from __future__ import annotations
from sqlalchemy.orm import Session
from app.models import AuditLog
def audit(db: Session, user_id, action: str, entity_type: str, entity_id=None, details: dict | None = None) -> None:
    """Ajoute une ligne d'audit à la transaction en cours (commit fait par l'appelant)."""
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id else None, details=details))