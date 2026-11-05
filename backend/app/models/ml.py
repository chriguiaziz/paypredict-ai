import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
Numeric,
String, Text, func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base, created_at_col, uuid_pk
class ModelVersion(Base):
    __tablename__ = "model_versions"
    model_version_id: Mapped[uuid.UUID] = uuid_pk()
    model_version: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(60), nullable=False)
    training_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True),
    nullable=False)
    training_dataset_version: Mapped[str] = mapped_column(String(60), nullable=False)
    feature_list: Mapped[list] = mapped_column(JSONB, nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (
    # Une seule version active à la fois (index unique partiel PostgreSQL)
    Index("uq_model_versions_single_active", "is_active", unique=True,
    postgresql_where="is_active"),
    )
class ModelMetric(Base):
    __tablename__ = "model_metrics"
    metric_id: Mapped[uuid.UUID] = uuid_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("model_versions.model_version_id"), nullable=False)
    dataset_split: Mapped[str] = mapped_column(String(20), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(40), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (
    CheckConstraint("dataset_split IN ('train','validation','test')",
    name="split_valid"),
    Index("ix_model_metrics_model_version_id", "model_version_id"),
    )
class Prediction(Base):
    __tablename__ = "predictions"
    prediction_id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("invoices.invoice_id"), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    predicted_probability: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    prediction_timestamp: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), server_default=func.now(), nullable=False)
    prediction_horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    explanation_data: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
    CheckConstraint("predicted_probability BETWEEN 0 AND 1", name="probability_bounds"),
    CheckConstraint("risk_score BETWEEN 0 AND 100", name="score_bounds"),
    CheckConstraint("risk_level IN ('Low','Medium','High')", name="level_valid"),
    Index("ix_predictions_invoice_ts", "invoice_id", "prediction_timestamp"),
    Index("ix_predictions_risk_level", "risk_level"),
    )
class Recommendation(Base):
    __tablename__ = "recommendations"
    recommendation_id: Mapped[uuid.UUID] = uuid_pk()
    prediction_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("predictions.prediction_id"), nullable=False)
    recommendation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)
    action_status: Mapped[str] = mapped_column(String(20), nullable=False,
    default="Pending")
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (
    CheckConstraint("priority IN ('Low','Medium','High')", name="priority_valid"),
    CheckConstraint(
    "action_status IN ('Pending','Accepted','Rejected','Done')",
    name="status_valid"),
    Index("ix_recommendations_prediction_id", "prediction_id"),
    )
