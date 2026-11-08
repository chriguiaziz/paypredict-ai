"""Pré-traitement scikit-learn : identique à l'entraînement et à l'inférence."""
from __future__ import annotations
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from ml.feature_engineering import CATEGORICAL_FEATURES, NUMERIC_FEATURES
def make_preprocessor(scale_numeric: bool) -> ColumnTransformer:
    """Imputation (médiane) + mise à l'échelle optionnelle + encodage one-hot.
    Le préprocesseur est ajusté (fit) UNIQUEMENT sur le jeu d'entraînement : il fait partie
    du Pipeline, donc validation et test sont seulement transformés (jamais ajustés).
    """
    num_steps = [("impute", SimpleImputer(strategy="median"))]
    if scale_numeric: # nécessaire pour la régression logistique, inutile pour les arbres
        num_steps.append(("scale", StandardScaler()))
    return ColumnTransformer(
        transformers=[
            ("num", Pipeline(num_steps), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),CATEGORICAL_FEATURES),
        ],
        verbose_feature_names_out=True,
)
