"""Contrôles de qualité des données synthétiques (CSV ou base PostgreSQL).

Idée : ne jamais faire confiance à des données sans les avoir testées.
Chaque contrôle répond par OK ou ÉCHEC. Si un contrôle échoue, on corrige le
générateur, jamais le contrôle.
"""
from __future__ import annotations

import argparse   # lire les options de la ligne de commande (--source, --folder)
import sys        # sys.exit() pour renvoyer un code de sortie (0 = tout va bien)
from pathlib import Path   # manipuler les chemins de fichiers

import pandas as pd   # manipuler les tableaux de données

# On réutilise les réglages du générateur pour que les contrôles restent
# synchronisés avec lui : CUTOFF = date de coupure T, et les volumes attendus.
from ml.data_generator import CUTOFF, N_CUSTOMERS, N_INVOICES


def run_checks(customers: pd.DataFrame, invoices: pd.DataFrame, payments: pd.DataFrame,
               truth: pd.DataFrame | None = None) -> list[tuple[str, bool, str]]:
    """Exécute tous les contrôles et renvoie une liste de (nom, réussi ?, détail).

    `truth` est la vérité terrain (profils cachés). Elle vaut None quand on
    contrôle la base de données, car le profil n'y est volontairement pas stocké.
    """
    res: list[tuple[str, bool, str]] = []   # liste des résultats, remplie par check()

    def check(name: str, ok: bool, detail: str = "") -> None:
        """Enregistre un résultat. bool(ok) convertit le résultat pandas en vrai/faux."""
        res.append((name, bool(ok), detail))

    # --- Préparation : copies de travail, pour ne jamais modifier les originaux ---
    inv = invoices.copy()
    pay = payments.copy()
    # Les montants arrivent en texte ("123.45") : on les convertit en nombres.
    inv["amount"] = inv["invoice_amount"].astype(float)
    pay["amount"] = pay["payment_amount"].astype(float)
    # Les dates arrivent en texte : on les convertit en vraies dates pour pouvoir
    # les comparer et calculer des écarts en jours.
    inv["invoice_date"] = pd.to_datetime(inv["invoice_date"])
    inv["due_date"] = pd.to_datetime(inv["due_date"])
    pay["payment_date"] = pd.to_datetime(pay["payment_date"])

    # --- 1. Volumes attendus ---
    check("volume clients", len(customers) == N_CUSTOMERS, f"{len(customers)}")
    check("volume factures", len(inv) == N_INVOICES, f"{len(inv)}")
    # Pour les paiements on accepte une fourchette : le nombre exact dépend du hasard
    # (versements multiples, litiges, paiements après T non enregistrés).
    check("volume paiements entre 15 000 et 20 000", 15_000 <= len(pay) <= 20_000, f"{len(pay)}")

    # --- 2. Unicité : aucun doublon d'identifiant ---
    check("identifiants clients uniques", customers["customer_id"].is_unique)
    check("numéros de facture uniques", inv["invoice_number"].is_unique)

    # --- 3. Clés étrangères : chaque facture a un client, chaque paiement a une facture ---
    # isin() teste si chaque valeur existe dans l'autre table ; all() exige que ce soit vrai partout.
    check("clé étrangère factures -> clients",
          inv["customer_id"].isin(customers["customer_id"]).all())
    check("clé étrangère paiements -> factures",
          pay["invoice_id"].isin(inv["invoice_id"]).all())

    # --- 4. Cohérence des dates et des montants ---
    # échéance - date de facture, en jours, doit être égal au délai de paiement du client
    check("échéance = date facture + délai",
          ((inv["due_date"] - inv["invoice_date"]).dt.days == inv["payment_terms_days"]).all())
    check("montants factures > 0", (inv["amount"] > 0).all())
    check("montants paiements > 0", (pay["amount"] > 0).all())
    check("devises valides", inv["currency"].isin(["EUR", "USD", "TND"]).all())

    # --- 5. Aucun surpaiement ---
    # On additionne les paiements de chaque facture (groupby + sum)...
    paid = pay.groupby("invoice_id")["amount"].sum().rename("paid")
    # ...puis on les rattache aux factures. how="left" garde aussi les factures sans
    # paiement ; fillna(0) leur met un total payé de 0.
    m = inv.merge(paid, on="invoice_id", how="left").fillna({"paid": 0.0})
    # 1e-6 est une toute petite marge qui évite les faux échecs dus aux arrondis.
    check("aucun surpaiement (somme paiements <= montant)",
          (m["paid"] <= m["amount"] + 1e-6).all(),
          f"{(m['paid'] > m['amount'] + 1e-6).sum()} violations")  # nombre de factures fautives

    # --- 6. Cohérence temporelle des paiements ---
    # On rattache à chaque paiement la date de sa facture.
    mp = pay.merge(inv[["invoice_id", "invoice_date"]], on="invoice_id")
    check("aucun paiement avant la date de facture",
          (mp["payment_date"] >= mp["invoice_date"]).all())
    # Aucun paiement après T : sinon on utiliserait des informations du futur.
    check("aucun paiement après la date de coupure T",
          (pay["payment_date"] <= pd.Timestamp(CUTOFF)).all())

    # --- 7. Cohérence entre statut et paiements ---
    st = m["invoice_status"]   # raccourci : la colonne des statuts
    # "Paid" : le total payé doit égaler le montant (écart < 1e-6)
    check("statut Paid => soldé",
          (abs(m.loc[st == "Paid", "paid"] - m.loc[st == "Paid", "amount"]) < 1e-6).all())
    # "Partially Paid" : payé strictement entre 0 et le montant
    check("statut Partially Paid => 0 < payé < montant",
          ((m.loc[st == "Partially Paid", "paid"] > 0)
           & (m.loc[st == "Partially Paid", "paid"] < m.loc[st == "Partially Paid", "amount"])).all())
    # "Cancelled" : aucun paiement
    check("statut Cancelled => aucun paiement", (m.loc[st == "Cancelled", "paid"] == 0).all())

    # --- 8. Plausibilité des profils (seulement si on a la vérité terrain) ---
    if truth is not None:
        # Date du dernier paiement de chaque facture
        last = pay.groupby("invoice_id")["payment_date"].max().rename("settle")
        x = m.merge(last, on="invoice_id", how="left")
        # On ne garde que les factures soldées (on connaît leur vrai retard), puis on
        # rattache le profil caché de chaque client.
        x = x[x["invoice_status"] == "Paid"].merge(
            customers[["customer_id"]].merge(truth[["customer_id", "archetype"]]),
            on="customer_id")
        # late = 1 si payée après l'échéance, 0 sinon
        x["late"] = (x["settle"] > x["due_date"]).astype(int)
        # Taux de retard moyen par profil (la moyenne de 0 et de 1 = la proportion de retards)
        rate = x.groupby("archetype")["late"].mean()
        check("fiables : taux de retard < 15 %", rate["reliable"] < 0.15, f"{rate['reliable']:.1%}")
        check("chroniques : taux de retard > 60 %", rate["chronic"] > 0.60, f"{rate['chronic']:.1%}")
        check("ordre des taux : fiables < occasionnels < chroniques",
              rate["reliable"] < rate["occasional"] < rate["chronic"])
    return res


