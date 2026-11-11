from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm   # lit le formulaire "username" + "password"
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.database.session import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import TokenOut, UserOut
from app.services.audit import audit    # journal d'audit : qui a fait quoi

# Toutes les routes de ce fichier commencent par /auth ; "tags" les regroupe dans Swagger
router = APIRouter(prefix="/auth", tags=["auth"])

# Hash factice : permet de dépenser le même temps de calcul si l'e-mail n'existe pas
_DUMMY_HASH = hash_password("not-a-real-password")


# ---------------------------------------------------------------------------
# ROUTE 1 : POST /auth/login (se connecter et recevoir un jeton)
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 1) Cherche l'utilisateur par e-mail (mis en minuscules ; le formulaire appelle l'e-mail "username")
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    # 2) Vérifie le mot de passe. Si l'e-mail n'existe pas, on vérifie quand même contre un faux hash :
    #    le temps de réponse est le même, donc on ne peut pas deviner quels e-mails existent.
    ok = verify_password(form.password, user.hashed_password if user else _DUMMY_HASH)
    # 3) Échec : e-mail inconnu, mauvais mot de passe, ou compte désactivé
    if not user or not ok or not user.is_active:
        audit(db, None, "login_failed", "user", None, {"email": form.username.lower()})   # trace la tentative
        db.commit()
        # Même message dans tous les cas : ne pas révéler si l'e-mail existe
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants incorrects")
    # 4) Succès : trace la connexion et remet un jeton signé (valable 60 minutes par défaut)
    audit(db, user.user_id, "login", "user", user.user_id)
    db.commit()
    return TokenOut(access_token=create_access_token(str(user.user_id), user.role.role_name))


# ---------------------------------------------------------------------------
# ROUTE 2 : GET /auth/me (qui suis-je ?)
# ---------------------------------------------------------------------------
@router.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)):
    # get_current_user a déjà vérifié le jeton et chargé l'utilisateur : on renvoie ses infos (sans mot de passe)
    return UserOut(user_id=user.user_id, email=user.email, full_name=user.full_name,
                   role=user.role.role_name)