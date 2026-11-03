"""Invalidate key helpers for live WebSocket pull signals."""

from __future__ import annotations

from typing import Any


def key(name: str, id: str | None = None) -> dict[str, str]:
    spec: dict[str, str] = {"key": name}
    if id is not None:
        spec["id"] = str(id)
    return spec


def money_actor_keys(*, dashboard: str | None = None) -> list[dict[str, str]]:
    keys = [key("balance"), key("balanceTx"), key("notifications")]
    if dashboard:
        keys.append(key(dashboard))
    return keys


def role_dashboard(user, role: str | None = None) -> str | None:
    if role == "merchant":
        return "merchantDashboard"
    if role == "investor":
        return "investorDashboard"
    if getattr(user, "is_admin", False):
        return "adminDashboard"
    if getattr(user, "has_merchant", False) and not getattr(user, "has_investor", False):
        return "merchantDashboard"
    if getattr(user, "has_investor", False) and not getattr(user, "has_merchant", False):
        return "investorDashboard"
    if getattr(user, "has_merchant", False):
        return "merchantDashboard"
    if getattr(user, "has_investor", False):
        return "investorDashboard"
    return None


def normalize_keys(keys: list[Any] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in keys or []:
        if isinstance(item, str):
            spec = {"key": item}
        elif isinstance(item, dict):
            name = item.get("key")
            if not name:
                continue
            spec = {"key": str(name)}
            if item.get("id") is not None:
                spec["id"] = str(item["id"])
        else:
            continue
        token = f"{spec['key']}:{spec.get('id', '')}"
        if token in seen:
            continue
        seen.add(token)
        out.append(spec)
        if len(out) >= 12:
            break
    return out
