"""Entraînement : 3 modèles comparés sur un découpage chronologique, calibration, sauvegarde.

Usage (depuis backend/) :
    python -m ml.train --source csv --folder ../database/seed --activate
"""
from __future__ import annotations

import argparse                              # options de la ligne de commande
import json                                  # écrire le fichier metadata.json
from datetime import datetime, timezone      # horodatage de la version du modèle
from pathlib import Path                     # chemins de fichiers

import joblib                                # sauvegarder / recharger le modèle sur disque
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV   # rend les probabilités plus fiables
from sklearn.ensemble import RandomForestClassifier      # modèle 2 : forêt aléatoire
from sklearn.frozen import FrozenEstimator               # "fige" un modèle déjà entraîné
from sklearn.linear_model import LogisticRegression      # modèle 1 : régression logistique (baseline)
from sklearn.pipeline import Pipeline                    # enchaîne pré-traitement + modèle
from xgboost import XGBClassifier                        # modèle 3 : gradient boosting

from ml.data_generator import CUTOFF, DATASET_VERSION          # date de coupure, version des données
from ml.evaluate import best_threshold_by_cost, compute_metrics, save_plots
from ml.feature_engineering import FEATURE_COLUMNS, TARGET, build_dataset
from ml.preprocessing import make_preprocessor

# ---------------------------------------------------------------------------
# RÉGLAGES
# ---------------------------------------------------------------------------
SEED = 42    # graine : mêmes résultats à chaque exécution
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"                  # backend/ml/artifacts/
REPORTS = Path(__file__).resolve().parents[2] / "docs" / "screenshots"     # où écrire les graphiques

# Découpage chronologique sur la date d'émission (jamais aléatoire).
TRAIN_END = pd.Timestamp("2024-07-01")   # train      : invoice_date <  2024-07-01
VALID_END = pd.Timestamp("2025-03-01")   # validation : 2024-07-01 <= date < 2025-03-01
                                         # test       : invoice_date >= 2025-03-01


# ---------------------------------------------------------------------------
# PARTIE 1 : charger les données
# ---------------------------------------------------------------------------
def load_frames(source: str, folder: Path):
    if source == "csv":    # lecture des fichiers CSV
        return (pd.read_csv(folder / "customers.csv"), pd.read_csv(folder / "invoices.csv"),
                pd.read_csv(folder / "payments.csv"))
    # sinon : lecture des 3 tables dans PostgreSQL
    from app.database.session import engine
    return tuple(pd.read_sql_table(t, engine) for t in ("customers", "invoices", "payments"))


# ---------------------------------------------------------------------------
# PARTIE 2 : découper dans le temps (train / validation / test)
# ---------------------------------------------------------------------------
def split_temporal(df: pd.DataFrame):
    train = df[df["invoice_date"] < TRAIN_END]                                   # le plus ancien
    valid = df[(df["invoice_date"] >= TRAIN_END) & (df["invoice_date"] < VALID_END)]   # au milieu
    test = df[df["invoice_date"] >= VALID_END]                                   # le plus récent
    return train, valid, test


# ---------------------------------------------------------------------------
# PARTIE 3 : définir les 3 modèles à comparer
# ---------------------------------------------------------------------------
def make_models() -> dict[str, Pipeline]:
    # Pas de class_weight : le taux de retard (~32 %) n'est que modérément déséquilibré, et
    # pondérer les classes fausserait les probabilités dont on a besoin pour le score de risque.
    return {
        # Modèle simple, sert de point de comparaison (baseline). Il a besoin de variables mises à l'échelle.
        "logistic_regression": Pipeline([
            ("preprocess", make_preprocessor(scale_numeric=True)),
            ("model", LogisticRegression(max_iter=2000, random_state=SEED))]),
        # 300 arbres de décision ; min_samples_leaf=20 évite le sur-apprentissage (feuilles trop petites).
        "random_forest": Pipeline([
            ("preprocess", make_preprocessor(scale_numeric=False)),   # les arbres n'ont pas besoin d'échelle
            ("model", RandomForestClassifier(n_estimators=300, min_samples_leaf=20,
                                             n_jobs=-1, random_state=SEED))]),
        # Arbres construits l'un après l'autre, chacun corrige les erreurs du précédent.
        "xgboost": Pipeline([
            ("preprocess", make_preprocessor(scale_numeric=False)),
            ("model", XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                                    subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
                                    tree_method="hist", random_state=SEED, n_jobs=-1))]),
    }


