"""Synchronize local DailyTodo data with the HTTP backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from core.database import Database
from core.sync_client import SyncClient, SyncClientError, TokenBundle
from lib.utils import load_settings, save_settings


SyncMode = Literal["upload", "download", "merge", "normal"]


@dataclass(frozen=True)
class SyncResult:
    message: str
    conflicts: list[dict[str, Any]]


class SyncManager:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.logger = logging.getLogger(__name__)
        self.last_conflicts: list[dict[str, Any]] = []

    def login(self, server_url: str, username: str, password: str, *, device_name: str = "desktop") -> SyncResult:
        server_url = server_url.strip()
        username = username.strip()
        if not server_url:
            raise ValueError("Server URL cannot be empty")
        if not username:
            raise ValueError("Username cannot be empty")
        bundle = SyncClient(server_url).login(username, password, device_name)
        settings = load_settings()
        settings["sync"].update(
            {
                "server_url": server_url,
                "username": username,
                "refresh_token": bundle.refresh_token,
                "last_server_version": bundle.server_version,
            }
        )
        save_settings(settings)
        return SyncResult("登录成功。", [])

    def logout(self) -> SyncResult:
        settings = load_settings()
        sync = settings["sync"]
        refresh_token = str(sync.get("refresh_token", ""))
        if refresh_token and sync.get("server_url"):
            try:
                client, bundle = self._refresh(settings)
                client.logout(bundle.access_token, bundle.refresh_token)
            except Exception:
                self.logger.exception("Remote logout failed; clearing local token anyway")
        sync.update({"refresh_token": "", "initialized": False})
        save_settings(settings)
        self.last_conflicts = []
        return SyncResult("已退出登录。", [])

    def sync(self, mode: SyncMode = "normal") -> SyncResult:
        settings = load_settings()
        client, bundle = self._refresh(settings)
        sync = settings["sync"]
        access_token = bundle.access_token
        starting_version = int(sync.get("last_server_version", 0) or 0)
        last_version = starting_version

        accepted_count = 0
        conflicts: list[dict[str, Any]] = []

        if mode == "download":
            self.database.backup_before_cloud_download()
            self.database.prepare_for_cloud_download()
            settings["daily_template"] = []
            pull_since = 0
        else:
            push_payload = self._build_push_payload(settings)
            if push_payload["tasks"] or push_payload["template_items"]:
                pushed = client.push(access_token, push_payload)
                accepted_count += self._apply_accepted(pushed.get("accepted", []), settings)
                conflicts.extend(list(pushed.get("conflicts", [])))
                last_version = max(last_version, int(pushed.get("server_version", last_version)))
            pull_since = 0 if mode in {"upload", "merge"} and not sync.get("initialized") else starting_version

        pulled = client.pull(access_token, pull_since)
        conflicts.extend(list(pulled.get("conflicts", [])))
        self._apply_pull(pulled, settings, conflicts)
        last_version = int(pulled.get("server_version", last_version))

        sync.update(
            {
                "refresh_token": bundle.refresh_token,
                "last_server_version": last_version,
                "initialized": True,
                "last_sync_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        save_settings(settings)
        self.last_conflicts = conflicts
        if conflicts:
            return SyncResult(f"同步完成，发现 {len(conflicts)} 个冲突。", conflicts)
        return SyncResult(f"同步完成，已上传 {accepted_count} 项变更。", [])

    def resolve_conflicts(self, resolutions: list[dict[str, Any]]) -> SyncResult:
        if not resolutions:
            return SyncResult("没有需要解决的冲突。", [])
        settings = load_settings()
        client, bundle = self._refresh(settings)
        response = client.resolve(bundle.access_token, {"resolutions": resolutions})
        accepted = response.get("accepted", [])
        self._apply_accepted(accepted, settings)
        for resolution in resolutions:
            if resolution.get("choice") == "remote":
                conflict = self._find_conflict(str(resolution.get("conflict_id")))
                if conflict:
                    self._apply_remote_payload(conflict, settings)
        settings["sync"].update(
            {
                "refresh_token": bundle.refresh_token,
                "last_server_version": int(response.get("server_version", settings["sync"].get("last_server_version", 0))),
                "last_sync_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        save_settings(settings)
        resolved_ids = {str(item.get("conflict_id")) for item in resolutions}
        self.last_conflicts = [conflict for conflict in self.last_conflicts if str(conflict.get("id")) not in resolved_ids]
        return SyncResult(f"已解决 {len(resolutions)} 个冲突。", self.last_conflicts)

    def _refresh(self, settings: dict[str, Any]) -> tuple[SyncClient, TokenBundle]:
        sync = settings["sync"]
        server_url = str(sync.get("server_url", "")).strip()
        refresh_token = str(sync.get("refresh_token", ""))
        if not server_url or not refresh_token:
            raise ValueError("请先登录同步账号。")
        client = SyncClient(server_url)
        bundle = client.refresh(refresh_token)
        sync["refresh_token"] = bundle.refresh_token
        save_settings(settings)
        return client, bundle

    def _build_push_payload(self, settings: dict[str, Any]) -> dict[str, Any]:
        tasks = [
            {
                "id": str(row["uid"]),
                "base_version": int(row["base_version"]),
                "content": str(row["content"]),
                "target_date": str(row["target_date"]),
                "completed": bool(row["is_completed"]),
                "sort_order": int(row["sort_order"]),
                "deleted": row["deleted_at"] is not None,
            }
            for row in self.database.get_dirty_tasks()
        ]
        template_items = [
            {
                "id": str(item["uid"]),
                "base_version": int(item.get("base_version", 0)),
                "content": str(item["content"]),
                "sort_order": int(item.get("sort_order", 0)),
                "deleted": bool(item.get("deleted", False)),
            }
            for item in settings.get("daily_template", [])
            if bool(item.get("sync_dirty", True))
        ]
        return {"tasks": tasks, "template_items": template_items}

    def _apply_accepted(self, accepted: list[dict[str, Any]], settings: dict[str, Any]) -> int:
        count = 0
        template_versions: dict[str, int] = {}
        for item in accepted:
            entity_type = str(item.get("entity_type", ""))
            entity_id = str(item.get("entity_id", ""))
            version = int(item.get("version", 0))
            if entity_type == "task":
                self.database.mark_task_synced(entity_id, version)
                count += 1
            elif entity_type == "template_item":
                template_versions[entity_id] = version
                count += 1
        if template_versions:
            for item in settings.get("daily_template", []):
                if item.get("uid") in template_versions:
                    item["base_version"] = template_versions[item["uid"]]
                    item["sync_dirty"] = False
            settings["daily_template"] = [
                item for item in settings.get("daily_template", [])
                if not (bool(item.get("deleted", False)) and not bool(item.get("sync_dirty", False)))
            ]
            save_settings(settings)
        return count

    def _apply_pull(
        self,
        payload: dict[str, Any],
        settings: dict[str, Any],
        conflicts: list[dict[str, Any]],
    ) -> None:
        conflicted_tasks = {
            str(conflict.get("entity_id"))
            for conflict in conflicts
            if conflict.get("entity_type") == "task"
        }
        conflicted_templates = {
            str(conflict.get("entity_id"))
            for conflict in conflicts
            if conflict.get("entity_type") == "template_item"
        }
        for task in payload.get("tasks", []):
            if str(task.get("id")) in conflicted_tasks:
                continue
            self.database.upsert_remote_task(task)
        if payload.get("template_items"):
            self._apply_remote_template_items(
                [
                    item for item in payload.get("template_items", [])
                    if str(item.get("id")) not in conflicted_templates
                ],
                settings,
            )

    def _apply_remote_template_items(self, records: list[dict[str, Any]], settings: dict[str, Any]) -> None:
        current = {str(item["uid"]): item for item in settings.get("daily_template", [])}
        for record in records:
            uid = str(record["id"])
            if bool(record.get("deleted", False)):
                if uid in current:
                    current[uid]["deleted"] = True
                    current[uid]["base_version"] = int(record.get("version", 0))
                    current[uid]["sync_dirty"] = False
                continue
            current[uid] = {
                "uid": uid,
                "content": str(record.get("content", "")),
                "sort_order": int(record.get("sort_order", 0)),
                "base_version": int(record.get("version", 0)),
                "deleted": False,
                "sync_dirty": False,
            }
        settings["daily_template"] = [
            item for item in sorted(current.values(), key=lambda value: int(value.get("sort_order", 0)))
            if not (bool(item.get("deleted", False)) and not bool(item.get("sync_dirty", False)))
        ]
        save_settings(settings)

    def _find_conflict(self, conflict_id: str) -> dict[str, Any] | None:
        for conflict in self.last_conflicts:
            if str(conflict.get("id")) == conflict_id:
                return conflict
        return None

    def _apply_remote_payload(self, conflict: dict[str, Any], settings: dict[str, Any]) -> None:
        if conflict.get("entity_type") == "task":
            payload = dict(conflict.get("server_payload", {}))
            payload["id"] = conflict.get("entity_id")
            self.database.upsert_remote_task(payload)
            return
        payload = dict(conflict.get("server_payload", {}))
        payload["id"] = conflict.get("entity_id")
        self._apply_remote_template_items([payload], settings)


def sync_error_message(exc: Exception) -> str:
    if isinstance(exc, SyncClientError):
        return str(exc)
    return str(exc) or exc.__class__.__name__