def _load_csv(folder: Path) -> tuple[pd.DataFrame, ...]:
    """Lit les 4 CSV générés (clients, factures, paiements, vérité terrain)."""
    return (pd.read_csv(folder / "customers.csv"), pd.read_csv(folder / "invoices.csv"),
            pd.read_csv(folder / "payments.csv"), pd.read_csv(folder / "ground_truth.csv"))


def _load_db() -> tuple[pd.DataFrame, ...]:
    """Lit les 3 tables dans PostgreSQL. Pas de vérité terrain : elle n'est pas en base."""
    # Import ici et non en haut du fichier : le mode CSV ne doit pas exiger une base.
    from app.database.session import engine
    return (pd.read_sql_table("customers", engine), pd.read_sql_table("invoices", engine),
            pd.read_sql_table("payments", engine), None)


def main() -> int:
    # Options : --source csv|db (d'où lire) et --folder (dossier des CSV)
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["csv", "db"], default="csv")
    parser.add_argument("--folder", default="../database/seed")
    args = parser.parse_args()
    # Charge les données depuis le CSV ou depuis la base selon l'option choisie
    customers, invoices, payments, truth = (
        _load_csv(Path(args.folder)) if args.source == "csv" else _load_db())
    results = run_checks(customers, invoices, payments, truth)
    # Affiche une ligne par contrôle : [OK] ou [ÉCHEC], avec le détail s'il y en a un
    for name, ok, detail in results:
        print(f"[{'OK' if ok else 'ÉCHEC'}] {name} {('(' + detail + ')') if detail else ''}")
    failed = [r for r in results if not r[1]]   # les contrôles ratés
    print(f"\n{len(results) - len(failed)}/{len(results)} contrôles réussis")
    return 1 if failed else 0   # code de sortie : 1 = au moins un échec, 0 = tout est bon


if __name__ == "__main__":
    sys.exit(main())