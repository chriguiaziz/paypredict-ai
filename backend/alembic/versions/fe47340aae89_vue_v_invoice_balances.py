"""vue v_invoice_balances

Revision ID: fe47340aae89
Revises: e2c5380cbb7a
Create Date: 2026-11-07 14:01:47.277447

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe47340aae89'
down_revision: Union[str, Sequence[str], None] = 'e2c5380cbb7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
CREATE OR REPLACE VIEW v_invoice_balances AS
WITH ref AS (
-- "aujourd'hui" métier : paramètre reference_date, sinon la date réelle
SELECT COALESCE(
(SELECT (value->>'date')::date FROM app_settings WHERE key = 'reference_date'),
CURRENT_DATE
) AS today
),
paid AS (
SELECT invoice_id, SUM(payment_amount) AS amount_paid
FROM payments
WHERE payment_status = 'Completed'
GROUP BY invoice_id
),
base AS (
SELECT i.invoice_id, i.invoice_number, i.customer_id, i.invoice_date, i.due_date,
i.invoice_amount, i.currency, i.invoice_status,
COALESCE(p.amount_paid, 0) AS amount_paid,
i.invoice_amount - COALESCE(p.amount_paid, 0) AS outstanding_balance
FROM invoices i
LEFT JOIN paid p ON p.invoice_id = i.invoice_id
)
SELECT b.*,
(b.invoice_status NOT IN ('Cancelled', 'Draft')
AND b.outstanding_balance > 0
AND b.due_date < ref.today) AS is_overdue,
CASE WHEN b.invoice_status NOT IN ('Cancelled', 'Draft')
AND b.outstanding_balance > 0
AND b.due_date < ref.today
THEN ref.today - b.due_date ELSE 0 END AS days_overdue
FROM base b CROSS JOIN ref
""")



def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP VIEW IF EXISTS v_invoice_balances")
