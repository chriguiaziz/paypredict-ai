"""Tests sans base de données : sécurité, recommandations, scoring, schémas, routes."""
import jwt                                   # pour attraper l'erreur PyJWT sur un jeton falsifié
import pandas as pd
import pytest
from fastapi.testclient import TestClient    # client HTTP de test : appelle l'API sans lancer uvicorn
from pydantic import ValidationError         # erreur levée quand un schéma refuse des données

from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.schemas import InvoiceIn
from app.services.recommendations import build_recommendation
from app.services.settings_store import risk_level

# Seuils de test : Medium à partir de 0,30 ; High à partir de 0,70
TH = {"medium_min": 0.30, "high_min": 0.70}


# ---------------------------------------------------------------------------
# TEST 1 : mots de passe (argon2)
# ---------------------------------------------------------------------------
def test_password_hash_and_verify():
    h = hash_password("S3cret!")
    # l'empreinte n'est pas le mot de passe, et elle commence par "$argon2" (l'algorithme utilisé)
    assert h != "S3cret!" and h.startswith("$argon2")
    # le bon mot de passe est accepté, un autre est refusé
    assert verify_password("S3cret!", h) and not verify_password("autre", h)
    # une valeur qui n'est pas une empreinte ne fait pas planter : elle est simplement refusée
    assert not verify_password("x", "pas-un-hash")


# ---------------------------------------------------------------------------
# TEST 2 : jeton JWT (aller-retour + falsification)
# ---------------------------------------------------------------------------
def test_jwt_roundtrip_and_tamper():
    token = create_access_token("abc", "analyst")
    assert decode_token(token)["role"] == "analyst"        # on retrouve ce qu'on a mis dedans
    with pytest.raises(jwt.PyJWTError):                    # on abîme les 2 derniers caractères (la signature)
        decode_token(token[:-2] + "xx")                    # -> le jeton doit être rejeté


# ---------------------------------------------------------------------------
# TEST 3 : niveaux de risque, avec les valeurs limites (parametrize = 1 test lancé 5 fois)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("p,expected", [(0.0, "Low"), (0.29, "Low"), (0.30, "Medium"), (0.699, "Medium"), (0.70, "High")])
def test_risk_levels(p, expected):
    assert risk_level(p, TH) == expected    # 0,30 est déjà Medium et 0,70 déjà High : seuils inclus


# ---------------------------------------------------------------------------
# TEST 4 : règles de recommandation
# ---------------------------------------------------------------------------
def test_recommendations_rules():
    # risque faible -> priorité faible
    assert build_recommendation("Low", 20, 500)["priority"] == "Low"
    # risque élevé + grosse facture (20 000 EUR) -> appel du responsable compte
    assert build_recommendation("High", 5, 20_000)["suggested_action"] == "Appel du responsable compte"
    # risque moyen + facture déjà échue (-10 jours avant échéance) -> relance de retard
    assert build_recommendation("Medium", -10, 500)["recommendation_type"] == "overdue_follow_up"


# ---------------------------------------------------------------------------
# TEST 5 : le schéma InvoiceIn refuse les données incohérentes
# ---------------------------------------------------------------------------
def test_invoice_schema_rejects_due_before_issue():
    # échéance (1er mai) AVANT la date d'émission (10 mai) -> refusé
    with pytest.raises(ValidationError):
        InvoiceIn(invoice_number="INV-1", customer_id="00000000-0000-0000-0000-000000000001",
                  invoice_date="2025-05-10", due_date="2025-05-01", invoice_amount="100.00", currency="EUR")
    # montant négatif -> refusé
    with pytest.raises(ValidationError):
        InvoiceIn(invoice_number="INV-1", customer_id="00000000-0000-0000-0000-000000000001",
                  invoice_date="2025-05-01", due_date="2025-06-01", invoice_amount="-5", currency="EUR")


# ---------------------------------------------------------------------------
# TEST 6 : le cœur du scoring fonctionne sur UN seul client (comme en production)
# Ce test exige que le modèle de la phase 2 soit entraîné et activé (--activate).
# ---------------------------------------------------------------------------
def test_scoring_core_on_synthetic_customer():
    """Le cœur de scoring fonctionne sur les données d'un seul client (comme en production)."""
    from ml.data_generator import generate_all
    from app.services.prediction import score_from_frames
    f = generate_all(42)                                   # on régénère les données synthétiques
    inv = f["invoices"]
    # on prend un client qui a au moins une facture ouverte
    cust_id = inv[inv["invoice_status"].isin(["Issued", "Partially Paid"])]["customer_id"].iloc[0]
    c_inv = inv[inv["customer_id"] == cust_id]             # toutes les factures de CE client
    target = c_inv[c_inv["invoice_status"].isin(["Issued", "Partially Paid"])].iloc[-1]   # la facture à scorer
    # on ne donne à la fonction que les données de ce client (ses factures et ses paiements)
    out = score_from_frames(f["customers"][f["customers"]["customer_id"] == cust_id], c_inv,
                            f["payments"][f["payments"]["invoice_id"].isin(c_inv["invoice_id"])],
                            target["invoice_id"], pd.Timestamp("2025-12-31").date(), TH)
    assert 0.0 <= out["probability"] <= 1.0                          # une probabilité est entre 0 et 1
    assert out["risk_level"] in {"Low", "Medium", "High"}
    assert len(out["explanation"]["top_factors"]) == 5               # 5 facteurs SHAP, pas un de plus


# ---------------------------------------------------------------------------
# TEST 7 : les routes protégées exigent un jeton valide
# ---------------------------------------------------------------------------
def test_protected_routes_require_token():
    from app.main import app
    client = TestClient(app)
    assert client.get("/api/v1/customers").status_code == 401          # pas de jeton -> 401
    assert client.get("/api/v1/dashboard/summary").status_code == 401
    # un faux jeton est refusé comme une absence de jeton
    assert client.get("/api/v1/models/active", headers={"Authorization": "Bearer faux"}).status_code == 401