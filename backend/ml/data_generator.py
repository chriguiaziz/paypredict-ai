"""Générateur de données synthétiques PayPredict AI.

Reproductible (graine fixe). Les montants sont calculés en centimes entiers
pour que la somme des paiements ne dépasse jamais le montant de la facture.
Les archétypes (vérité terrain) sont écrits dans un fichier séparé et ne sont
JAMAIS chargés en base ni utilisés comme variable explicative.
"""
from __future__ import annotations  # permet des annotations de types modernes

# ---------------------------------------------------------------------------
# ÉTAPE 1 : les imports
# ---------------------------------------------------------------------------
import argparse   # lire les options de la ligne de commande (--out, --seed)
import hashlib    # calculer l'empreinte (hash) du jeu de données
import uuid       # fabriquer des identifiants uniques
from dataclasses import dataclass       # petites "fiches" de données
from datetime import date, timedelta    # dates et durées
from pathlib import Path                # manipuler les chemins de fichiers

import numpy as np    # tirages aléatoires et calculs mathématiques
import pandas as pd   # tableaux (DataFrame) et export CSV

# ---------------------------------------------------------------------------
# ÉTAPE 2 : les constantes (les réglages du générateur)
# ---------------------------------------------------------------------------
SEED = 42                          # graine du hasard : même graine = mêmes données
N_CUSTOMERS = 1_000                # nombre de clients à créer
N_INVOICES = 20_000                # nombre total de factures
WINDOW_START = date(2023, 1, 1)    # début de la période des factures
LAST_INVOICE_DATE = date(2025, 12, 15)  # dernière date d'émission possible
CUTOFF = date(2025, 12, 31)        # date de coupure T : on observe la base ce jour-là
DATASET_VERSION = "synthetic-v1"   # version du jeu de données

# Valeurs possibles, tirées au sort pour chaque client ou facture
INDUSTRIES = ["Retail", "Manufacturing", "Construction", "Healthcare",
              "Technology", "Logistics", "Hospitality", "Education", "Energy"]
COUNTRIES = ["France", "Germany", "Tunisia", "Morocco", "Spain", "Italy", "UAE"]
SEGMENTS = ["SME", "Mid-Market", "Enterprise"]
CURRENCIES = ["EUR", "USD", "TND"]
PAYMENT_METHODS = ["Bank Transfer", "Card", "Direct Debit", "Cheque"]


# ---------------------------------------------------------------------------
# ÉTAPE 3 : les 5 profils de clients ("archétypes")
# ---------------------------------------------------------------------------
@dataclass(frozen=True)  # frozen = une fois créée, la fiche ne peut plus être modifiée
class Archetype:
    name: str              # nom du profil
    share: float           # part des clients ayant ce profil (0.40 = 40 %)
    base_logit: float      # propension au retard (échelle log-odds : plus haut = plus de retards)
    late_mean_days: float  # nombre moyen de jours de retard quand la facture est en retard
    amount_scale: float    # multiplicateur appliqué aux montants (4.0 = factures 4x plus grosses)


ARCHETYPES = [
    #          nom            part  logit  retard  montants
    Archetype("reliable",     0.40, -2.6,   4.0,   1.0),  # fiable : rarement en retard
    Archetype("occasional",   0.28, -0.4,   9.0,   1.0),  # occasionnel : parfois en retard
    Archetype("chronic",      0.12,  1.8,  24.0,   0.9),  # chronique : très souvent en retard
    Archetype("high_value",   0.10, -0.9,  12.0,   4.0),  # grand compte : grosses factures
    Archetype("new",          0.10, -0.2,  10.0,   0.8),  # nouveau client : peu d'historique
]


# ---------------------------------------------------------------------------
# ÉTAPE 4 : petites fonctions utilitaires
# ---------------------------------------------------------------------------
def _uuid(rng: np.random.Generator) -> str:
    """Identifiant unique, mais tiré du générateur seedé pour rester reproductible."""
    return str(uuid.UUID(bytes=rng.bytes(16), version=4))


def _cents(x: float) -> int:
    """Convertit un montant en centimes entiers : 12.34 -> 1234."""
    return int(round(x * 100))


def _fmt(cents: int) -> str:
    """Convertit des centimes en texte à 2 décimales : 1234 -> '12.34'."""
    return f"{cents // 100}.{cents % 100:02d}"