# ---------------------------------------------------------------------------
# PARTIE 4 : le programme principal
# ---------------------------------------------------------------------------
def main() -> None:
    # Options : d'où lire (csv ou db), quel dossier, et --activate pour marquer le modèle actif
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["csv", "db"], default="csv")
    parser.add_argument("--folder", type=Path, default=Path("../database/seed"))
    parser.add_argument("--activate", action="store_true", help="marque ce modèle comme actif")
    args = parser.parse_args()

    # Construire le tableau de variables (une ligne par facture), garder les factures étiquetées
    customers, invoices, payments = load_frames(args.source, args.folder)
    data = build_dataset(customers, invoices, payments, CUTOFF)
    labeled = data[data[TARGET].notna()].copy()
    train, valid, test = split_temporal(labeled)
    print(f"train {len(train):,} | validation {len(valid):,} | test {len(test):,} "
          f"| taux de retard train {train[TARGET].mean():.1%}, test {test[TARGET].mean():.1%}")

    # X = les variables ; y = la réponse (0 ou 1), pour chacun des 3 jeux
    X_tr, y_tr = train[FEATURE_COLUMNS], train[TARGET].astype(int)
    X_va, y_va = valid[FEATURE_COLUMNS], valid[TARGET].astype(int)
    X_te, y_te = test[FEATURE_COLUMNS], test[TARGET].astype(int)

    # 1) Entraînement sur train, comparaison sur VALIDATION
    fitted, val_metrics = {}, {}
    for name, pipe in make_models().items():
        pipe.fit(X_tr, y_tr)                     # le modèle apprend sur le train uniquement
        fitted[name] = pipe
        val_metrics[name] = compute_metrics(y_va, pipe.predict_proba(X_va)[:, 1])   # note sur la validation
        m = val_metrics[name]
        print(f"[validation] {name:20s} ROC-AUC {m['roc_auc']:.3f} | PR-AUC {m['pr_auc']:.3f} "
              f"| Brier {m['brier']:.3f}")

    # On choisit le meilleur modèle selon la PR-AUC de la VALIDATION (jamais du test)
    best_name = max(val_metrics, key=lambda n: val_metrics[n]["pr_auc"])
    print(f"=> meilleur modèle (PR-AUC validation) : {best_name}")

    # 2) Calibration du meilleur modèle sur la VALIDATION (modèle figé)
    base = fitted[best_name]
    # FrozenEstimator : on ne ré-entraîne pas le modèle, on apprend seulement à corriger ses probabilités
    calibrated = CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid")
    calibrated.fit(X_va, y_va)

    # 3) Seuil métier choisi sur la validation, puis évaluation unique sur le TEST
    p_va_cal = calibrated.predict_proba(X_va)[:, 1]
    threshold = best_threshold_by_cost(y_va, p_va_cal, cost_fp=1.0, cost_fn=5.0)   # faux négatif = 5 x faux positif
    # Probabilités sur le test pour les 3 modèles + la version calibrée du meilleur
    test_proba = {n: p.predict_proba(X_te)[:, 1] for n, p in fitted.items()}
    test_proba[f"{best_name} (calibré)"] = calibrated.predict_proba(X_te)[:, 1]
    test_metrics = {n: compute_metrics(y_te, p) for n, p in test_proba.items()}
    final_p = test_proba[f"{best_name} (calibré)"]
    final_at_business = compute_metrics(y_te, final_p, threshold)   # métriques avec le seuil métier
    for n, m in test_metrics.items():
        print(f"[test] {n:32s} ROC-AUC {m['roc_auc']:.3f} | PR-AUC {m['pr_auc']:.3f} | Brier {m['brier']:.3f}")
    print(f"[test] seuil métier {threshold:.2f} : précision {final_at_business['precision']:.2f}, "
          f"rappel {final_at_business['recall']:.2f}")

    # 4) Sauvegarde versionnée
    now = datetime.now(timezone.utc)
    version = f"v1-{best_name}-{now:%Y%m%d%H%M}"     # ex. v1-random_forest-202611081530
    out = ARTIFACTS / version
    out.mkdir(parents=True, exist_ok=True)
    # model.joblib : le modèle calibré, son pipeline de base et la liste des variables
    joblib.dump({"model": calibrated, "base_pipeline": base, "feature_columns": FEATURE_COLUMNS,
                 "model_version": version}, out / "model.joblib")
    # metadata.json : la "carte d'identité" du modèle (version, données, découpage, métriques, seuil)
    metadata = {
        "model_version": version, "algorithm": best_name, "trained_at": now.isoformat(),
        "training_dataset_version": DATASET_VERSION, "feature_list": FEATURE_COLUMNS,
        "split": {"train_end": str(TRAIN_END.date()), "valid_end": str(VALID_END.date())},
        "business_threshold": threshold, "cost_fp": 1.0, "cost_fn": 5.0,
        "validation_metrics": val_metrics, "test_metrics": test_metrics,
        "test_at_business_threshold": final_at_business,
        "synthetic_data_warning": "Métriques calculées sur des données synthétiques : "
                                  "elles ne prouvent aucune performance réelle.",
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    save_plots(y_te, test_proba, REPORTS)    # écrit roc.png, precision_recall.png, calibration.png
    if args.activate:    # active.json indique à l'API quel modèle utiliser
        (ARTIFACTS / "active.json").write_text(json.dumps({"model_version": version}), encoding="utf-8")
    print(f"modèle sauvegardé dans {out}" + (" (ACTIF)" if args.activate else ""))


if __name__ == "__main__":
    main()