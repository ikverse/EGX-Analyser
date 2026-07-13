"""Store the original AI provider response for local exports."""

from alembic import op
import sqlalchemy as sa


revision = "0002_add_raw_ai_response"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("ai_response_raw", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "ai_response_raw")
