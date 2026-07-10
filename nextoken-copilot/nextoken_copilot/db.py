"""A trimmed mirror of the NexToken database schema.

Same table and column names as the production app (see ``app/models.py`` in the
NexToken repo), so the queries in ``data_access.py`` port directly to the real
database. Only the columns the nextoken_copilot needs are included.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from .config import settings


class Base(DeclarativeBase):
    pass


def now_utc() -> datetime:
    return datetime.utcnow()


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="customer")


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    base_url: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    upstream_model: Mapped[str] = mapped_column(String(200))
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    input_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    output_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    input_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    output_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    provider: Mapped[Provider] = relationship()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="Default")
    key_prefix: Mapped[str] = mapped_column(String(24), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    rpm_limit: Mapped[int] = mapped_column(Integer, default=60)
    tpm_limit: Mapped[int] = mapped_column(Integer, default=100_000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="api_keys")


class Ledger(Base):
    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    kind: Mapped[str] = mapped_column(String(40))  # topup | debit | refund | adjust
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)
    model: Mapped[str] = mapped_column(String(160), index=True)
    endpoint: Mapped[str] = mapped_column(String(40), default="chat.completions")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # upstream_cost = what the platform pays; charge = what the customer pays.
    # The difference is margin -> ADMIN-only.
    upstream_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    charge: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    status: Mapped[int] = mapped_column(Integer, default=200)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    return SessionLocal()
