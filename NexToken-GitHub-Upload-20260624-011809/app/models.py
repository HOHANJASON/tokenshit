from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now_utc():
    return datetime.utcnow()


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    google_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    google_picture: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    gmail_bound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="customer")


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    base_url: Mapped[str] = mapped_column(String(500))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    models: Mapped[list["ModelConfig"]] = relationship(back_populates="provider")
    routes: Mapped[list["ModelRoute"]] = relationship(back_populates="provider")


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    upstream_model: Mapped[str] = mapped_column(String(200))
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    input_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    output_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    input_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    output_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    endpoint_type: Mapped[str] = mapped_column(String(40), default="chat")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    provider: Mapped[Provider] = relationship(back_populates="models")
    routes: Mapped[list["ModelRoute"]] = relationship(back_populates="model", cascade="all, delete-orphan")


class ModelRoute(Base):
    __tablename__ = "model_routes"
    __table_args__ = (UniqueConstraint("model_config_id", "provider_id", "upstream_model", name="uq_model_route"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    upstream_model: Mapped[str] = mapped_column(String(200))
    input_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    output_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    priority: Mapped[int] = mapped_column(Integer, default=10)
    weight: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    disabled_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    model: Mapped[ModelConfig] = relationship(back_populates="routes")
    provider: Mapped[Provider] = relationship(back_populates="routes")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="Default")
    key_prefix: Mapped[str] = mapped_column(String(24), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
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
    kind: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)
    model: Mapped[str] = mapped_column(String(160), index=True)
    endpoint: Mapped[str] = mapped_column(String(40), default="chat.completions")
    units: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    upstream_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    charge: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    status: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
