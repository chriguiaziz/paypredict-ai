from __future__ import annotations

import uuid
from decimal import Decimal                    # montants exacts

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text                    # pour écrire du SQL brut (lecture de la vue)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.deps import get_current_user, require_role
from app.models import Customer, Invoice, Payment
from app.schemas import InvoiceIn, InvoiceOut, PaymentIn, PaymentOut
from app.services.audit import audit

router = APIRouter(tags=["invoices"])          # pas de préfixe : les routes ont /invoices ou /payments

# Colonnes autorisées pour le tri (liste blanche)
SORTABLE = {"due_date", "invoice_date", "invoice_amount", "days_overdue"}


# ---------------------------------------------------------------------------
# ROUTE 1 : GET /invoices (liste filtrée, triée, paginée) : tout utilisateur connecté
# ---------------------------------------------------------------------------
@router.get("/invoices", response_model=dict)
def list_invoices(customer_id: uuid.UUID | None = None, status_: str | None = Query(None, alias="status"),
                  overdue: bool | None = None, currency: str | None = None,
                  sort: str = "due_date", desc: bool = False,
                  limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Liste paginée, avec solde et retard calculés par la vue v_invoice_balances."""
    if sort not in SORTABLE:                       # liste blanche : le tri n'est jamais injecté tel quel
        raise HTTPException(422, f"tri autorisé : {sorted(SORTABLE)}")
    # On construit la clause WHERE morceau par morceau, avec des paramètres liés (:nom)
    where, params = ["1=1"], {"limit": limit, "offset": offset}
    if customer_id:
        where.append("customer_id = :customer_id"); params["customer_id"] = customer_id
    if status_:
        where.append("invoice_status = :status"); params["status"] = status_
    if overdue is not None:
        where.append("is_overdue = :overdue"); params["overdue"] = overdue
    if currency:
        where.append("currency = :currency"); params["currency"] = currency
    clause = " AND ".join(where)
    # Nombre total de résultats (avant pagination)
    total = db.execute(text(f"SELECT COUNT(*) FROM v_invoice_balances WHERE {clause}"), params).scalar_one()
    # Page demandée ; "invoice_id" en second critère de tri pour un ordre stable
    rows = db.execute(text(
        f"SELECT * FROM v_invoice_balances WHERE {clause} "
        f"ORDER BY {sort} {'DESC' if desc else 'ASC'}, invoice_id LIMIT :limit OFFSET :offset"), params).mappings().all()
    return {"items": [InvoiceOut.model_validate(dict(r)) for r in rows], "total": total,
            "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# ROUTE 2 : GET /invoices/{id} (une facture, avec son solde) : tout utilisateur connecté
# ---------------------------------------------------------------------------
@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db), _=Depends(get_current_user)):
    row = db.execute(text("SELECT * FROM v_invoice_balances WHERE invoice_id = :i"),
                     {"i": invoice_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Facture introuvable")
    return InvoiceOut.model_validate(dict(row))


# ---------------------------------------------------------------------------
# ROUTE 3 : POST /invoices (créer une facture) : rôle analyst minimum
# ---------------------------------------------------------------------------
@router.post("/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(body: InvoiceIn, db: Session = Depends(get_db), user=Depends(require_role("analyst"))):
    cust = db.get(Customer, body.customer_id)
    if not cust or cust.customer_status != "Active":       # le client doit exister et être actif
        raise HTTPException(422, "Client inconnu ou inactif")
    # Le délai de paiement est DÉDUIT des dates (échéance - émission, au minimum 1 jour) ; statut initial "Issued"
    inv = Invoice(**body.model_dump(), payment_terms_days=max((body.due_date - body.invoice_date).days, 1),
                  invoice_status="Issued")
    db.add(inv)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "invoice_number déjà utilisé")
    audit(db, user.user_id, "create", "invoice", inv.invoice_id)
    db.commit()
    return get_invoice(inv.invoice_id, db)                 # relit via la vue pour renvoyer solde et retard


# ---------------------------------------------------------------------------
# ROUTE 4 : POST /payments (enregistrer un paiement) : rôle analyst minimum
# ---------------------------------------------------------------------------
@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def record_payment(body: PaymentIn, db: Session = Depends(get_db), user=Depends(require_role("analyst"))):
    # Verrou de ligne : deux paiements simultanés ne peuvent pas dépasser le montant ensemble
    inv = db.query(Invoice).filter(Invoice.invoice_id == body.invoice_id).with_for_update().first()
    if not inv:
        raise HTTPException(404, "Facture introuvable")
    if inv.invoice_status in ("Cancelled", "Draft"):
        raise HTTPException(422, f"Paiement impossible sur une facture « {inv.invoice_status} »")
    if body.payment_date < inv.invoice_date:
        raise HTTPException(422, "Le paiement ne peut pas précéder la date de facture")
    # Total déjà payé (seulement les paiements "Completed")
    paid = sum((p.payment_amount for p in inv.payments if p.payment_status == "Completed"), Decimal("0"))
    if paid + body.payment_amount > inv.invoice_amount:
        raise HTTPException(422, f"Surpaiement refusé : reste à payer {inv.invoice_amount - paid}")
    pay = Payment(**body.model_dump(), payment_status="Completed")
    db.add(pay)
    # Met à jour le statut : soldée si le total atteint le montant, sinon partiellement payée
    if inv.invoice_status in ("Issued", "Partially Paid"):
        inv.invoice_status = "Paid" if paid + body.payment_amount == inv.invoice_amount else "Partially Paid"
    db.flush()
    audit(db, user.user_id, "create", "payment", pay.payment_id, {"invoice_id": str(inv.invoice_id)})
    db.commit()
    return pay