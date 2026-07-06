"""Small helpers shared by sync code and tests."""

from __future__ import annotations

from typing import Any


ENTITY_LABELS = {
    "task": "任务",
    "template_item": "母本",
}


def merge_conflicts(
    current: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = {str(conflict.get("id")) for conflict in current}
    merged = list(current)
    for conflict in incoming:
        conflict_id = str(conflict.get("id"))
        if conflict_id in seen:
            continue
        seen.add(conflict_id)
        merged.append(conflict)
    return merged


def dedupe_resolutions(resolutions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for resolution in resolutions:
        conflict_id = str(resolution.get("conflict_id"))
        if conflict_id in seen:
            continue
        seen.add(conflict_id)
        deduped.append(resolution)
    return deduped


def sync_change_lines(
    *,
    accepted: list[dict[str, Any]],
    pushed: dict[str, list[dict[str, Any]]],
    pulled: dict[str, Any],
    conflicts: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    pushed_by_key = {
        (entity_type, str(item.get("id"))): item
        for entity_type, items in (
            ("task", pushed.get("tasks", [])),
            ("template_item", pushed.get("template_items", [])),
        )
        for item in items
    }
    for item in accepted:
        entity_type = str(item.get("entity_type", ""))
        entity_id = str(item.get("entity_id", ""))
        payload = pushed_by_key.get((entity_type, entity_id), {})
        lines.append(_format_change_line("上传", entity_type, payload))

    accepted_keys = {
        (str(item.get("entity_type")), str(item.get("entity_id")))
        for item in accepted
    }
    conflicted = {
        (str(conflict.get("entity_type")), str(conflict.get("entity_id")))
        for conflict in conflicts
    }
    for task in pulled.get("tasks", []):
        key = ("task", str(task.get("id")))
        if key not in accepted_keys and key not in conflicted:
            lines.append(_format_change_line("下载", "task", task))
    for item in pulled.get("template_items", []):
        key = ("template_item", str(item.get("id")))
        if key not in accepted_keys and key not in conflicted:
            lines.append(_format_change_line("下载", "template_item", item))
    return lines


def sync_change_counts(change_lines: list[str]) -> tuple[int, int]:
    additions = sum(1 for line in change_lines if line.startswith("+"))
    deletions = sum(1 for line in change_lines if line.startswith("-"))
    return additions, deletions


def sync_summary_message(change_lines: list[str], conflict_count: int = 0) -> str:
    if conflict_count:
        header = f"同步完成，发现 {conflict_count} 个冲突。"
    else:
        header = "同步完成"
    additions, deletions = sync_change_counts(change_lines)
    return f"{header}\n+{additions} -{deletions}"


def _format_change_line(direction: str, entity_type: str, payload: dict[str, Any]) -> str:
    marker = "-" if bool(payload.get("deleted", False)) else "+"
    label = ENTITY_LABELS.get(entity_type, entity_type or "项目")
    title = _payload_title(entity_type, payload)
    return f"{marker} {direction}{label}: {title}"


def _payload_title(entity_type: str, payload: dict[str, Any]) -> str:
    content = str(payload.get("content", "")).strip()
    if content:
        return content
    entity_id = str(payload.get("id", "")).strip()
    if entity_id:
        return entity_id
    return ENTITY_LABELS.get(entity_type, entity_type or "项目")
