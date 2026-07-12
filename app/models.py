from datetime import datetime
from enum import StrEnum
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import VECTOR


class Base(DeclarativeBase):
    pass


class Signal(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    analyst_score: Mapped[float | None] = mapped_column(Float)
    last_collected_message_id: Mapped[int | None] = mapped_column(Integer)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    messages: Mapped[list["Message"]] = relationship(back_populates="channel")


class Stock(Base):
    __tablename__ = "stocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name_en: Mapped[str] = mapped_column(String(255))
    name_ar: Mapped[str | None] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("channel_id", "telegram_message_id", name="uq_channel_telegram_message"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    telegram_message_id: Mapped[int] = mapped_column(index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    author: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text, default="")
    views: Mapped[int | None] = mapped_column(Integer)
    forwarded_from: Mapped[str | None] = mapped_column(String(255))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[Channel] = relationship(back_populates="messages")
    images: Mapped[list["Image"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    media: Mapped[list["Media"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="message", cascade="all, delete-orphan")


class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    vision_analysis: Mapped[dict | None] = mapped_column(JSON)
    message: Mapped[Message] = relationship(back_populates="images")


class Media(Base):
    __tablename__ = "media"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    transcript: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[Message] = relationship(back_populates="media")


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    stock_id: Mapped[int | None] = mapped_column(ForeignKey("stocks.id"), index=True)
    signal: Mapped[str] = mapped_column(String(10))
    company_name: Mapped[str] = mapped_column(String(255))
    ticker_raw: Mapped[str | None] = mapped_column(String(30))
    entry: Mapped[float | None] = mapped_column(Float)
    target: Mapped[float | None] = mapped_column(Float)
    target_2: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(30))
    time_horizon: Mapped[str | None] = mapped_column(String(100))
    indicators: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    message: Mapped[Message] = relationship(back_populates="recommendations")
    stock: Mapped[Stock | None] = relationship()


class Embedding(Base):
    __tablename__ = "embeddings"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True)
    content: Mapped[str] = mapped_column(Text)
    vector: Mapped[list[float] | None] = mapped_column(VECTOR(1536).with_variant(JSON, "sqlite"))


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    markdown_path: Mapped[str] = mapped_column(String(1024))
    html_path: Mapped[str] = mapped_column(String(1024))
    pdf_path: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[dict] = mapped_column(JSON)


class AlertRule(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    conditions: Mapped[dict] = mapped_column(JSON)
