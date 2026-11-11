"""Service de prédiction : charge le modèle actif, calcule les variables à la date d'émission,
prédit, explique (SHAP) et enregistre prédiction + recommandation."""
from __future__ import annotations

import json                                   # lire active.json
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache               # mémoriser le résultat d'une fonction
from pathlib import Path

import joblib                                 # recharger le modèle sauvegardé
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ml.explain import RiskExplainer                                 # explications SHAP (phase 2)
from ml.feature_engineering import FEATURE_COLUMNS, build_dataset    # MÊME code qu'à l'entraînement
from app.models import Customer, Invoice, Payment, Prediction, Recommendation
from app.services.recommendations import build_recommendation
from app.services.settings_store import get_setting, reference_date, risk_level

ARTIFACTS = Path(__file__).resolve().parents[2] / "ml" / "artifacts"   # backend/ml/artifacts/


class NoActiveModel(RuntimeError):
    # Erreur dédiée : aucun modèle n'a été entraîné et activé
    pass


# ---------------------------------------------------------------------------
# PARTIE 1 : trouver et charger le modèle actif
# ---------------------------------------------------------------------------
@lru_cache(maxsize=2)
def _load(version: str):
    # lru_cache : le fichier model.joblib est lu une seule fois, puis gardé en mémoire
    return joblib.load(ARTIFACTS / version / "model.joblib")


def active_version() -> str:
    # active.json (écrit par train.py --activate) indique quelle version utiliser
    pointer = ARTIFACTS / "active.json"
    if not pointer.exists():
        raise NoActiveModel("Aucun modèle actif : lance `python -m ml.train ... --activate`.")
    return json.loads(pointer.read_text(encoding="utf-8"))["model_version"]


# ---------------------------------------------------------------------------
# PARTIE 2 : charger les données d'UN client depuis la base
# ---------------------------------------------------------------------------
def _frames(db: Session, customer_id: uuid.UUID):
    """Charge UNIQUEMENT les données du client (les variables sont calculées par client)."""
    c = db.get(Customer, customer_id)
    # Le client, sous forme de tableau d'une ligne (même format que les CSV de la phase 1)
    customers = pd.DataFrame([{
        "customer_id": c.customer_id, "industry": c.industry, "country": c.country,
        "customer_segment": c.customer_segment, "registration_date": c.registration_date,
        "payment_terms_days": c.payment_terms_days, "credit_limit": c.credit_limit}])
    # Toutes ses factures
    invs = db.scalars(select(Invoice).where(Invoice.customer_id == customer_id)).all()
    invoices = pd.DataFrame([{
        "invoice_id": i.invoice_id, "customer_id": i.customer_id, "invoice_date": i.invoice_date,
        "due_date": i.due_date, "invoice_amount": i.invoice_amount, "currency": i.currency,
        "payment_terms_days": i.payment_terms_days, "invoice_status": i.invoice_status} for i in invs])
    # Tous les paiements de ces factures (colonnes imposées, au cas où il n'y en a aucun)
    pays = db.scalars(select(Payment).join(Invoice).where(Invoice.customer_id == customer_id)).all()
    payments = pd.DataFrame([{
        "invoice_id": p.invoice_id, "payment_date": p.payment_date, "payment_amount": p.payment_amount,
        "payment_status": p.payment_status} for p in pays],
        columns=["invoice_id", "payment_date", "payment_amount", "payment_status"])
    return customers, invoices, payments


# ---------------------------------------------------------------------------
# PARTIE 3 : le cœur du scoring (fonction PURE : aucune base de données)
# ---------------------------------------------------------------------------
def score_from_frames(customers, invoices, payments, invoice_id, ref: date, thresholds: dict) -> dict:
    """Cœur PUR du scoring (sans base de données) : facile à tester."""
    bundle = _load(active_version())      # modèle calibré + pipeline de base + version
    # Calcule les variables comme à l'entraînement, "à la date de référence"
    data = build_dataset(customers, invoices, payments, pd.Timestamp(ref))
    row = data[data["invoice_id"] == invoice_id]       # la ligne de la facture demandée
    if row.empty:
        raise ValueError("Facture exclue du jeu de variables")   # ex. annulée, brouillon, litige
    # Probabilité de retard (colonne 1 = classe "en retard"), via le modèle calibré
    proba = float(bundle["model"].predict_proba(row[FEATURE_COLUMNS])[:, 1][0])
    try:   # l'explication est un plus : son échec ne doit pas bloquer le score
        factors = RiskExplainer(bundle["base_pipeline"], row).explain(row, top_k=5)[0]
        explanation = {"top_factors": factors, "note": "Attribution du modèle, pas une causalité."}
    except Exception as exc:  # noqa: BLE001
        explanation = {"top_factors": [], "error": f"explication indisponible : {type(exc).__name__}"}
    return {"model_version": bundle["model_version"], "probability": proba,
            "risk_level": risk_level(proba, thresholds), "explanation": explanation,
            "amount_eur": float(row["invoice_amount_eur"].iloc[0])}


# ---------------------------------------------------------------------------
# PARTIE 4 : prédire une facture et enregistrer le résultat
# ---------------------------------------------------------------------------
def predict_invoice(db: Session, invoice_id: uuid.UUID) -> Prediction:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise LookupError("Facture introuvable")
    # Pas de prédiction pour une facture annulée, brouillon, en litige ou déjà payée
    if inv.invoice_status in ("Cancelled", "Draft", "Disputed", "Paid"):
        raise ValueError(f"Prédiction non applicable au statut « {inv.invoice_status} »")
    ref = reference_date(db)                            # "aujourd'hui" métier (31/12/2025)
    customers, invoices, payments = _frames(db, inv.customer_id)
    r = score_from_frames(customers, invoices, payments, invoice_id, ref, get_setting(db, "risk_thresholds"))

    # Enregistre la prédiction : probabilité, score 0-100, niveau, explications
    pred = Prediction(invoice_id=invoice_id, model_version=r["model_version"],
                      predicted_probability=round(r["probability"], 5),
                      risk_score=int(round(r["probability"] * 100)), risk_level=r["risk_level"],
                      prediction_timestamp=datetime.now(timezone.utc), prediction_horizon_days=0,
                      explanation_data=r["explanation"])
    db.add(pred)
    db.flush()    # envoie à la base pour obtenir prediction_id, sans valider la transaction
    # Recommandation associée : jours avant l'échéance = échéance - date de référence
    rec = build_recommendation(r["risk_level"], (inv.due_date - ref).days, r["amount_eur"])
    db.add(Recommendation(prediction_id=pred.prediction_id, **rec))
    return pred    # le commit est fait par l'appelant (la route)