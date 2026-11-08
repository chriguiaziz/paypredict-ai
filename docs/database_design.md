# Conception de la base de données PayPredict AI

Base : PostgreSQL 16. Schéma géré par **Alembic** (migrations versionnées), modèles définis avec **SQLAlchemy 2**.
Toutes les clés primaires sont des **UUID**. Les montants sont en `NUMERIC(14,2)` (jamais de flottants).

## Vue d'ensemble : 14 tables en 4 groupes

| Groupe | Tables |
| --- | --- |
| Authentification | `roles`, `users` |
| Données financières | `customers`, `invoices`, `payments` |
| Machine learning | `model_versions`, `model_metrics`, `predictions`, `recommendations` |
| Opérations et traçabilité | `reminder_logs`, `workflow_logs`, `approval_requests`, `audit_logs`, `app_settings` |

## Relations principales

```text
roles 1──* users
customers 1──* invoices 1──* payments
invoices 1──* predictions 1──* recommendations
invoices 1──* reminder_logs 1──* approval_requests *──1 users
model_versions 1──* model_metrics
users 1──* audit_logs
```

## Authentification

**roles** : `role_id` (PK), `role_name` (unique : admin, analyst, viewer), `description`.
**users** : `user_id` (PK), `email` (unique), `full_name`, `hashed_password`, `role_id` (FK → roles), `is_active`.
Hiérarchie des droits : viewer < analyst < admin.

## Données financières

**customers** : `customer_id` (PK), `customer_code` (unique), `company_name`, `industry`, `country`, `customer_segment`, `registration_date`, `payment_terms_days`, `credit_limit`, `customer_status`.

**invoices** : `invoice_id` (PK), `invoice_number` (unique), `customer_id` (FK → customers), `invoice_date`, `due_date`, `invoice_amount`, `currency`, `payment_terms_days`, `invoice_status`, `description`.

**payments** : `payment_id` (PK), `invoice_id` (FK → invoices), `payment_date`, `payment_amount`, `payment_method`, `transaction_reference`, `payment_status`.

## Machine learning

**model_versions** : `model_version` (unique), `algorithm`, `training_timestamp`, `training_dataset_version`, `feature_list` (JSONB), `artifact_path`, `is_active`.
Un index unique partiel garantit qu'**un seul modèle est actif** à la fois.

**model_metrics** : `model_version_id` (FK), `dataset_split` (train / validation / test), `metric_name`, `metric_value`.

**predictions** : `prediction_id` (PK), `invoice_id` (FK), `model_version`, `predicted_probability` (0 à 1), `risk_score` (0 à 100), `risk_level` (Low / Medium / High), `prediction_timestamp`, `prediction_horizon_days`, `explanation_data` (JSONB, explications SHAP).

**recommendations** : `prediction_id` (FK), `recommendation_type`, `recommendation_text`, `suggested_action`, `priority` (Low / Medium / High), `action_status`.

## Opérations et traçabilité

**reminder_logs** : relances de paiement. `idempotency_key` est **unique** : elle empêche d'envoyer deux fois la même relance. Autres colonnes : `invoice_id` (FK), `reminder_type`, `recipient_email`, `subject`, `send_status`, `sent_at`, `external_message_id`.

**approval_requests** : validation humaine d'une relance avant envoi. `reminder_id` (FK), `resume_url` (reprise du workflow n8n), `status` (Pending / Approved / Rejected), `decided_by` (FK → users), `decided_at`.

**workflow_logs** : journal d'exécution des workflows n8n (`workflow_name`, `execution_id`, `execution_status`, `started_at`, `completed_at`, `error_message`, `execution_metadata`).

**audit_logs** : qui a fait quoi (`user_id`, `action`, `entity_type`, `entity_id`, `details`).

**app_settings** : paramètres clé / valeur JSONB. Contient notamment `risk_thresholds` (seuils de risque) et `reference_date` (date métier « aujourd'hui », 2025-12-31).

## Contraintes CHECK (règles garanties par la base)

- `customers` : `payment_terms_days > 0`, `credit_limit >= 0`, statut Active ou Inactive.
- `invoices` : `invoice_amount > 0`, `due_date >= invoice_date`, `payment_terms_days > 0`, statut et devise dans une liste fermée (devises : EUR, USD, TND).
- `payments` : `payment_amount > 0`, statut valide.
- `predictions` : probabilité entre 0 et 1, score entre 0 et 100, niveau Low / Medium / High.
- `model_metrics` : split limité à train, validation, test.
- `approval_requests` : statut Pending, Approved ou Rejected.

## Index

Index sur les colonnes les plus filtrées : `invoices` (client, date de facture, échéance, statut), `payments` (facture, date), `customers` (secteur, segment), `predictions` (facture + date, niveau de risque), `audit_logs` (type + identifiant d'entité), `workflow_logs` (nom + date de début), `reminder_logs` (facture), `recommendations` (prédiction), `model_metrics` (version de modèle).

## Vue `v_invoice_balances`

Vue SQL qui calcule, pour chaque facture :
- `amount_paid` : somme des paiements au statut Completed ;
- `outstanding_balance` : montant de la facture moins le payé ;
- `is_overdue` et `days_overdue` : en retard si le solde est positif, le statut n'est ni Cancelled ni Draft et l'échéance est passée.

**Choix de conception :** le statut « Overdue » n'est **jamais stocké**. Il est calculé par la vue, qui est la source unique du solde pour l'API, n8n et Power BI. La date « aujourd'hui » vient du paramètre `reference_date` de `app_settings`, car les données synthétiques s'arrêtent le 31/12/2025.

## Choix techniques à retenir

- **Migrations Alembic** plutôt que des tables créées à la main : schéma reproductible et versionné dans Git.
- **Convention de nommage des contraintes** : permet à Alembic de les modifier ou supprimer de façon fiable.
- **Les KPI se calculent par devise** (EUR, USD, TND), jamais en additionnant des devises différentes.

## Diagramme entité-relation

À ajouter : `docs/screenshots/er_diagram.png`, exporté depuis DBeaver (clic droit sur la base, « View Diagram »).