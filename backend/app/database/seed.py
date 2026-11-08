"""Charge les CSV synthétiques dans PostgreSQL (COPY) et crée les données de référence.

Usage (depuis backend/) :
    python -m app.database.seed            # refuse de s'exécuter si des clients existent
    python -m app.database.seed --reset    # vide customers/invoices/payments avant de charger
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.database.session import engine

SEED_DIR = Path(__file__).resolve().parents[3] / "database" / "seed"
TABLES = ["customers", "invoices", "payments"]  # ordre imposé par les clés étrangères

ROLES = {
    # Rôles RBAC (hiérarchie viewer < analyst < admin, voir app/deps.py). Correspondance avec la spécification :
    # administrator -> admin | financial_manager, accountant -> analyst | sales_manager -> viewer
    "admin": "Gère utilisateurs, paramètres et automatisations",
    "analyst": "Gère factures, paiements, prédictions et approbations de relances",
    "viewer": "Consulte les tableaux de bord et les factures (lecture seule)",
}
DEFAULT_SETTINGS = {
    "risk_thresholds": {"medium_min": 0.30, "high_min": 0.70},
    # Date de référence du "aujourd'hui" métier. Les données synthétiques s'arrêtent à T.
    "reference_date": {"date": "2025-12-31"},
}


def copy_csv(raw_conn, table: str, path: Path) -> None:
    columns = pd.read_csv(path, nrows=0).columns.tolist()
    sql = f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, HEADER true)"
    with raw_conn.cursor() as cur, cur.copy(sql) as copy, open(path, "rb") as fh:
        while chunk := fh.read(1_048_576):
            copy.write(chunk)


def seed_reference(conn) -> None:
    for name, description in ROLES.items():
        conn.execute(text(
            "INSERT INTO roles (role_id, role_name, description) "
            "VALUES (gen_random_uuid(), :n, :d) ON CONFLICT (role_name) DO NOTHING"),
            {"n": name, "d": description})
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(text(
            "INSERT INTO app_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO NOTHING"), {"k": key, "v": json.dumps(value)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--folder", type=Path, default=SEED_DIR)
    args = parser.parse_args()

    with engine.begin() as conn:
        if args.reset:
            conn.execute(text("TRUNCATE payments, invoices, customers CASCADE"))
        existing = conn.execute(text("SELECT count(*) FROM customers")).scalar_one()
        if existing:
            raise SystemExit("customers n'est pas vide : relance avec --reset pour recharger.")
        raw = conn.connection.dbapi_connection
        for table in TABLES:
            copy_csv(raw, table, args.folder / f"{table}.csv")
            n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            print(f"{table:10s} {n:>7,d} lignes chargées")
        seed_reference(conn)
        print("rôles et paramètres par défaut créés")


if __name__ == "__main__":
    main()