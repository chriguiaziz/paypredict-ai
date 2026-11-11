from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.deps import get_current_user, require_role
from app.models import Prediction, Recommendation
from app.schemas import PredictionOut, RecommendationOut, RecommendationStatusIn
from app.services.audit import audit
from app.services.prediction import NoActiveModel, predict_invoice

router = APIRouter(tags=["predictions"])


# ---------------------------------------------------------------------------
# ROUTE 1 : POST /invoices/{id}/predict (calculer le risque d'une facture) : analyst minimum
# ---------------------------------------------------------------------------
@router.post("/invoices/{invoice_id}/predict", response_model=PredictionOut)
def predict(invoice_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(require_role("analyst"))):
    try:
        pred = predict_invoice(db, invoice_id)     # le service fait tout le travail (modèle, SHAP, recommandation)
    except LookupError as exc:                     # facture introuvable
        raise HTTPException(404, str(exc))
    except ValueError as exc:                      # facture non éligible (annulée, payée, litige...)
        raise HTTPException(422, str(exc))
    except NoActiveModel as exc:                   # aucun modèle entraîné et activé
        raise HTTPException(503, str(exc))         # 503 = service indisponible
    audit(db, user.user_id, "predict", "invoice", invoice_id, {"model": pred.model_version})
    db.commit()                                    # valide prédiction + recommandation + audit ensemble
    return pred


# ---------------------------------------------------------------------------
# ROUTE 2 : GET /invoices/{id}/predictions (historique des prédictions d'une facture)
# ---------------------------------------------------------------------------
@router.get("/invoices/{invoice_id}/predictions", response_model=list[PredictionOut])
def history(invoice_id: uuid.UUID, db: Session = Depends(get_db), _=Depends(get_current_user)):
    # Toutes les prédictions de cette facture, de la plus récente à la plus ancienne
    return db.scalars(select(Prediction).where(Prediction.invoice_id == invoice_id)
                      .order_by(Prediction.prediction_timestamp.desc())).all()


# ---------------------------------------------------------------------------
# ROUTE 3 : GET /predictions/high-risk (les factures les plus risquées)
# ---------------------------------------------------------------------------
@router.get("/predictions/high-risk", response_model=list[PredictionOut])
def high_risk(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Dernière prédiction de chaque facture, niveau High uniquement."""
    # Sous-requête : pour chaque facture, la date de sa prédiction la plus récente
    # (DISTINCT ON est une fonction propre à PostgreSQL)
    latest = (select(Prediction.invoice_id, Prediction.prediction_timestamp)
              .distinct(Prediction.invoice_id)
              .order_by(Prediction.invoice_id, Prediction.prediction_timestamp.desc()).subquery())
    # On joint pour ne garder que ces dernières prédictions, puis seulement le niveau High,
    # triées de la probabilité la plus forte à la plus faible
    stmt = (select(Prediction).join(latest, (Prediction.invoice_id == latest.c.invoice_id)
                                    & (Prediction.prediction_timestamp == latest.c.prediction_timestamp))
            .where(Prediction.risk_level == "High")
            .order_by(Prediction.predicted_probability.desc()).limit(limit))
    return db.scalars(stmt).all()


# ---------------------------------------------------------------------------
# ROUTE 4 : GET /recommendations (liste des recommandations)
# ---------------------------------------------------------------------------
@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(action_status: str | None = None, priority: str | None = None,
                         limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
                         _=Depends(get_current_user)):
    stmt = select(Recommendation)
    if action_status:                                         # filtre facultatif : ?action_status=Pending
        stmt = stmt.where(Recommendation.action_status == action_status)
    if priority:                                              # filtre facultatif : ?priority=High
        stmt = stmt.where(Recommendation.priority == priority)
    return db.scalars(stmt.order_by(Recommendation.created_at.desc()).limit(limit)).all()


# ---------------------------------------------------------------------------
# ROUTE 5 : PATCH /recommendations/{id} (accepter, refuser ou marquer comme faite) : analyst minimum
# ---------------------------------------------------------------------------
@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationOut)
def update_recommendation(recommendation_id: uuid.UUID, body: RecommendationStatusIn,
                          db: Session = Depends(get_db), user=Depends(require_role("analyst"))):
    rec = db.get(Recommendation, recommendation_id)
    if not rec:
        raise HTTPException(404, "Recommandation introuvable")
    rec.action_status = body.action_status                    # Accepted, Rejected ou Done (validé par le schéma)
    audit(db, user.user_id, "update_status", "recommendation", recommendation_id,
          {"action_status": body.action_status})
    db.commit()
    return rec