"""Importer tous les modèles ici : Alembic doit les voir pour générer les migrations."""
from app.models.auth import Role, User # noqa: F401
from app.models.finance import Customer, Invoice, Payment # noqa: F401
from app.models.ml import ModelMetric, ModelVersion, Prediction, Recommendation # noqa:F401
from app.models.ops import (ApprovalRequest, AppSetting, AuditLog, ReminderLog, # noqa:F401, 
                            WorkflowLog)
