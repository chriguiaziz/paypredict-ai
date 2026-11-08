"""Ingénierie des variables SANS fuite d'information.

Règle d'or : les variables d'une facture sont calculées à sa date d'émission P
(date de prédiction) avec uniquement ce qui était CONNU avant P.

Une facture passée n'entre dans l'historique que si son issue était connue avant P :
  - payée à temps  -> l'issue est connue à la date de règlement ;
  - en retard      -> l'issue est connue dès le lendemain de l'échéance
                      (la facture n'est pas soldée à l'échéance), même si elle
                      n'est payée que plus tard.
"""
from __future__ import annotations

import numpy as np    # calculs sur tableaux de nombres et de dates
import pandas as pd   # tableaux de données (DataFrame)

# ---------------------------------------------------------------------------
# PARTIE 1 : constantes et listes de variables
# ---------------------------------------------------------------------------

# Taux de change FIXES et SYNTHÉTIQUES (hypothèse documentée, pas de vrais taux).
# Sert à convertir tous les montants en EUR pour pouvoir les comparer.
FX_TO_EUR = {"EUR": 1.0, "USD": 0.92, "TND": 0.30}

# Factures qu'on exclut de l'apprentissage : leur issue n'a pas de sens ou n'est pas fiable.
EXCLUDED_STATUSES = ("Cancelled", "Draft", "Disputed")

# Les variables numériques que le modèle recevra (17 au total).
NUMERIC_FEATURES = [
    "invoice_amount_eur",                  # montant de la facture, en EUR
    "payment_terms_days",                  # délai de paiement accordé (15, 30 ou 60)
    "customer_age_months",                 # ancienneté du client, en mois
    "invoice_month",                       # mois d'émission (1 à 12) : saisonnalité
    "invoice_quarter",                     # trimestre d'émission (1 à 4)
    "amount_to_credit_limit_ratio",        # montant / plafond de crédit du client
    "previous_invoice_count",              # nombre de factures précédentes du client
    "previous_late_payment_count",         # nombre de retards passés (issue connue)
    "historical_late_payment_rate",        # taux de retard passé
    "recent_late_rate_last5",              # taux de retard sur les 5 dernières factures
    "average_payment_delay",               # retard moyen en jours (factures soldées)
    "median_payment_delay",                # retard médian
    "maximum_payment_delay",               # pire retard observé
    "outstanding_balance_eur",             # solde impayé du client au jour P, en EUR
    "customer_outstanding_invoice_count",  # nombre de factures encore impayées au jour P
    "days_since_last_payment",             # jours écoulés depuis son dernier paiement
    "has_history",                         # 1 si le client a au moins une issue connue, sinon 0
]
# Variables en texte (catégories) : seront encodées plus tard dans le pipeline.
CATEGORICAL_FEATURES = ["customer_industry", "customer_segment"]
# Liste complète des colonnes données au modèle (19 en tout).
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
# La colonne à prédire : 1 = facture soldée en retard, 0 = soldée à temps.
TARGET = "will_be_late"


