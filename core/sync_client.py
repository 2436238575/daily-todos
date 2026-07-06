"""HTTP client for the DailyTodo sync server."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class SyncClientError(RuntimeError):
    """Raised when the sync server request fails."""


SENSITIVE_FIELDS = ("authorization", "password", "token")


@dataclass(frozen=True)
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_in: int
    server_version: int


class SyncClient:
    def __init__(self, server_url: str, *, timeout: int = 10) -> None:
        self.server_url = server_url.rstrip("/") + "/"
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    def login(self, username: str, password: str, device_name: str) -> TokenBundle:
        payload = self._request(
            "POST",
            "v1/auth/login",
            {"username": username, "password": password, "device_name": device_name},
        )
        return self._token_bundle(payload)

    def refresh(self, refresh_token: str) -> TokenBundle:
        payload = self._request("POST", "v1/auth/refresh", {"refresh_token": refresh_token})
        return self._token_bundle(payload)

    def logout(self, access_token: str, refresh_token: str) -> None:
        self._request(
            "POST",
            "v1/auth/logout",
            {"refresh_token": refresh_token},
            access_token=access_token,
        )

    def push(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "v1/sync/push", payload, access_token=access_token)

    def pull(self, access_token: str, since: int) -> dict[str, Any]:
        return self._request("GET", f"v1/sync/pull?since={since}", access_token=access_token)

    def resolve(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "v1/sync/resolve", payload, access_token=access_token)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        request = Request(urljoin(self.server_url, path), data=body, headers=headers, method=method)
        started = time.monotonic()
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = response.read()
                status = getattr(response, "status", 200)
        except HTTPError as exc:
            duration_ms = (time.monotonic() - started) * 1000
            detail = _sanitize_error_detail(exc.read().decode("utf-8", errors="replace"))
            self.logger.warning("HTTP: %s %s %s %.3fms", exc.code, method, path, duration_ms)
            raise SyncClientError(f"HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            duration_ms = (time.monotonic() - started) * 1000
            self.logger.warning("HTTP: NetworkError %s %s %.3fms", method, path, duration_ms)
            raise SyncClientError(f"Network error: {exc.reason}") from exc
        except OSError as exc:
            duration_ms = (time.monotonic() - started) * 1000
            self.logger.warning("HTTP: NetworkError %s %s %.3fms", method, path, duration_ms)
            raise SyncClientError(f"Network error: {exc}") from exc

        duration_ms = (time.monotonic() - started) * 1000
        self.logger.info("HTTP: %s %s %s %.3fms", status, method, path, duration_ms)
        if not data:
            return {}
        try:
            parsed = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SyncClientError("Server returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise SyncClientError("Server returned an unexpected response")
        return parsed

    @staticmethod
    def _token_bundle(payload: dict[str, Any]) -> TokenBundle:
        return TokenBundle(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_in=int(payload["expires_in"]),
            server_version=int(payload.get("server_version", 0)),
        )


def _sanitize_error_detail(detail: str) -> str:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return detail
    return json.dumps(_sanitize_value(payload), ensure_ascii=False)


def _sanitize_value(value: Any, sensitive_context: bool = False) -> Any:
    if isinstance(value, dict):
        loc = value.get("loc")
        loc_sensitive = sensitive_context or (
            isinstance(loc, list)
            and any(_is_sensitive_name(str(part)) for part in loc)
        )
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_sensitive = sensitive_context or _is_sensitive_name(str(key))
            if key == "input" and (loc_sensitive or key_sensitive):
                sanitized[key] = "***"
            else:
                sanitized[key] = _sanitize_value(item, key_sensitive)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, sensitive_context) for item in value]
    if sensitive_context and isinstance(value, str):
        return "***"
    return value


def _is_sensitive_name(name: str) -> bool:
    lower = name.lower()
    return any(field in lower for field in SENSITIVE_FIELDS)
