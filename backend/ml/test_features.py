"""Tests anti-fuite et de cohérence du pipeline de variables."""
import numpy as np
import pandas as pd
import pytest

from ml.data_generator import CUTOFF, generate_all
from ml.feature_engineering import FEATURE_COLUMNS, TARGET, build_dataset
from ml.train import TRAIN_END, VALID_END, split_temporal

CUT = pd.Timestamp(CUTOFF)   # date de coupure T (31/12/2025), en format date pandas


# ---------------------------------------------------------------------------
# FIXTURES : préparations partagées, calculées une seule fois pour tout le fichier
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def frames():
    # Génère les 4 tables synthétiques (graine 42)
    return generate_all(seed=42)


@pytest.fixture(scope="module")
def dataset(frames):
    # Construit le tableau de variables (une ligne par facture éligible)
    return build_dataset(frames["customers"], frames["invoices"], frames["payments"], CUT)


# ---------------------------------------------------------------------------
# TEST 1 : pas de label pour les factures récentes
# ---------------------------------------------------------------------------
def test_no_label_for_recent_invoices(dataset):
    """Les factures récentes (issue pas encore certaine) ne sont jamais étiquetées."""
    # Factures émises dans les 60 derniers jours avant T
    recent = dataset[dataset["invoice_date"] >= CUT - pd.Timedelta(days=60)]
    # Leur cible doit être vide (NaN) pour TOUTES : on ne connaît pas encore leur issue
    assert recent[TARGET].isna().all()


# ---------------------------------------------------------------------------
# TEST 2 : la première facture d'un client n'a aucun historique
# ---------------------------------------------------------------------------
def test_first_invoice_has_no_history(dataset):
    # La toute première facture de chaque client
    first = dataset.sort_values("invoice_date").groupby("customer_id").head(1)
    assert (first["previous_invoice_count"] == 0).all()           # 0 facture précédente
    assert first["historical_late_payment_rate"].isna().all()     # donc taux de retard inconnu
    assert (first["has_history"] == 0).all()                      # et pas d'historique


# ---------------------------------------------------------------------------
# TEST 3 : LE PLUS IMPORTANT, les variables ne dépendent pas du futur
# ---------------------------------------------------------------------------
def test_features_do_not_depend_on_the_future(frames, dataset):
    """Si on supprime toutes les données postérieures à la date de prédiction P,
    les variables de la facture doivent rester IDENTIQUES."""
    # 20 factures au hasard, ayant déjà plus de 3 factures précédentes (reproductible : random_state=1)
    sample = dataset[dataset["previous_invoice_count"] > 3].sample(20, random_state=1)
    inv, pay, cust = frames["invoices"], frames["payments"], frames["customers"]
    for _, row in sample.iterrows():
        P = row["invoice_date"]    # date de prédiction = date d'émission de la facture testée
        # On COUPE le futur : factures émises jusqu'à P, paiements strictement avant P
        inv_t = inv[pd.to_datetime(inv["invoice_date"]) <= P]
        pay_t = pay[pd.to_datetime(pay["payment_date"]) < P]
        cust_row = cust[cust["customer_id"] == row["customer_id"]]
        # On recalcule les variables avec ces données tronquées, comme si on était au jour P
        truncated = build_dataset(cust_row, inv_t[inv_t["customer_id"] == row["customer_id"]],
                                  pay_t, P)
        same = truncated[truncated["invoice_id"] == row["invoice_id"]].iloc[0]
        # Chaque variable doit être exactement la même qu'avec toutes les données
        for col in FEATURE_COLUMNS:
            a, b = row[col], same[col]
            if isinstance(a, float) and np.isnan(a):
                assert np.isnan(b), col            # manquant des deux côtés
            elif isinstance(a, (int, float, np.floating, np.integer)):
                assert a == pytest.approx(b), col  # nombres égaux (à l'arrondi près)
            else:
                assert a == b, col                 # texte identique


# ---------------------------------------------------------------------------
# TEST 4 : le découpage train / validation / test ne se chevauche pas
# ---------------------------------------------------------------------------
def test_temporal_split_has_no_overlap(dataset):
    labeled = dataset[dataset[TARGET].notna()]
    train, valid, test = split_temporal(labeled)
    # Le train se termine avant le début de la validation, qui se termine avant le test
    assert train["invoice_date"].max() < valid["invoice_date"].min()
    assert valid["invoice_date"].max() < test["invoice_date"].min()
    # Et les bornes respectent les dates de coupure choisies
    assert train["invoice_date"].max() < TRAIN_END and test["invoice_date"].min() >= VALID_END


# ---------------------------------------------------------------------------
# TEST 5 : la cible ne contient que 0 ou 1
# ---------------------------------------------------------------------------
def test_label_is_binary(dataset):
    # Les valeurs présentes (hors NaN) doivent être un sous-ensemble de {0, 1}
    assert set(dataset[TARGET].dropna().unique()) <= {0.0, 1.0}