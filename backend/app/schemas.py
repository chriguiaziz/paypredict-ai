"""Schémas Pydantic (entrées/sorties de l'API). Les montants sont des Decimal, jamais des float.

Un schéma décrit la FORME attendue d'une donnée. Pydantic vérifie chaque champ
automatiquement : si une donnée entrante est invalide, l'API répond 422 sans
même exécuter la route. Convention : "...In" = ce qu'on REÇOIT, "...Out" = ce qu'on RENVOIE.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal                        # nombres décimaux exacts (jamais de float pour l'argent)
from typing import Literal                         # limite un champ à une liste de valeurs fixes

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

Currency = Literal["EUR", "USD", "TND"]            # seules ces 3 devises sont acceptées


class ORM(BaseModel):
    # Classe de base pour les schémas de SORTIE : permet de les remplir directement
    # à partir d'un objet SQLAlchemy (une ligne de la base), sans conversion manuelle.
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# AUTHENTIFICATION
# ---------------------------------------------------------------------------
class TokenOut(BaseModel):
    # Réponse de la connexion : le jeton JWT
    access_token: str
    token_type: str = "bearer"                     # valeur standard pour ce type de jeton


class UserOut(ORM):
    # Ce qu'on montre d'un utilisateur. Jamais le mot de passe haché.
    user_id: uuid.UUID
    email: EmailStr                                # vérifie que c'est une adresse e-mail valide
    full_name: str
    role: str


# ---------------------------------------------------------------------------
# CLIENTS
# ---------------------------------------------------------------------------
class CustomerIn(BaseModel):
    # Création d'un client : chaque champ a ses règles
    customer_code: str = Field(min_length=3, max_length=20)        # entre 3 et 20 caractères
    company_name: str = Field(min_length=1, max_length=200)
    industry: str
    country: str
    customer_segment: Literal["SME", "Mid-Market", "Enterprise"]   # liste fermée
    registration_date: date
    payment_terms_days: int = Field(gt=0, le=120)                  # gt = strictement supérieur à 0 ; le = inférieur ou égal à 120
    credit_limit: Decimal = Field(ge=0, max_digits=14, decimal_places=2)   # ge = supérieur ou égal à 0 ; 2 décimales max


class CustomerUpdate(BaseModel):
    # Modification partielle : tous les champs sont facultatifs (None = "ne pas changer")
    company_name: str | None = None
    industry: str | None = None
    country: str | None = None
    customer_segment: Literal["SME", "Mid-Market", "Enterprise"] | None = None
    payment_terms_days: int | None = Field(default=None, gt=0, le=120)
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class CustomerOut(ORM):
    # Un client tel que renvoyé par l'API
    customer_id: uuid.UUID
    customer_code: str
    company_name: str
    industry: str
    country: str
    customer_segment: str
    registration_date: date
    payment_terms_days: int
    credit_limit: Decimal
    customer_status: str


# ---------------------------------------------------------------------------
# FACTURES
# ---------------------------------------------------------------------------
class InvoiceIn(BaseModel):
    invoice_number: str = Field(min_length=3, max_length=40)
    customer_id: uuid.UUID
    invoice_date: date
    due_date: date
    invoice_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)   # montant strictement positif
    currency: Currency
    description: str | None = None                                           # facultatif

    @model_validator(mode="after")
    def due_after_issue(self):
        # Règle qui porte sur DEUX champs à la fois : l'échéance ne peut pas précéder l'émission
        if self.due_date < self.invoice_date:
            raise ValueError("due_date doit être postérieure ou égale à invoice_date")
        return self


class InvoiceOut(ORM):
    invoice_id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID
    invoice_date: date
    due_date: date
    invoice_amount: Decimal
    currency: str
    invoice_status: str
    # Champs calculés par la vue SQL v_invoice_balances (valeurs par défaut si absents)
    amount_paid: Decimal = Decimal("0")
    outstanding_balance: Decimal | None = None
    is_overdue: bool = False
    days_overdue: int = 0


# ---------------------------------------------------------------------------
# PAIEMENTS
# ---------------------------------------------------------------------------
class PaymentIn(BaseModel):
    invoice_id: uuid.UUID
    payment_date: date
    payment_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    payment_method: Literal["Bank Transfer", "Card", "Direct Debit", "Cheque"]
    transaction_reference: str | None = None


class PaymentOut(ORM):
    payment_id: uuid.UUID
    invoice_id: uuid.UUID
    payment_date: date
    payment_amount: Decimal
    payment_method: str
    payment_status: str


# ---------------------------------------------------------------------------
# PRÉDICTIONS ET RECOMMANDATIONS
# ---------------------------------------------------------------------------
class PredictionOut(ORM):
    prediction_id: uuid.UUID
    invoice_id: uuid.UUID
    model_version: str                             # quelle version du modèle a produit ce score
    predicted_probability: Decimal                 # probabilité de retard (0 à 1)
    risk_score: int                                # score de 0 à 100
    risk_level: str                                # Low, Medium ou High
    prediction_timestamp: datetime
    explanation_data: dict | None = None           # explications SHAP


class RecommendationOut(ORM):
    recommendation_id: uuid.UUID
    prediction_id: uuid.UUID
    recommendation_type: str
    recommendation_text: str
    suggested_action: str
    priority: str
    action_status: str


class RecommendationStatusIn(BaseModel):
    # Seuls ces trois nouveaux statuts peuvent être demandés
    action_status: Literal["Accepted", "Rejected", "Done"]