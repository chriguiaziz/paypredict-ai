"""Hachage des mots de passe (argon2) et jetons JWT."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone   # dates avec fuseau, durées

import jwt                                            # bibliothèque PyJWT : créer et lire des jetons
from argon2 import PasswordHasher                     # hachage de mots de passe (algorithme argon2)
from argon2.exceptions import InvalidHashError, VerificationError   # erreurs de vérification

from app.core.config import get_settings              # paramètres (secret JWT, durée de validité)

# Un seul "hacheur" réutilisé partout, avec les réglages par défaut recommandés d'argon2
_hasher = PasswordHasher()


# ---------------------------------------------------------------------------
# PARTIE 1 : les mots de passe
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    # Transforme "monMotDePasse" en une empreinte irréversible, à stocker en base.
    # Le mot de passe en clair n'est JAMAIS stocké ni journalisé.
    # Argon2 ajoute un "sel" aléatoire : deux mêmes mots de passe donnent deux empreintes différentes.
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    # Vérifie un mot de passe saisi contre l'empreinte stockée (au moment de la connexion)
    try:
        return _hasher.verify(hashed, plain)       # True si ça correspond
    except (VerificationError, InvalidHashError):
        return False                               # mauvais mot de passe, ou empreinte illisible


# ---------------------------------------------------------------------------
# PARTIE 2 : les jetons JWT (la "carte d'accès" remise après connexion)
# ---------------------------------------------------------------------------
def create_access_token(user_id: str, role: str) -> str:
    s = get_settings()                              # secret et durée de validité
    now = datetime.now(timezone.utc)                # heure actuelle, en UTC
    payload = {"sub": user_id,                      # "sub" (subject) : à qui appartient le jeton
               "role": role,                        # le rôle (informatif : l'API le relit en base)
               "iat": now,                          # "issued at" : date d'émission
               "exp": now + timedelta(minutes=s.access_token_minutes)}   # "exp" : date d'expiration
    # Signe le contenu avec le secret : toute modification du jeton le rend invalide
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Lève jwt.PyJWTError si le jeton est invalide ou expiré."""
    # Vérifie la signature ET la date d'expiration, puis renvoie le contenu (payload).
    # algorithms=["HS256"] impose l'algorithme accepté : cela bloque l'attaque
    # où un faux jeton prétend utiliser l'algorithme "none" (sans signature).
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])