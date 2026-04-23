"""Audit helpers for manual changes."""

from __future__ import annotations

from sqlite3 import Connection
from typing import Mapping

from gtv.repositories import audit as audit_repo


def audit_diff(
    connection: Connection,
    *,
    user_email: str,
    entity_type: str,
    entity_id: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
    context: str | None = None,
) -> None:
    for field_name, new_value in after.items():
        old_value = before.get(field_name)
        if str(old_value or "") == str(new_value or ""):
            continue
        audit_repo.log_change(
            connection,
            user_email=user_email,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            context=context,
        )


def audit_event(
    connection: Connection,
    *,
    user_email: str,
    entity_type: str,
    entity_id: str,
    action: str,
    context: str | None = None,
) -> None:
    audit_repo.log_change(
        connection,
        user_email=user_email,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=action,
        old_value=None,
        new_value=None,
        context=context,
    )
