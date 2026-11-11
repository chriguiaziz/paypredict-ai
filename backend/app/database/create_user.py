"""Crée un utilisateur (mot de passe saisi au clavier, jamais écrit dans le code ni dans Git).

Usage : python -m app.database.create_user --email admin@paypredict.test --name "Admin" --role admin
"""
from __future__ import annotations

import argparse   # lire les options de la ligne de commande (--email, --name, --role)
import getpass    # saisir un mot de passe SANS l'afficher à l'écran

from sqlalchemy import select

from app.core.security import hash_password        # transforme le mot de passe en empreinte argon2
from app.database.session import SessionLocal      # ouvre une session avec la base
from app.models import Role, User


def main() -> None:
    # --- Étape 1 : lire les options de la commande ---
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)                  # obligatoire
    parser.add_argument("--name", required=True)                   # obligatoire
    # --role n'accepte que ces 3 valeurs ; sans option, le compte le moins privilégié (viewer)
    parser.add_argument("--role", choices=["admin", "analyst", "viewer"], default="viewer")
    args = parser.parse_args()

    # --- Étape 2 : demander le mot de passe au clavier (rien n'est affiché en tapant) ---
    # Il n'est donc ni dans le code, ni dans l'historique PowerShell, ni dans Git.
    password = getpass.getpass("Mot de passe (12 caractères minimum) : ")
    if len(password) < 12:
        raise SystemExit("Mot de passe trop court.")               # SystemExit = arrêt propre avec un message
    if password != getpass.getpass("Confirmation : "):             # on redemande pour éviter une faute de frappe
        raise SystemExit("Les mots de passe diffèrent.")

    # --- Étape 3 : écrire en base ---
    with SessionLocal() as db:                                     # la session se ferme toute seule à la fin du bloc
        # Le rôle doit exister : la table roles est remplie par le seed
        role = db.scalar(select(Role).where(Role.role_name == args.role))
        if role is None:
            raise SystemExit("Rôle introuvable : lance d'abord `python -m app.database.seed`.")
        # L'e-mail est stocké en minuscules : "Admin@X.com" et "admin@x.com" = même compte
        if db.scalar(select(User).where(User.email == args.email.lower())):
            raise SystemExit("Cet e-mail existe déjà.")
        # On enregistre l'EMPREINTE du mot de passe, jamais le mot de passe lui-même
        db.add(User(email=args.email.lower(), full_name=args.name,
                    hashed_password=hash_password(password), role_id=role.role_id))
        db.commit()
    print(f"Utilisateur {args.email} créé avec le rôle {args.role}.")


# Ce bloc ne s'exécute que si on lance le fichier directement (python -m app.database.create_user),
# pas s'il est simplement importé par un autre module.
if __name__ == "__main__":
    main()