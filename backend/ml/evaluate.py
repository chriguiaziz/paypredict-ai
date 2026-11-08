"""Métriques d'évaluation, choix du seuil métier et graphiques."""
from __future__ import annotations

from pathlib import Path   # manipuler les chemins de dossiers

import numpy as np
from sklearn.calibration import calibration_curve   # points de la courbe de calibration
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
                             confusion_matrix, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score, roc_curve)


# ---------------------------------------------------------------------------
# PARTIE 1 : calculer toutes les métriques
# ---------------------------------------------------------------------------
def compute_metrics(y_true, proba, threshold: float = 0.5) -> dict:
    # y_true = vraies réponses (0 ou 1) ; proba = probabilités de retard prédites (0 à 1)
    y_true = np.asarray(y_true).astype(int)
    # Décision : on déclare "en retard" (1) si la probabilité dépasse le seuil
    pred = (np.asarray(proba) >= threshold).astype(int)
    # Matrice de confusion : tn, fp, fn, tp (voir la légende plus bas)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "threshold": float(threshold),                            # seuil utilisé
        "accuracy": float(accuracy_score(y_true, pred)),          # part de bonnes réponses
        "precision": float(precision_score(y_true, pred, zero_division=0)),  # alertes justifiées
        "recall": float(recall_score(y_true, pred, zero_division=0)),        # retards détectés
        "f1": float(f1_score(y_true, pred, zero_division=0)),     # compromis précision / rappel
        "roc_auc": float(roc_auc_score(y_true, proba)),           # capacité à classer retards avant non-retards
        "pr_auc": float(average_precision_score(y_true, proba)),  # idem, centrée sur la classe rare
        "brier": float(brier_score_loss(y_true, proba)),          # qualité des probabilités (bas = mieux)
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
        "base_rate": float(y_true.mean()),                        # taux de retard réel (≈ 32 %)
    }
    # tn = vrai négatif : à temps et prédit à temps
    # fp = faux positif : à temps mais prédit en retard (relance inutile)
    # fn = faux négatif : en retard mais prédit à temps (retard non anticipé)
    # tp = vrai positif : en retard et prédit en retard


# ---------------------------------------------------------------------------
# PARTIE 2 : choisir le seuil d'alerte selon le coût métier
# ---------------------------------------------------------------------------
def best_threshold_by_cost(y_true, proba, cost_fp: float = 1.0, cost_fn: float = 5.0) -> float:
    """Seuil qui minimise le coût total (faux positif = relance inutile ; faux négatif = retard non anticipé)."""
    y_true = np.asarray(y_true).astype(int)
    best_t, best_cost = 0.5, float("inf")   # meilleur seuil trouvé, coût associé (infini au départ)
    for t in np.linspace(0.05, 0.95, 91):   # on essaie 91 seuils : 0.05, 0.06, ... 0.95
        pred = proba >= t                   # décisions avec ce seuil
        fp = int(((pred == 1) & (y_true == 0)).sum())   # relances inutiles
        fn = int(((pred == 0) & (y_true == 1)).sum())   # retards manqués
        cost = cost_fp * fp + cost_fn * fn  # un faux négatif coûte 5 fois plus qu'un faux positif
        if cost < best_cost:                # on garde le seuil le moins coûteux
            best_t, best_cost = float(t), cost
    return best_t


# ---------------------------------------------------------------------------
# PARTIE 3 : enregistrer les graphiques (ROC, précision-rappel, calibration)
# ---------------------------------------------------------------------------
def save_plots(y_true, proba_by_model: dict, out_dir: Path) -> None:
    """ROC, précision-rappel et calibration pour chaque modèle (PNG)."""
    import matplotlib
    matplotlib.use("Agg")                 # mode sans fenêtre : on écrit seulement des fichiers PNG
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)   # crée le dossier de sortie s'il n'existe pas
    y = np.asarray(y_true).astype(int)

    # --- Graphique 1 : courbe ROC ---
    fig, ax = plt.subplots(figsize=(5, 4))
    for name, p in proba_by_model.items():       # une courbe par modèle
        fpr, tpr, _ = roc_curve(y, p)            # taux de faux positifs et de vrais positifs
        ax.plot(fpr, tpr, label=name)
    ax.plot([0, 1], [0, 1], "k--", lw=1)         # diagonale = modèle qui devine au hasard
    ax.set(xlabel="Taux de faux positifs", ylabel="Rappel", title="Courbe ROC")
    ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "roc.png", dpi=150); plt.close(fig)

    # --- Graphique 2 : courbe précision-rappel ---
    fig, ax = plt.subplots(figsize=(5, 4))
    for name, p in proba_by_model.items():
        prec, rec, _ = precision_recall_curve(y, p)
        ax.plot(rec, prec, label=name)
    ax.axhline(y.mean(), color="k", ls="--", lw=1, label="taux de base")   # niveau d'un modèle au hasard
    ax.set(xlabel="Rappel", ylabel="Précision", title="Courbe précision-rappel")
    ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "precision_recall.png", dpi=150); plt.close(fig)

    # --- Graphique 3 : courbe de calibration ---
    fig, ax = plt.subplots(figsize=(5, 4))
    for name, p in proba_by_model.items():
        # 10 groupes de taille égale : fréquence réelle de retard vs probabilité moyenne prédite
        frac_pos, mean_pred = calibration_curve(y, p, n_bins=10, strategy="quantile")
        ax.plot(mean_pred, frac_pos, marker="o", label=name)
    ax.plot([0, 1], [0, 1], "k--", lw=1)         # diagonale = probabilités parfaitement calibrées
    ax.set(xlabel="Probabilité prédite", ylabel="Fréquence observée", title="Courbe de calibration")
    ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "calibration.png", dpi=150); plt.close(fig)