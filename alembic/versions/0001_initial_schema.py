"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("channels", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("handle", sa.String(255), unique=True, nullable=False), sa.Column("title", sa.String(255)), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("analyst_score", sa.Float()))
    op.create_table("stocks", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("ticker", sa.String(30), unique=True, nullable=False), sa.Column("name_en", sa.String(255), nullable=False), sa.Column("name_ar", sa.String(255)), sa.Column("aliases", sa.JSON(), nullable=False))
    op.create_table("messages", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False), sa.Column("telegram_message_id", sa.Integer(), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True), nullable=False), sa.Column("author", sa.String(255)), sa.Column("text", sa.Text(), nullable=False), sa.Column("views", sa.Integer()), sa.Column("forwarded_from", sa.String(255)), sa.Column("processed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("channel_id", "telegram_message_id", name="uq_channel_telegram_message"))
    op.create_table("images", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False), sa.Column("path", sa.String(1024), unique=True, nullable=False), sa.Column("mime_type", sa.String(100)), sa.Column("ocr_text", sa.Text()), sa.Column("vision_analysis", sa.JSON()))
    op.create_table("recommendations", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False), sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id")), sa.Column("signal", sa.String(10), nullable=False), sa.Column("company_name", sa.String(255), nullable=False), sa.Column("ticker_raw", sa.String(30)), sa.Column("entry", sa.Float()), sa.Column("target", sa.Float()), sa.Column("stop_loss", sa.Float()), sa.Column("reason", sa.Text()), sa.Column("risk_level", sa.String(30)), sa.Column("time_horizon", sa.String(100)), sa.Column("indicators", sa.JSON(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False))
    op.create_table("embeddings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), unique=True, nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("vector", Vector(1536)))
    op.create_table("reports", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("report_date", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("markdown_path", sa.String(1024), nullable=False), sa.Column("html_path", sa.String(1024), nullable=False), sa.Column("pdf_path", sa.String(1024), nullable=False), sa.Column("summary", sa.JSON(), nullable=False))
    op.create_table("alerts", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(255), unique=True, nullable=False), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("conditions", sa.JSON(), nullable=False))

def downgrade() -> None:
    for name in ("alerts", "reports", "embeddings", "recommendations", "images", "messages", "stocks", "channels"): op.drop_table(name)
