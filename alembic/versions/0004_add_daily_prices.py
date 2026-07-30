"""Add daily prices for recommendation outcome scoring."""
from alembic import op
import sqlalchemy as sa

revision = "0004_add_daily_prices"
down_revision = "0003_add_recommendation_entry_ranges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=30), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=60), nullable=True),
        sa.UniqueConstraint("ticker", "session_date", name="uq_daily_price"),
    )
    op.create_index("ix_daily_prices_ticker", "daily_prices", ["ticker"])
    op.create_index("ix_daily_prices_session_date", "daily_prices", ["session_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_prices_session_date", table_name="daily_prices")
    op.drop_index("ix_daily_prices_ticker", table_name="daily_prices")
    op.drop_table("daily_prices")
