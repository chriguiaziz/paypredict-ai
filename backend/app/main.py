"""Point d'entrée FastAPI."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware   # autorise (ou non) les appels venant d'un autre site/port
from sqlalchemy import text

from app.core.config import get_settings             # lit le fichier .env (nom de l'app, origines CORS...)
from app.database.session import engine              # connexion à PostgreSQL (utilisée par /health)
from app.routers import auth, customers, dashboard, invoices, models, predictions

settings = get_settings()

# L'objet "app" EST l'API : uvicorn le lance avec `uvicorn app.main:app`
# (dossier app / fichier main / variable app). Le titre et la description s'affichent dans Swagger (/docs).
app = FastAPI(title=settings.app_name, version="1.0.0",
              description="API de prédiction des retards de paiement (données synthétiques).")

# --- CORS : qui a le droit d'appeler l'API depuis un navigateur ? ---
# Le frontend (http://localhost:5173) et l'API (http://localhost:8000) sont deux "origines" différentes :
# sans CORS, le navigateur bloquerait les appels du frontend vers l'API.
app.add_middleware(
    CORSMiddleware,
    # La liste vient du .env (CORS_ORIGINS="http://localhost:5173,..."), découpée sur les virgules.
    # Jamais "*" : sinon n'importe quel site pourrait appeler l'API avec la session d'un utilisateur connecté.
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,                                        # autorise l'envoi du jeton / cookies
    allow_methods=["GET", "POST", "PATCH", "DELETE"],              # uniquement les méthodes utilisées
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],  # uniquement les en-têtes utilisés
)

# --- Branchement des 6 groupes de routes, tous sous /api/v1 ---
# Le préfixe "v1" permet de sortir un jour une v2 sans casser les clients (frontend, n8n, Power BI).
PREFIX = "/api/v1"
for r in (auth.router, customers.router, invoices.router, predictions.router, dashboard.router, models.router):
    app.include_router(r, prefix=PREFIX)


# --- Route de santé (hors /api/v1) : sert à Docker Compose et à toi pour vérifier que tout tourne ---
@app.get("/health", tags=["health"])
def health():
    """Santé de l'API et de la base (utilisé par Docker Compose)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))       # requête la plus simple possible : "la base répond-elle ?"
        return {"status": "ok", "database": "ok"}
    except Exception:  # noqa: BLE001
        # On ne plante pas : on répond "degraded" (l'API tourne, mais la base est injoignable)
        return {"status": "degraded", "database": "unreachable"}