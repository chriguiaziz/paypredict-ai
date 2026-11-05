"""Tables métier : customers, invoices, payments."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
Numeric,
String, Text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, created_at_col, updated_at_col, uuid_pk
INVOICE_STATUSES = ("Draft", "Issued", "Partially Paid", "Paid", "Overdue", "Cancelled",
"Disputed")
CURRENCIES = ("EUR", "USD", "TND")
class Customer(Base):
    __tablename__ = "customers"
    customer_id: Mapped[uuid.UUID] = uuid_pk()
    customer_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(80), nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_segment: Mapped[str] = mapped_column(String(40), nullable=False)
    registration_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    customer_status: Mapped[str] = mapped_column(String(20), nullable=False,
    default="Active")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")
    __table_args__ = (
    CheckConstraint("payment_terms_days > 0", name="terms_positive"),
    CheckConstraint("credit_limit >= 0", name="credit_limit_non_negative"),
    CheckConstraint("customer_status IN ('Active','Inactive')", name="status_valid"),
    Index("ix_customers_industry", "industry"),
    Index("ix_customers_segment", "customer_segment"),
    )
class Invoice(Base):
    __tablename__ = "invoices"
    invoice_id: Mapped[uuid.UUID] = uuid_pk()
    invoice_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("customers.customer_id"), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    invoice_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_status: Mapped[str] = mapped_column(String(20), nullable=False,
    default="Issued")
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    customer: Mapped[Customer] = relationship(back_populates="invoices")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")
    __table_args__ = (
    CheckConstraint("invoice_amount > 0", name="amount_positive"),
    CheckConstraint("due_date >= invoice_date", name="due_after_invoice"),
    CheckConstraint("payment_terms_days > 0", name="terms_positive"),
    CheckConstraint(
    "invoice_status IN ('" + "','".join(INVOICE_STATUSES) + "')",
    name="status_valid"),
    CheckConstraint("currency IN ('" + "','".join(CURRENCIES) + "')",
    name="currency_valid"),
    Index("ix_invoices_customer_id", "customer_id"),
    Index("ix_invoices_invoice_date", "invoice_date"),
    Index("ix_invoices_due_date", "due_date"),
    Index("ix_invoices_invoice_status", "invoice_status"),
    )
class Payment(Base):
    __tablename__ = "payments"
    payment_id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("invoices.invoice_id"), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(40), nullable=False)
    transaction_reference: Mapped[str | None] = mapped_column(String(60))
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False,
    default="Completed")
    created_at: Mapped[datetime] = created_at_col()
    invoice: Mapped[Invoice] = relationship(back_populates="payments")
    __table_args__ = (
    CheckConstraint("payment_amount > 0", name="amount_positive"),
    CheckConstraint(
    "payment_status IN ('Completed','Pending','Failed','Refunded')",
    name="status_valid"),
    Index("ix_payments_invoice_id", "invoice_id"),
    Index("ix_payments_payment_date", "payment_date"),
    )