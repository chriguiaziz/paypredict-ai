"""Tables d'exploitation : rappels, workflows, approbations, audit, paramètres."""
import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base, created_at_col, uuid_pk
class ReminderLog(Base):
    __tablename__ = "reminder_logs"
    reminder_id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("invoices.invoice_id"), nullable=False)
    reminder_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Clé d'idempotence = "<invoice_id>:<reminder_type>" : un rappel par type et par facture
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    send_status: Mapped[str] = mapped_column(String(20), nullable=False, default="Pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_message_id: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (
    CheckConstraint(
    "send_status IN ('Pending','Approved','Sent','Failed','Rejected')",
    name="status_valid"),
    Index("ix_reminder_logs_invoice_id", "invoice_id"),
    )
class WorkflowLog(Base):
    __tablename__ = "workflow_logs"
    log_id: Mapped[uuid.UUID] = uuid_pk()
    workflow_name: Mapped[str] = mapped_column(String(80), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(80), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    execution_metadata: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
    CheckConstraint(
    "execution_status IN ('Running','Success','Failed')", name="status_valid"),
    Index("ix_workflow_logs_name_started", "workflow_name", "started_at"),
    )
class ApprovalRequest(Base):
    """Demande d'approbation humaine avant l'envoi d'un rappel (workflow 4)."""
    __tablename__ = "approval_requests"
    approval_id: Mapped[uuid.UUID] = uuid_pk()
    reminder_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("reminder_logs.reminder_id"), nullable=False)
    resume_url: Mapped[str | None] = mapped_column(String(500)) # URL de reprise du Wait node n8n
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
    ForeignKey("users.user_id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (
    CheckConstraint("status IN ('Pending','Approved','Rejected')", name="status_valid"),
    )
class AuditLog(Base):
    __tablename__ = "audit_logs"
    audit_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
    ForeignKey("users.user_id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)
class AppSetting(Base):
    """Paramètres modifiables (seuils de risque, notifications...)."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = created_at_col()