"""HTTP client for the DailyTodo sync server."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class SyncClientError(RuntimeError):
    """Raised when the sync server request fails."""


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
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SyncClientError(f"HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise SyncClientError(f"Network error: {exc.reason}") from exc
        except OSError as exc:
            raise SyncClientError(f"Network error: {exc}") from exc

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
