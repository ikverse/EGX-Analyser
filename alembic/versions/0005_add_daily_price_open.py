"""Record the session open, which settles same-session entry and target ordering."""
from alembic import op
import sqlalchemy as sa

revision = "0005_add_daily_price_open"
down_revision = "0004_add_daily_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows keep a null open and are treated as unknown rather than favourable until the
    # next price refresh rewrites them.
    op.add_column("daily_prices", sa.Column("open", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_prices", "open")