# ---------------------------------------------------------------------------
# ÉTAPE 5 : création des clients
# ---------------------------------------------------------------------------
def generate_customers(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (table des clients, table de vérité terrain cachée)."""
    shares = [a.share for a in ARCHETYPES]
    # On attribue un profil à chacun des 1000 clients d'un seul coup,
    # selon les parts (40 % fiable, 28 % occasionnel...).
    idx = rng.choice(len(ARCHETYPES), size=N_CUSTOMERS, p=shares)

    rows, truth = [], []   # rows = table customers ; truth = secrets de chaque client
    for i in range(N_CUSTOMERS):
        a = ARCHETYPES[idx[i]]   # le profil du client numéro i

        # Date d'inscription : un "new" s'inscrit en 2025, les autres entre 2019 et ~2023
        if a.name == "new":
            reg = date(2025, 3, 1) + timedelta(days=int(rng.integers(0, 200)))
        else:
            reg = date(2019, 1, 1) + timedelta(days=int(rng.integers(0, 1500)))

        # Segment : un grand compte est toujours "Enterprise", sinon tirage pondéré
        segment = "Enterprise" if a.name == "high_value" else str(
            rng.choice(SEGMENTS, p=[0.55, 0.35, 0.10]))

        # Délai de paiement accordé : 15, 30 ou 60 jours
        terms = int(rng.choice([15, 30, 60], p=[0.20, 0.55, 0.25]))

        # Limite de crédit : loi lognormale (beaucoup de petites valeurs, quelques très grandes)
        credit = _cents(float(rng.lognormal(10.2, 0.6)) * a.amount_scale)

        cid = _uuid(rng)   # identifiant unique du client

        # Ligne de la table "customers" (ce que l'on charge en base)
        rows.append({
            "customer_id": cid,
            "customer_code": f"CUST-{i + 1:05d}",            # ex. CUST-00001
            "company_name": f"Synthetic Company {i + 1:04d}",
            "industry": str(rng.choice(INDUSTRIES)),
            "country": str(rng.choice(COUNTRIES)),
            "customer_segment": segment,
            "registration_date": reg.isoformat(),
            "payment_terms_days": terms,
            "credit_limit": _fmt(credit),
            "customer_status": "Active",
        })

        # Vérité terrain : changement de comportement pour 15 % des clients (sauf "new").
        # À partir de drift_date, le client devient plus mauvais ou meilleur payeur.
        drift_date = (WINDOW_START + timedelta(days=int(rng.integers(300, 900)))).isoformat() \
            if rng.random() < 0.15 and a.name != "new" else ""
        drift_dir = float(rng.choice([-1.0, 1.0])) if drift_date else 0.0  # -1 mieux, +1 pire

        # Ligne de la table cachée : JAMAIS donnée au modèle
        truth.append({
            "customer_id": cid,
            "archetype": a.name,
            "currency": str(rng.choice(CURRENCIES, p=[0.60, 0.25, 0.15])),
            "drift_date": drift_date,
            "drift_direction": drift_dir,
            "customer_noise": float(rng.normal(0, 0.4)),  # personnalité propre au client
        })
    return pd.DataFrame(rows), pd.DataFrame(truth)


# ---------------------------------------------------------------------------
# ÉTAPE 6 : création des factures et des paiements (le cœur du script)
# ---------------------------------------------------------------------------
def generate_invoices_and_payments(
    rng: np.random.Generator, customers: pd.DataFrame, truth: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # On rassemble clients + vérité terrain dans un seul tableau
    cust = customers.merge(truth, on="customer_id").reset_index(drop=True)
    arche = {a.name: a for a in ARCHETYPES}   # accès rapide à un profil par son nom

    # 6a. Combien de factures par client ? Moins pour "new", plus pour "high_value".
    weights = np.array([
        0.4 if r.archetype == "new" else (1.5 if r.archetype == "high_value" else 1.0)
        for r in cust.itertuples()
    ])
    # On répartit exactement 20 000 factures selon ces poids
    counts = rng.multinomial(N_INVOICES, weights / weights.sum())

    invoices, payments = [], []   # listes de lignes pour les tables invoices et payments
    inv_seq = 0                   # compteur pour numéroter les factures

    for r, n in zip(cust.itertuples(), counts):   # r = un client, n = son nb de factures
        a = arche[r.archetype]
        reg = date.fromisoformat(r.registration_date)
        start = max(WINDOW_START, reg)            # pas de facture avant l'inscription
        span = (LAST_INVOICE_DATE - start).days   # nombre de jours disponibles
        if span <= 0:
            continue

        # 6b. Dates d'émission : n jours tirés au hasard dans la période, puis triés
        offsets = np.sort(rng.integers(0, span + 1, size=int(n)))
        drift = date.fromisoformat(r.drift_date) if r.drift_date else None
        terms = int(r.payment_terms_days)

        for off in offsets:   # une itération = une facture
            inv_date = start + timedelta(days=int(off))
            inv_seq += 1

            # 6c. Montant (lognormal x échelle du profil), minimum 50.00
            amount_c = _cents(float(rng.lognormal(7.6, 0.9)) * a.amount_scale)
            amount_c = max(amount_c, 5_000)
            due = inv_date + timedelta(days=terms)   # date d'échéance

            # 6d. Probabilité de retard : on additionne des facteurs dans un "logit"
            logit = a.base_logit + r.customer_noise                       # profil + personnalité
            logit += 0.25 * np.log(max(amount_c / 100, 1) / 2000)         # gros montants : plus de retards
            logit += {15: 0.3, 30: 0.0, 60: -0.25}[terms]                 # échéance courte : plus de retards
            logit += {10: 0.15, 11: 0.2, 12: 0.45}.get(inv_date.month, 0.0)  # oct-déc : plus de retards
            if drift and inv_date >= drift:
                logit += 1.2 * r.drift_direction                          # changement de comportement
            p_late = 1.0 / (1.0 + np.exp(-logit))   # logit -> probabilité entre 0 et 1
            is_late = rng.random() < p_late         # tirage au sort : retard ou non

            # 6e. Date réelle de paiement
            if is_late:
                delay = 1 + int(rng.gamma(2.0, a.late_mean_days / 2.0))   # retard d'au moins 1 jour
            else:
                delay = -int(rng.integers(0, max(2, terms // 2)))         # payé en avance ou à l'heure
            settle_date = due + timedelta(days=delay)
            settle_date = max(settle_date, inv_date + timedelta(days=1))  # jamais avant la facture

            # 6f. Statut de la facture : 2 % annulée, 3 % en litige, sinon émise
            u = rng.random()
            status = "Issued"
            if u < 0.02:
                status = "Cancelled"
            elif u < 0.05:
                status = "Disputed"

            inv_id = _uuid(rng)
            invoices.append({
                "invoice_id": inv_id,
                "invoice_number": f"INV-{inv_date.year}-{inv_seq:06d}",
                "customer_id": r.customer_id,
                "invoice_date": inv_date.isoformat(),
                "due_date": due.isoformat(),
                "invoice_amount": _fmt(amount_c),
                "currency": r.currency,
                "payment_terms_days": terms,
                "invoice_status": status,
                "description": f"Services {inv_date.strftime('%B %Y')}",
            })

            if status == "Cancelled":
                continue   # une facture annulée n'a aucun paiement

            # Les litiges sont rarement payés (30 %) et seulement partiellement, plus tard
            if status == "Disputed":
                if rng.random() < 0.7:
                    continue
                settle_date += timedelta(days=int(rng.integers(20, 60)))

            # 6g. Paiements : 1 versement (94 %) ou 2 versements (6 %, si montant >= 200.00)
            pay_list: list[tuple[date, int]] = []
            if rng.random() < 0.06 and amount_c >= 20_000:
                first_c = int(amount_c * rng.uniform(0.3, 0.7))   # 1er versement : 30 à 70 %
                first_date = inv_date + timedelta(
                    days=int(rng.integers(1, max(2, (settle_date - inv_date).days))))
                pay_list = [(first_date, first_c), (settle_date, amount_c - first_c)]
            else:
                pay_list = [(settle_date, amount_c)]
            if status == "Disputed":   # litige : on ne paie que la moitié
                pay_list = [(pay_list[0][0], int(pay_list[0][1] * 0.5))]

            total_c = 0   # total payé avant la date de coupure
            for pdate, pc in pay_list:
                if pdate > CUTOFF:   # paiement après T : futur non observé, on l'ignore
                    continue
                total_c += pc
                payments.append({
                    "payment_id": _uuid(rng),
                    "invoice_id": inv_id,
                    "payment_date": pdate.isoformat(),
                    "payment_amount": _fmt(pc),
                    "payment_method": str(rng.choice(PAYMENT_METHODS)),
                    "transaction_reference": f"TX-{rng.integers(10**9, 10**10)}",
                    "payment_status": "Completed",
                })

            # 6h. Mise à jour du statut selon ce qui a réellement été payé
            if status == "Issued":
                if total_c >= amount_c:
                    invoices[-1]["invoice_status"] = "Paid"
                elif total_c > 0:
                    invoices[-1]["invoice_status"] = "Partially Paid"
                # sinon reste "Issued" ; "Overdue" n'est jamais écrit (la vue SQL le calcule)
    return pd.DataFrame(invoices), pd.DataFrame(payments)


# ---------------------------------------------------------------------------
# ÉTAPE 7 : assemblage, empreinte et exécution
# ---------------------------------------------------------------------------
def generate_all(seed: int = SEED) -> dict[str, pd.DataFrame]:
    """Génère les 4 tables à partir d'une graine."""
    rng = np.random.default_rng(seed)   # le générateur aléatoire seedé, partagé partout
    customers, truth = generate_customers(rng)
    invoices, payments = generate_invoices_and_payments(rng, customers, truth)
    return {"customers": customers, "invoices": invoices,
            "payments": payments, "ground_truth": truth}


def dataset_hash(frames: dict[str, pd.DataFrame]) -> str:
    """Empreinte SHA-256 de tous les CSV : même hash = mêmes données."""
    h = hashlib.sha256()
    for name in sorted(frames):   # ordre fixe pour un hash stable
        h.update(name.encode())
        h.update(frames[name].to_csv(index=False).encode())
    return h.hexdigest()


def main() -> None:
    # Options de la ligne de commande : --out (dossier) et --seed (graine)
    parser = argparse.ArgumentParser(description="Génère les données synthétiques")
    parser.add_argument("--out", default="database/seed", help="dossier de sortie")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    frames = generate_all(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)   # crée le dossier s'il n'existe pas
    for name, df in frames.items():
        df.to_csv(out / f"{name}.csv", index=False)   # un CSV par table
        print(f"{name:13s} {len(df):>7,d} lignes")
    print(f"hash du jeu de données : {dataset_hash(frames)[:16]}")


if __name__ == "__main__":   # exécuté seulement si on lance le fichier directement
    main()