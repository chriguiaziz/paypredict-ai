"""Lecture des paramètres métier stockés en base (table app_settings)."""
from __future__ import annotations
from datetime import date
from sqlalchemy.orm import Session
from app.models import AppSetting
DEFAULTS = {
"risk_thresholds": {"medium_min": 0.30, "high_min": 0.70},
"reference_date": {"date": "2025-12-31"},
}
def get_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    return row.value if row else DEFAULTS[key]
def reference_date(db: Session) -> date:
    return date.fromisoformat(get_setting(db, "reference_date")["date"])
def risk_level(probability: float, thresholds: dict) -> str:
    if probability >= thresholds["high_min"]:
        return "High"
    if probability >= thresholds["medium_min"]:
        return "Medium"
    return "Low"