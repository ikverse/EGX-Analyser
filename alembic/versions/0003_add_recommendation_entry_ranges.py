"""Store exact low and high bounds for recommendation entry ranges."""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_recommendation_entry_ranges"
down_revision = "0002_add_raw_ai_response"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recommendations", sa.Column("entry_low", sa.Float(), nullable=True))
    op.add_column("recommendations", sa.Column("entry_high", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("recommendations", "entry_high")
    op.drop_column("recommendations", "entry_low")
