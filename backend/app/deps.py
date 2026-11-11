"""Dépendances FastAPI : utilisateur courant, rôles, clé d'automatisation."""
from __future__ import annotations

import secrets   # comparaison sécurisée de chaînes
import uuid      # convertir l'identifiant texte du jeton en UUID

import jwt       # pour attraper les erreurs de jeton (PyJWTError)
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer   # lit le jeton dans l'en-tête "Authorization: Bearer ..."
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_token
from app.database.session import get_db    # fournit une session de base de données par requête
from app.models import User

# Indique à FastAPI où se trouve la route de connexion ; active le bouton "Authorize" dans Swagger
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Hiérarchie : admin > analyst > viewer (un rang plus élevé a plus de droits)
ROLE_RANK = {"viewer": 1, "analyst": 2, "admin": 3}


# ---------------------------------------------------------------------------
# PARTIE 1 : qui est l'utilisateur connecté ?
# ---------------------------------------------------------------------------
def get_current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    # L'erreur renvoyée dans tous les cas d'échec : 401 (non authentifié).
    # Un seul message pour tous les cas, afin de ne rien révéler à un attaquant.
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton invalide ou expiré",
                                 headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(token)                       # vérifie la signature et l'expiration
        user = db.get(User, uuid.UUID(payload["sub"]))      # relit l'utilisateur EN BASE
    except (jwt.PyJWTError, KeyError, ValueError):
        # jeton falsifié ou expiré (PyJWTError), champ "sub" absent (KeyError), identifiant invalide (ValueError)
        raise unauthorized
    if user is None or not user.is_active:                  # compte supprimé ou désactivé
        raise unauthorized
    return user


# ---------------------------------------------------------------------------
# PARTIE 2 : l'utilisateur a-t-il le droit ?
# ---------------------------------------------------------------------------
def require_role(minimum: str):
    """Exige au moins le rôle `minimum` (viewer < analyst < admin)."""
    def checker(user: User = Depends(get_current_user)) -> User:
        # Compare le rang de l'utilisateur au rang minimal exigé (0 si rôle inconnu)
        if ROLE_RANK.get(user.role.role_name, 0) < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Droits insuffisants")   # connecté, mais pas autorisé
        return user
    return checker    # on renvoie la fonction de contrôle, que FastAPI appellera à chaque requête


# ---------------------------------------------------------------------------
# PARTIE 3 : authentifier n8n (machine à machine)
# ---------------------------------------------------------------------------
def require_automation_key(x_api_key: str = Header(default="")) -> None:
    """Authentifie n8n (appels machine à machine) par clé partagée, comparaison à temps constant."""
    # Lit l'en-tête "X-API-Key" et le compare à la clé configurée dans .env.
    # compare_digest prend le même temps que les chaînes soient proches ou non :
    # cela empêche de deviner la clé caractère par caractère en mesurant le temps de réponse.
    if not secrets.compare_digest(x_api_key, get_settings().automation_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Clé d'automatisation invalide")