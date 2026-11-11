from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError      # erreur de la base : doublon, contrainte violée
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.deps import get_current_user, require_role
from app.models import Customer
from app.schemas import CustomerIn, CustomerOut, CustomerUpdate
from app.services.audit import audit

# Toutes les routes commencent par /customers
router = APIRouter(prefix="/customers", tags=["customers"])


# ---------------------------------------------------------------------------
# ROUTE 1 : GET /customers (liste filtrée et paginée) : tout utilisateur connecté
# ---------------------------------------------------------------------------
@router.get("", response_model=dict)
def list_customers(q: str | None = None, segment: str | None = None, industry: str | None = None,
                   include_inactive: bool = False,
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    # Paramètres facultatifs de l'URL : ?q=...&segment=SME&industry=Retail&limit=50&offset=0
    stmt = select(Customer)                                  # requête de base : tous les clients
    if not include_inactive:                                 # par défaut, on cache les clients désactivés
        stmt = stmt.where(Customer.customer_status == "Active")
    if q:                                                    # recherche texte sur le nom ou le code
        like = f"%{q}%"   # paramètre lié : pas d'injection SQL
        stmt = stmt.where(Customer.company_name.ilike(like) | Customer.customer_code.ilike(like))
    if segment:
        stmt = stmt.where(Customer.customer_segment == segment)
    if industry:
        stmt = stmt.where(Customer.industry == industry)
    # Nombre total de résultats (avant pagination), pour que l'interface affiche "page 1 sur N"
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    # Page demandée : tri par code, puis on saute `offset` lignes et on en prend `limit` au plus
    rows = db.scalars(stmt.order_by(Customer.customer_code).limit(limit).offset(offset)).all()
    return {"items": [CustomerOut.model_validate(r) for r in rows], "total": total,
            "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# ROUTE 2 : GET /customers/{id} (un client) : tout utilisateur connecté
# ---------------------------------------------------------------------------
@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: uuid.UUID, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.get(Customer, customer_id)                        # cherche par clé primaire
    if not c:
        raise HTTPException(404, "Client introuvable")
    return c


# ---------------------------------------------------------------------------
# ROUTE 3 : POST /customers (créer) : rôle analyst minimum
# ---------------------------------------------------------------------------
@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(body: CustomerIn, db: Session = Depends(get_db), user=Depends(require_role("analyst"))):
    c = Customer(**body.model_dump())     # body a déjà été validé par CustomerIn (montants, devise, segment...)
    db.add(c)
    try:
        db.flush()                        # envoie à la base : c'est là qu'un doublon est détecté
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "customer_code déjà utilisé")   # 409 = conflit
    audit(db, user.user_id, "create", "customer", c.customer_id)
    db.commit()
    return c


# ---------------------------------------------------------------------------
# ROUTE 4 : PATCH /customers/{id} (modifier partiellement) : rôle analyst minimum
# ---------------------------------------------------------------------------
@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: uuid.UUID, body: CustomerUpdate, db: Session = Depends(get_db),
                    user=Depends(require_role("analyst"))):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "Client introuvable")
    # exclude_unset=True : seulement les champs réellement envoyés (les autres restent inchangés)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(c, k, v)                                     # applique chaque modification
    audit(db, user.user_id, "update", "customer", c.customer_id, {"fields": list(changes)})   # trace les champs modifiés
    db.commit()
    return c


# ---------------------------------------------------------------------------
# ROUTE 5 : DELETE /customers/{id} (désactiver) : rôle admin uniquement
# ---------------------------------------------------------------------------
@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_customer(customer_id: uuid.UUID, db: Session = Depends(get_db),
                        user=Depends(require_role("admin"))):
    """Suppression LOGIQUE : l'historique des factures et des paiements est conservé."""
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "Client introuvable")
    c.customer_status = "Inactive"                           # on ne supprime pas la ligne : on la désactive
    audit(db, user.user_id, "deactivate", "customer", c.customer_id)
    db.commit()