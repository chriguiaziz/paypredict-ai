"""Recommandations de recouvrement : règles métier simples, déterministes et testables."""
from __future__ import annotations


def build_recommendation(risk_level: str, days_to_due: int, amount_eur: float,
                         outstanding_ratio: float | None = None) -> dict:
    """Retourne type, texte, action suggérée et priorité.

    days_to_due < 0 signifie que la facture est déjà échue.
    """
    # Une facture est "grosse" à partir de 10 000 EUR : elle mérite un contact plus personnel
    big = amount_eur >= 10_000

    # RÈGLE 1 : facture déjà échue ET risque Medium ou High -> relance immédiate, priorité haute
    if days_to_due < 0 and risk_level != "Low":
        return {"recommendation_type": "overdue_follow_up",
                "suggested_action": "Relance ferme + appel" if big else "Relance ferme",
                "priority": "High",
                "recommendation_text": f"Facture échue depuis {-days_to_due} jours et risque {risk_level} : "
                                       "relancer immédiatement et proposer un échéancier si nécessaire."}

    # RÈGLE 2 : risque élevé, pas encore échue -> agir AVANT l'échéance
    if risk_level == "High":
        return {"recommendation_type": "early_contact",
                "suggested_action": "Appel du responsable compte" if big else "Relance préventive",
                "priority": "High",
                "recommendation_text": "Risque élevé de retard : contacter le client avant l'échéance "
                                       "et confirmer la date de paiement."}

    # RÈGLE 3 : risque moyen -> simple rappel courtois
    if risk_level == "Medium":
        return {"recommendation_type": "reminder",
                "suggested_action": "Rappel courtois avant l'échéance",
                "priority": "Medium",
                "recommendation_text": "Risque modéré : envoyer un rappel quelques jours avant l'échéance."}

    # RÈGLE 4 (par défaut) : risque faible -> rien à faire
    return {"recommendation_type": "monitor",
            "suggested_action": "Aucune action",
            "priority": "Low",
            "recommendation_text": "Risque faible : surveillance normale."}