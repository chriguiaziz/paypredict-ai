from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_current_user
from app.services.prediction import ARTIFACTS, NoActiveModel, active_version

# Toutes les routes de ce fichier commencent par /models
router = APIRouter(prefix="/models", tags=["models"])


# ---------------------------------------------------------------------------
# ROUTE UNIQUE : GET /models/active -> la fiche d'identité du modèle actuellement utilisé
# Accessible à tout utilisateur connecté (viewer ou plus).
# ---------------------------------------------------------------------------
@router.get("/active")
def active_model(_=Depends(get_current_user)):
    try:
        # Lit ml/artifacts/active.json pour savoir quelle version est active
        version = active_version()
    except NoActiveModel as exc:
        # Aucun modèle entraîné et activé -> 503 (service indisponible), comme pour /predict
        raise HTTPException(503, str(exc))
    # Chaque version a un dossier ml/artifacts/<version>/ avec un metadata.json
    # (écrit par train.py) : algorithme, date d'entraînement, métriques, seuil métier...
    meta = json.loads((ARTIFACTS / version / "metadata.json").read_text(encoding="utf-8"))
    # On ne renvoie qu'une sélection de champs (liste blanche) : on n'expose pas la liste
    # complète des variables ni les métriques de validation, seulement l'essentiel.
    return {k: meta[k] for k in ("model_version", "algorithm", "trained_at", "training_dataset_version",
                                 "business_threshold", "test_at_business_threshold", "synthetic_data_warning")}