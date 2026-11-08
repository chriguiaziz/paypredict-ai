"""Explicabilité SHAP : pourquoi une facture reçoit-elle ce score ?

Attention : SHAP décrit comment le MODÈLE utilise les variables (attribution), pas
la cause réelle du retard (corrélation, pas causalité).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import shap                                           # bibliothèque d'explicabilité
from sklearn.linear_model import LogisticRegression

from ml.feature_engineering import FEATURE_COLUMNS

# ---------------------------------------------------------------------------
# PARTIE 1 : noms lisibles pour l'affichage (remplacent les noms techniques)
# ---------------------------------------------------------------------------
FEATURE_LABELS = {
    "invoice_amount_eur": "Montant de la facture (EUR)",
    "payment_terms_days": "Délai de paiement (jours)",
    "customer_age_months": "Ancienneté du client (mois)",
    "invoice_month": "Mois d'émission",
    "invoice_quarter": "Trimestre d'émission",
    "amount_to_credit_limit_ratio": "Montant / plafond de crédit",
    "previous_invoice_count": "Nombre de factures précédentes",
    "previous_late_payment_count": "Nombre de retards passés",
    "historical_late_payment_rate": "Taux historique de retard",
    "recent_late_rate_last5": "Taux de retard sur les 5 dernières factures",
    "average_payment_delay": "Retard moyen de paiement (jours)",
    "median_payment_delay": "Retard médian de paiement (jours)",
    "maximum_payment_delay": "Retard maximal de paiement (jours)",
    "outstanding_balance_eur": "Solde impayé du client (EUR)",
    "customer_outstanding_invoice_count": "Factures impayées du client",
    "days_since_last_payment": "Jours depuis le dernier paiement",
    "has_history": "Le client a un historique",
    "customer_industry": "Secteur d'activité",
    "customer_segment": "Segment client",
}


def _clean_name(raw: str) -> str:
    # Après le pré-traitement, les colonnes s'appellent par ex. "num__has_history"
    # ou "cat__customer_segment_SME". On enlève le préfixe "num__" ou "cat__".
    name = raw.split("__", 1)[-1]
    # Pour les catégories encodées en one-hot, on écrit "Libellé = valeur"
    for cat in ("customer_industry", "customer_segment"):
        if name.startswith(cat + "_"):
            return f"{FEATURE_LABELS[cat]} = {name[len(cat) + 1:]}"
    # Sinon, on prend le libellé lisible (ou le nom brut s'il n'existe pas)
    return FEATURE_LABELS.get(name, name)


# ---------------------------------------------------------------------------
# PARTIE 2 : la classe qui explique les scores
# ---------------------------------------------------------------------------
class RiskExplainer:
    def __init__(self, base_pipeline, background: pd.DataFrame, max_background: int = 200):
        # On sépare les deux étapes du pipeline : pré-traitement et modèle
        self.pre = base_pipeline.named_steps["preprocess"]
        self.clf = base_pipeline.named_steps["model"]
        # Noms lisibles de toutes les colonnes après pré-traitement
        self.names = [_clean_name(n) for n in self.pre.get_feature_names_out()]
        # Échantillon de référence ("fond") : les 200 premières lignes, transformées
        bg = self.pre.transform(background[FEATURE_COLUMNS].head(max_background))
        # Choix de l'explicateur selon le type de modèle
        if isinstance(self.clf, LogisticRegression):
            self.explainer = shap.LinearExplainer(self.clf, bg)   # rapide, pour les modèles linéaires
        else:
            self.explainer = shap.TreeExplainer(self.clf)         # rapide, pour forêts et XGBoost

    def _values(self, X: np.ndarray) -> np.ndarray:
        # Calcule les valeurs SHAP : une contribution par variable et par facture
        sv = self.explainer.shap_values(X)
        if isinstance(sv, list):          # anciennes versions de shap : une matrice par classe
            sv = sv[1]                    # on garde la classe 1 (= "en retard")
        sv = np.asarray(sv)
        if sv.ndim == 3:                  # (n, variables, classes)
            sv = sv[:, :, 1]              # là aussi, la classe 1
        return sv

    def explain(self, rows: pd.DataFrame, top_k: int = 5) -> list[list[dict]]:
        """Pour chaque facture : les top_k variables qui pèsent le plus sur son score."""
        X = self.pre.transform(rows[FEATURE_COLUMNS])
        sv = self._values(X)
        out = []
        for i in range(len(rows)):                           # une facture à la fois
            order = np.argsort(-np.abs(sv[i]))[:top_k]       # les plus fortes contributions (en valeur absolue)
            out.append([{"feature": self.names[j],           # nom lisible de la variable
                         "contribution": float(sv[i, j]),    # sa contribution au score
                         "direction": "augmente le risque" if sv[i, j] > 0 else "réduit le risque"}
                        for j in order])
        return out

    def global_importance(self, rows: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
        """Importance globale : contribution absolue moyenne de chaque variable sur un ensemble de factures."""
        sv = self._values(self.pre.transform(rows[FEATURE_COLUMNS]))
        imp = pd.Series(np.abs(sv).mean(axis=0), index=self.names).sort_values(ascending=False)
        return imp.head(top_k).rename("importance_moyenne_absolue").to_frame()