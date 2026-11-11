"""KPI du tableau de bord. RÈGLE : on ne somme JAMAIS des devises différentes -> un total par devise."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text            # text() = écrire du SQL brut (ici, plus lisible que l'ORM pour des agrégats)
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.deps import get_current_user

# Toutes les routes de ce fichier commencent par /dashboard
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# ROUTE 1 : GET /dashboard/summary -> les chiffres clés + la répartition du risque
# ---------------------------------------------------------------------------
@router.get("/summary")
def summary(db: Session = Depends(get_db), _=Depends(get_current_user)):   # tout utilisateur connecté (viewer+)
    # --- Partie A : les KPI financiers, une ligne PAR DEVISE (GROUP BY currency) ---
    # "FILTER (WHERE ...)" = compter/sommer seulement les lignes qui respectent la condition
    # (syntaxe PostgreSQL). On lit la vue v_invoice_balances : solde et retard sont déjà calculés.
    by_currency = db.execute(text("""
        SELECT currency,
               -- nombre de factures encore à payer (solde > 0), hors annulées et brouillons
               COUNT(*) FILTER (WHERE outstanding_balance > 0 AND invoice_status NOT IN ('Cancelled','Draft')) AS open_invoices,
               -- montant total restant dû ; COALESCE(..., 0) évite un NULL s'il n'y a aucune ligne
               COALESCE(SUM(outstanding_balance) FILTER (WHERE invoice_status NOT IN ('Cancelled','Draft')), 0) AS outstanding,
               -- combien de factures sont en retard, et pour quel montant
               COUNT(*) FILTER (WHERE is_overdue) AS overdue_invoices,
               COALESCE(SUM(outstanding_balance) FILTER (WHERE is_overdue), 0) AS overdue_amount
        FROM v_invoice_balances GROUP BY currency ORDER BY currency""")).mappings().all()

    # --- Partie B : répartition du niveau de risque (Low / Medium / High) ---
    # Une facture peut avoir plusieurs prédictions : on ne garde que la DERNIÈRE de chacune.
    # DISTINCT ON (invoice_id) = "une seule ligne par facture", celle qui vient en premier selon
    # l'ORDER BY, donc la plus récente (prediction_timestamp DESC). Propre à PostgreSQL.
    risk = db.execute(text("""
        WITH latest AS (
            SELECT DISTINCT ON (invoice_id) invoice_id, risk_level
            FROM predictions ORDER BY invoice_id, prediction_timestamp DESC)
        SELECT risk_level, COUNT(*) AS invoices FROM latest GROUP BY risk_level""")).mappings().all()

    # Réponse JSON : une liste de lignes par devise + un dictionnaire {"High": 12, "Low": 40, ...}
    return {"by_currency": [dict(r) for r in by_currency],
            "risk_distribution": {r["risk_level"]: r["invoices"] for r in risk}}


# ---------------------------------------------------------------------------
# ROUTE 2 : GET /dashboard/aging -> balance âgée (les impayés classés par ancienneté du retard)
# ---------------------------------------------------------------------------
@router.get("/aging")
def aging(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Balance âgée par devise : tranches de jours de retard."""
    rows = db.execute(text("""
        SELECT currency,
          -- CASE = un grand "si / sinon si" : chaque facture est rangée dans une tranche
          CASE WHEN days_overdue = 0 THEN 'Non échu'
               WHEN days_overdue <= 30 THEN '1-30 j'
               WHEN days_overdue <= 60 THEN '31-60 j'
               WHEN days_overdue <= 90 THEN '61-90 j'
               ELSE '> 90 j' END AS bucket,
          COUNT(*) AS invoices, SUM(outstanding_balance) AS amount
        FROM v_invoice_balances
        -- seulement ce qui reste à payer, hors annulées et brouillons
        WHERE outstanding_balance > 0 AND invoice_status NOT IN ('Cancelled','Draft')
        -- une ligne par (devise, tranche) ; MIN(days_overdue) sert à trier de la tranche
        -- la plus récente à la plus ancienne (et non par ordre alphabétique)
        GROUP BY currency, bucket ORDER BY currency, MIN(days_overdue)""")).mappings().all()
    return [dict(r) for r in rows]