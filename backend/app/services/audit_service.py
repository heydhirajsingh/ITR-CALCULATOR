"""Centralized persistent audit logging."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.entities import AuditLog


def log_event(
    db: Session,
    event_type: str,
    message: str,
    *,
    level: str = "INFO",
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            level=level,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            message=message,
            details=details or {},
        )
    )