# ---------------------------------------------------------------------------
# PARTIE 2 : préparer la table des factures (règlement, label, date de connaissance)
# ---------------------------------------------------------------------------
def prepare_invoice_table(customers: pd.DataFrame, invoices: pd.DataFrame,
                          payments: pd.DataFrame, cutoff: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ajoute à chaque facture : règlement, label, date à laquelle l'issue est connue."""
    cutoff = pd.Timestamp(cutoff)   # date de coupure T (31/12/2025)

    # --- Factures : conversion des types et des montants en EUR ---
    inv = invoices.copy()   # copie : on ne modifie jamais les données d'origine
    inv["invoice_date"] = pd.to_datetime(inv["invoice_date"])
    inv["due_date"] = pd.to_datetime(inv["due_date"])
    inv["amount"] = inv["invoice_amount"].astype(float)
    inv["amount_eur"] = inv["amount"] * inv["currency"].map(FX_TO_EUR)  # montant converti en EUR

    # --- Paiements : on ne garde que ceux au statut "Completed", en EUR ---
    pay = payments.copy()
    pay["payment_date"] = pd.to_datetime(pay["payment_date"])
    pay["amount"] = pay["payment_amount"].astype(float)
    pay = pay[pay["payment_status"] == "Completed"]
    pay = pay.merge(inv[["invoice_id", "currency"]], on="invoice_id")  # on récupère la devise
    pay["amount_eur"] = pay["amount"] * pay["currency"].map(FX_TO_EUR)

    # --- Pour chaque facture : total payé et date du dernier paiement ---
    agg = pay.groupby("invoice_id").agg(paid_total=("amount", "sum"), last_payment=("payment_date", "max"))
    inv = inv.merge(agg, on="invoice_id", how="left")   # how="left" garde les factures sans paiement
    inv["paid_total"] = inv["paid_total"].fillna(0.0)   # pas de paiement = 0 payé
    # Facture soldée si le total payé couvre le montant (0.005 = tolérance d'arrondi)
    settled = inv["paid_total"] >= inv["amount"] - 0.005
    # Date de règlement = date du dernier paiement, seulement si la facture est soldée
    inv["settle_date"] = inv["last_payment"].where(settled)
    # Retard en jours = date de règlement - échéance (négatif = payé en avance)
    inv["delay_days"] = (inv["settle_date"] - inv["due_date"]).dt.days

    # Trois situations, qui définissent l'issue de chaque facture :
    late_settled = settled & (inv["settle_date"] > inv["due_date"])   # soldée en retard
    ontime_settled = settled & ~late_settled                          # soldée à temps
    unpaid_overdue = ~settled & (inv["due_date"] < cutoff)            # non soldée, échéance dépassée

    # --- Le label (la cible) : uniquement quand l'issue est CERTAINE à la date T ---
    label = pd.Series(np.nan, index=inv.index)   # NaN = inconnu par défaut
    label[ontime_settled] = 0.0                  # à temps -> 0
    label[late_settled | unpaid_overdue] = 1.0   # en retard (ou impayée échue) -> 1
    # Fenêtre de labellisation : on n'étiquette que les factures émises avant
    # (coupure - délai maximum). Toutes les durées de paiement (15, 30, 60 jours) y sont
    # alors représentées. Sans cette règle, les factures récentes à échéance lointaine
    # (déjà payées d'avance ou pas encore échues) fausseraient le taux de retard.
    max_terms = int(inv["payment_terms_days"].max())   # 60 jours
    label[inv["invoice_date"] >= cutoff - pd.Timedelta(days=max_terms)] = np.nan
    inv[TARGET] = label

    # --- Date à laquelle l'issue devient connue (sert à ne pas utiliser le futur) ---
    known = pd.Series(pd.NaT, index=inv.index, dtype="datetime64[ns]")   # NaT = date inconnue
    known[ontime_settled] = inv.loc[ontime_settled, "settle_date"]       # à temps : au règlement
    is_late = late_settled | unpaid_overdue
    known[is_late] = inv.loc[is_late, "due_date"] + pd.Timedelta(days=1) # en retard : lendemain de l'échéance
    inv["outcome_known_date"] = known
    # Éligible = statut utilisable (hors annulées, brouillons et litiges)
    inv["eligible"] = ~inv["invoice_status"].isin(EXCLUDED_STATUSES)
    return inv, pay


# ---------------------------------------------------------------------------
# PARTIE 3 : calculer les variables pour toutes les factures d'UN client
# ---------------------------------------------------------------------------
def _customer_rows(c: pd.Series, inv: pd.DataFrame, pay: pd.DataFrame) -> list[dict]:
    """Variables pour toutes les factures éligibles d'un client (une ligne par facture)."""
    # On garde les factures éligibles du client, triées par date d'émission
    inv = inv[inv["eligible"]].sort_values("invoice_date").reset_index(drop=True)
    if inv.empty:
        return []
    # Dictionnaire : identifiant de facture -> numéro de ligne (0, 1, 2...)
    idx_of = {iid: k for k, iid in enumerate(inv["invoice_id"])}
    pay = pay[pay["invoice_id"].isin(idx_of)]   # paiements de ces factures seulement
    # Conversion en tableaux numpy : beaucoup plus rapide que pandas dans une boucle
    p_date = pay["payment_date"].to_numpy("datetime64[ns]")   # dates des paiements
    p_amt = pay["amount_eur"].to_numpy(float)                 # montants des paiements (EUR)
    p_idx = pay["invoice_id"].map(idx_of).to_numpy(int)       # facture de chaque paiement

    i_date = inv["invoice_date"].to_numpy("datetime64[ns]")        # dates d'émission
    known = inv["outcome_known_date"].to_numpy("datetime64[ns]")   # dates où l'issue est connue
    settle = inv["settle_date"].to_numpy("datetime64[ns]")         # dates de règlement
    delay = inv["delay_days"].to_numpy(float)                      # retards en jours
    late = (inv[TARGET].to_numpy(float) == 1.0)                    # True si la facture est en retard
    amt_eur = inv["amount_eur"].to_numpy(float)                    # montants en EUR
    reg = pd.Timestamp(c["registration_date"])                     # date d'inscription du client

    rows = []
    for k in range(len(inv)):   # on traite chaque facture k comme "la facture à prédire"
        P = i_date[k]           # P = date de prédiction = date d'émission de la facture k

        # --- Tout ce qui suit n'utilise QUE ce qui était connu avant P ---
        before = i_date < P                      # factures émises STRICTEMENT avant P
        kn = before & (known < P)                # issue connue avant P (NaT -> False)
        n_known = int(kn.sum())                  # nombre d'issues connues
        n_late = int((kn & late).sum())          # dont combien en retard
        st = before & (settle < P)               # soldées avant P
        d = delay[st]                            # leurs retards en jours
        pm = p_date < P                          # paiements enregistrés avant P
        # Total payé avant P pour chaque facture (somme des paiements par facture)
        paid_before = np.bincount(p_idx[pm], weights=p_amt[pm], minlength=len(inv))
        bal = amt_eur - paid_before              # solde restant de chaque facture au jour P
        open_mask = before & (bal > 0.005)       # factures précédentes encore impayées
        order = np.argsort(known[kn])            # tri des issues connues par date de connaissance
        last5 = late[kn][order][-5:]             # retards (0/1) des 5 dernières issues connues
        # Dates des paiements faits avant P sur des factures antérieures
        last_pay = p_date[pm & before[p_idx]] if pm.any() else p_date[:0]
        pdate = pd.Timestamp(P)
        credit = float(c["credit_limit"])

        # Une ligne = les 24 colonnes de la facture k
        rows.append({
            "invoice_id": inv.at[k, "invoice_id"],
            "customer_id": c["customer_id"],
            "invoice_date": pdate,
            "due_date": inv.at[k, "due_date"],
            TARGET: inv.at[k, TARGET],   # la cible (peut être NaN si censurée)
            # --- variables de la facture ---
            "invoice_amount_eur": amt_eur[k],
            "payment_terms_days": int(inv.at[k, "payment_terms_days"]),
            "customer_age_months": max((pdate - reg).days / 30.44, 0.0),   # 30,44 = jours par mois moyen
            "invoice_month": pdate.month,
            "invoice_quarter": (pdate.month - 1) // 3 + 1,
            "amount_to_credit_limit_ratio": amt_eur[k] / credit if credit > 0 else np.nan,
            # --- variables d'historique (calculées avec le passé uniquement) ---
            "previous_invoice_count": int(before.sum()),
            "previous_late_payment_count": n_late,
            "historical_late_payment_rate": n_late / n_known if n_known else np.nan,
            "recent_late_rate_last5": float(last5.mean()) if len(last5) else np.nan,
            "average_payment_delay": float(d.mean()) if len(d) else np.nan,
            "median_payment_delay": float(np.median(d)) if len(d) else np.nan,
            "maximum_payment_delay": float(d.max()) if len(d) else np.nan,
            # --- variables d'exposition ---
            "outstanding_balance_eur": float(bal[open_mask].sum()),
            "customer_outstanding_invoice_count": int(open_mask.sum()),
            "days_since_last_payment": float((P - last_pay.max()) / np.timedelta64(1, "D")) if len(last_pay) else np.nan,
            "has_history": int(n_known > 0),
            # --- variables du client (catégories) ---
            "customer_industry": c["industry"],
            "customer_segment": c["customer_segment"],
        })
    return rows


# ---------------------------------------------------------------------------
# PARTIE 4 : construire le jeu de données complet
# ---------------------------------------------------------------------------
def build_dataset(customers: pd.DataFrame, invoices: pd.DataFrame, payments: pd.DataFrame,
                  cutoff) -> pd.DataFrame:
    """Une ligne par facture éligible. TARGET = NaN pour les factures censurées."""
    inv, pay = prepare_invoice_table(customers, invoices, payments, pd.Timestamp(cutoff))
    # On range factures et paiements par client, pour traiter les clients un par un
    inv_by_c = {k: g for k, g in inv.groupby("customer_id")}
    pay_by_c = {k: g for k, g in pay.merge(inv[["invoice_id", "customer_id"]], on="invoice_id").groupby("customer_id")}
    empty_pay = pay.iloc[:0].assign(customer_id=pd.Series(dtype=object))   # table vide si aucun paiement
    rows: list[dict] = []
    for _, c in customers.iterrows():           # une itération = un client
        g = inv_by_c.get(c["customer_id"])
        if g is None:                           # client sans facture : on passe
            continue
        rows.extend(_customer_rows(c, g, pay_by_c.get(c["customer_id"], empty_pay)))
    # Tableau final trié par date d'émission : indispensable pour un découpage chronologique
    return pd.DataFrame(rows).sort_values("invoice_date").reset_index(drop=True)