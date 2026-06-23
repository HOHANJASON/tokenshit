import json
import os
import re
import time
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .cache import REDIS_REQUIRED, check_redis
from .database import SessionLocal, check_database, get_db
from .model_catalog import catalog_payload
from .models import ApiKey, Customer, Ledger, ModelConfig, ModelRoute, Provider, UsageLog
from .rate_limit import consume
from .routing import available_routes, mark_failure, mark_success
from .security import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    api_key_hash,
    create_token,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    new_customer_key,
    verify_password,
)


APP_NAME = "NexToken Local"
STATIC_DIR = Path(__file__).parent / "static"
SHOP_DIR = STATIC_DIR / "shop"
MONEY = Decimal("0.000001")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()

app = FastAPI(title=APP_NAME, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:3100,http://localhost:3100").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/assets", StaticFiles(directory=SHOP_DIR / "assets"), name="assets")


@app.on_event("startup")
def startup():
    check_database()
    if REDIS_REQUIRED:
        check_redis()


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def estimate_max_charge(body: dict, route: ModelConfig) -> Decimal:
    messages = body.get("messages") or []
    input_chars = sum(len(str(item.get("content", ""))) for item in messages if isinstance(item, dict))
    estimated_input_tokens = max(1, input_chars // 4)
    max_output_tokens = int(body.get("max_completion_tokens", body.get("max_tokens", 4096)) or 4096)
    max_output_tokens = min(max(max_output_tokens, 1), 128_000)
    return money(
        Decimal(estimated_input_tokens) / Decimal(1_000_000) * route.input_price
        + Decimal(max_output_tokens) / Decimal(1_000_000) * route.output_price
    )


def estimate_rate_tokens(body: dict) -> int:
    messages = body.get("messages") or []
    input_chars = sum(len(str(item.get("content", ""))) for item in messages if isinstance(item, dict))
    estimated_input = max(1, input_chars // 4)
    requested_output = int(body.get("max_completion_tokens", body.get("max_tokens", 4096)) or 4096)
    return estimated_input + min(max(requested_output, 1), 128_000)


def reserve_balance(db: Session, customer_id: int, amount: Decimal, model: str, request_id: str) -> None:
    customer = db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
    if not customer or not customer.active:
        raise HTTPException(status_code=403, detail="Customer is disabled")
    if customer.balance < amount:
        raise HTTPException(status_code=402, detail=f"Insufficient balance. Required reserve: ${amount}")
    customer.balance -= amount
    db.add(Ledger(customer_id=customer.id, amount=-amount, kind="api_reserve", note=f"{model}:{request_id}"))
    db.commit()


def release_reserve(db: Session, customer_id: int, amount: Decimal, model: str, request_id: str) -> None:
    customer = db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
    if not customer:
        return
    customer.balance += amount
    db.add(Ledger(customer_id=customer.id, amount=amount, kind="api_release", note=f"{model}:{request_id}"))
    db.commit()


def settle_usage(
    db: Session,
    *,
    customer_id: int,
    api_key_id: int,
    route_id: int,
    model_name: str,
    request_id: str,
    reserved: Decimal,
    input_tokens: int,
    output_tokens: int,
    status: int,
    latency_ms: int,
) -> Decimal:
    customer = db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
    route = db.get(ModelRoute, route_id)
    if not customer or not route:
        raise RuntimeError("Billing target disappeared during request settlement")
    model = route.model
    charge = money(
        Decimal(input_tokens) / Decimal(1_000_000) * model.input_price
        + Decimal(output_tokens) / Decimal(1_000_000) * model.output_price
    )
    cost = money(
        Decimal(input_tokens) / Decimal(1_000_000) * route.input_cost
        + Decimal(output_tokens) / Decimal(1_000_000) * route.output_cost
    )
    adjustment = reserved - charge
    customer.balance += adjustment
    key = db.get(ApiKey, api_key_id)
    if key:
        key.last_used_at = datetime.utcnow()
    if adjustment:
        db.add(Ledger(customer_id=customer.id, amount=adjustment, kind="api_settlement", note=f"{model_name}:{request_id}"))
    db.add(
        UsageLog(
            customer_id=customer.id,
            api_key_id=api_key_id,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            upstream_cost=cost,
            charge=charge,
            status=status,
            latency_ms=latency_ms,
        )
    )
    db.commit()
    return charge


def settle_units(
    db: Session,
    *,
    customer_id: int,
    api_key_id: int,
    route_id: int,
    model_name: str,
    request_id: str,
    reserved: Decimal,
    units: int,
    status: int,
    latency_ms: int,
) -> Decimal:
    customer = db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
    route = db.get(ModelRoute, route_id)
    if not customer or not route:
        raise RuntimeError("Billing target disappeared during request settlement")
    charge = money(route.model.unit_price * units)
    cost = money(route.unit_cost * units)
    adjustment = reserved - charge
    customer.balance += adjustment
    key = db.get(ApiKey, api_key_id)
    if key:
        key.last_used_at = datetime.utcnow()
    if adjustment:
        db.add(Ledger(customer_id=customer.id, amount=adjustment, kind="api_settlement", note=f"{model_name}:{request_id}"))
    db.add(
        UsageLog(
            customer_id=customer.id,
            api_key_id=api_key_id,
            model=model_name,
            endpoint="images.generations",
            units=units,
            upstream_cost=cost,
            charge=charge,
            status=status,
            latency_ms=latency_ms,
        )
    )
    db.commit()
    return charge


def log_failed_request(
    db: Session,
    *,
    customer_id: int,
    api_key_id: int,
    model_name: str,
    status: int,
    latency_ms: int,
    error: str,
) -> None:
    db.add(
        UsageLog(
            customer_id=customer_id,
            api_key_id=api_key_id,
            model=model_name,
            status=status,
            latency_ms=latency_ms,
            error=error[:2000],
        )
    )
    db.commit()


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    return authorization[7:].strip()


def admin_auth(authorization: str | None = Header(default=None)):
    return decode_token(bearer(authorization), "admin")


def customer_auth(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Customer:
    payload = decode_token(bearer(authorization), "customer")
    customer = db.get(Customer, int(payload["sub"]))
    if not customer or not customer.active:
        raise HTTPException(status_code=403, detail="Customer is disabled")
    return customer


def customer_from_api_key(authorization: str | None, db: Session):
    raw = bearer(authorization)
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == api_key_hash(raw), ApiKey.active.is_(True)))
    if not key or not key.customer.active:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key.customer, key


async def verify_google_credential(credential: str) -> dict:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google login is not configured")
    credential = credential.strip()
    if not credential:
        raise HTTPException(status_code=422, detail="Google credential is required")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": credential})
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Google token verification unavailable") from exc
    if not response.is_success:
        raise HTTPException(status_code=401, detail="Invalid Google credential")
    payload = response.json()
    if payload.get("aud") != GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="Google credential audience mismatch")
    if str(payload.get("email_verified", "")).lower() != "true":
        raise HTTPException(status_code=401, detail="Google email is not verified")
    email = str(payload.get("email", "")).strip().lower()
    if not email.endswith("@gmail.com"):
        raise HTTPException(status_code=422, detail="Only Gmail accounts can be bound")
    sub = str(payload.get("sub", "")).strip()
    if not sub:
        raise HTTPException(status_code=401, detail="Google subject is missing")
    return {"sub": sub, "email": email, "picture": payload.get("picture") or None}


def apply_google_identity(customer: Customer, identity: dict) -> None:
    customer.google_sub = identity["sub"]
    customer.google_email = identity["email"]
    customer.google_picture = identity.get("picture")
    customer.email_verified = True
    customer.gmail_bound_at = datetime.utcnow()


class LoginBody(BaseModel):
    username: str
    password: str


class CustomerLoginBody(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=200)


class GoogleCredentialBody(BaseModel):
    credential: str = Field(min_length=20)


class ProviderBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(min_length=4)
    priority: int = Field(default=10, ge=0, le=1000)
    active: bool = True


class ModelBody(BaseModel):
    public_name: str = Field(min_length=1, max_length=160)
    upstream_model: str = Field(min_length=1, max_length=200)
    provider_id: int
    input_cost: Decimal = Field(default=Decimal("0"), ge=0)
    output_cost: Decimal = Field(default=Decimal("0"), ge=0)
    input_price: Decimal = Field(ge=0)
    output_price: Decimal = Field(ge=0)
    endpoint_type: str = Field(default="chat", pattern="^(chat|image)$")
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    active: bool = True


class RouteBody(BaseModel):
    provider_id: int
    upstream_model: str = Field(min_length=1, max_length=200)
    input_cost: Decimal = Field(default=Decimal("0"), ge=0)
    output_cost: Decimal = Field(default=Decimal("0"), ge=0)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    priority: int = Field(default=10, ge=0, le=1000)
    weight: int = Field(default=100, ge=1, le=10_000)
    active: bool = True


class TopupBody(BaseModel):
    customer_id: int
    amount: Decimal
    note: str = Field(default="Manual top-up", max_length=500)


class KeyBody(BaseModel):
    name: str = Field(default="Default", min_length=1, max_length=100)


class KeyLimitBody(BaseModel):
    rpm_limit: int = Field(default=60, ge=0, le=1_000_000)
    tpm_limit: int = Field(default=100_000, ge=0, le=2_000_000_000)


@app.get("/health")
def health():
    return {"status": "ok", "service": APP_NAME, "version": app.version}


@app.get("/health/ready")
def readiness():
    try:
        check_database()
        redis_ok = check_redis()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="A required dependency is unavailable") from exc
    return {
        "status": "ready",
        "database": "ok",
        "redis": "ok" if redis_ok else ("required" if REDIS_REQUIRED else "disabled"),
    }


@app.get("/")
def shop():
    return FileResponse(SHOP_DIR / "index.html")


@app.get("/config.js")
def portal_config(request: Request):
    origin = str(request.base_url).rstrip("/")
    body = (
        "window.NEXTOKEN_CONFIG = "
        + json.dumps(
            {
                "apiOrigin": origin,
                "apiBaseUrl": origin + "/v1",
                "registerUrl": origin + "/customer",
                "loginUrl": origin + "/customer",
                "topupUrl": origin + "/customer",
            }
        )
        + ";"
    )
    return Response(body, media_type="application/javascript")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/customer")
def customer_page():
    return FileResponse(STATIC_DIR / "customer.html")


@app.get("/api/auth/google/config")
def google_auth_config():
    return {"enabled": bool(GOOGLE_CLIENT_ID), "client_id": GOOGLE_CLIENT_ID if GOOGLE_CLIENT_ID else None}


@app.post("/api/admin/login")
def admin_login(body: LoginBody):
    if body.username != ADMIN_USERNAME or body.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(body.username, "admin")}


@app.post("/api/customer/register")
def customer_register(body: CustomerLoginBody, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=422, detail="Invalid email")
    if db.scalar(select(Customer).where(Customer.email == email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    customer = Customer(email=email, password_hash=hash_password(body.password))
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return {"token": create_token(str(customer.id), "customer", hours=24)}


@app.post("/api/customer/login")
def customer_login(body: CustomerLoginBody, db: Session = Depends(get_db)):
    customer = db.scalar(select(Customer).where(Customer.email == body.email.strip().lower()))
    if not customer or not verify_password(body.password, customer.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not customer.active:
        raise HTTPException(status_code=403, detail="Customer is disabled")
    return {"token": create_token(str(customer.id), "customer", hours=24)}


@app.post("/api/customer/google/login")
async def customer_google_login(body: GoogleCredentialBody, db: Session = Depends(get_db)):
    identity = await verify_google_credential(body.credential)
    customer = db.scalar(select(Customer).where(Customer.google_sub == identity["sub"]))
    if not customer:
        customer = db.scalar(select(Customer).where(Customer.email == identity["email"]))
        if customer and customer.google_sub and customer.google_sub != identity["sub"]:
            raise HTTPException(status_code=409, detail="This Gmail is already linked to another Google identity")
        if not customer:
            customer = Customer(email=identity["email"], password_hash=hash_password(uuid.uuid4().hex))
            db.add(customer)
            db.flush()
        apply_google_identity(customer, identity)
        db.commit()
        db.refresh(customer)
    if not customer.active:
        raise HTTPException(status_code=403, detail="Customer is disabled")
    return {"token": create_token(str(customer.id), "customer", hours=24), "email": customer.email}


@app.post("/api/customer/google/bind")
async def customer_google_bind(body: GoogleCredentialBody, customer: Customer = Depends(customer_auth), db: Session = Depends(get_db)):
    identity = await verify_google_credential(body.credential)
    existing = db.scalar(select(Customer).where(Customer.google_sub == identity["sub"], Customer.id != customer.id))
    if existing:
        raise HTTPException(status_code=409, detail="This Gmail is already bound to another account")
    if customer.email != identity["email"]:
        same_email = db.scalar(select(Customer).where(Customer.email == identity["email"], Customer.id != customer.id))
        if same_email:
            raise HTTPException(status_code=409, detail="This Gmail email is already registered")
    apply_google_identity(customer, identity)
    db.commit()
    return {"ok": True, "gmail": customer.google_email, "bound_at": customer.gmail_bound_at.isoformat() if customer.gmail_bound_at else None}


@app.get("/api/customer/me")
def customer_me(customer: Customer = Depends(customer_auth)):
    return {
        "id": customer.id,
        "email": customer.email,
        "balance": float(customer.balance),
        "active": customer.active,
        "gmail": customer.google_email,
        "email_verified": customer.email_verified,
        "gmail_bound_at": customer.gmail_bound_at.isoformat() if customer.gmail_bound_at else None,
    }


@app.get("/api/customer/keys")
def customer_keys(customer: Customer = Depends(customer_auth), db: Session = Depends(get_db)):
    rows = db.scalars(select(ApiKey).where(ApiKey.customer_id == customer.id).order_by(ApiKey.created_at.desc())).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "prefix": row.key_prefix,
            "active": row.active,
            "rpm_limit": row.rpm_limit,
            "tpm_limit": row.tpm_limit,
            "created_at": row.created_at.isoformat(),
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        }
        for row in rows
    ]


@app.post("/api/customer/keys")
def create_customer_key(body: KeyBody, customer: Customer = Depends(customer_auth), db: Session = Depends(get_db)):
    raw = new_customer_key()
    row = ApiKey(customer_id=customer.id, name=body.name, key_prefix=raw[:18], key_hash=api_key_hash(raw))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "api_key": raw, "warning": "This key is shown only once."}


@app.patch("/api/customer/keys/{key_id}/toggle")
def toggle_customer_key(key_id: int, customer: Customer = Depends(customer_auth), db: Session = Depends(get_db)):
    row = db.get(ApiKey, key_id)
    if not row or row.customer_id != customer.id:
        raise HTTPException(status_code=404, detail="Key not found")
    row.active = not row.active
    db.commit()
    return {"active": row.active}


@app.get("/api/customer/usage")
def customer_usage(customer: Customer = Depends(customer_auth), db: Session = Depends(get_db)):
    rows = db.scalars(select(UsageLog).where(UsageLog.customer_id == customer.id).order_by(UsageLog.created_at.desc()).limit(100)).all()
    return [
        {
            "id": row.id,
            "model": row.model,
            "endpoint": row.endpoint,
            "units": row.units,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "charge": float(row.charge),
            "status": row.status,
            "latency_ms": row.latency_ms,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.get("/api/admin/dashboard", dependencies=[Depends(admin_auth)])
def admin_dashboard(db: Session = Depends(get_db)):
    return {
        "customers": db.scalar(select(func.count(Customer.id))) or 0,
        "providers": db.scalar(select(func.count(Provider.id)).where(Provider.active.is_(True))) or 0,
        "models": db.scalar(select(func.count(ModelConfig.id)).where(ModelConfig.active.is_(True))) or 0,
        "requests": db.scalar(select(func.count(UsageLog.id))) or 0,
        "revenue": float(db.scalar(select(func.coalesce(func.sum(UsageLog.charge), 0))) or 0),
        "upstream_cost": float(db.scalar(select(func.coalesce(func.sum(UsageLog.upstream_cost), 0))) or 0),
    }


@app.get("/api/admin/providers", dependencies=[Depends(admin_auth)])
def list_providers(db: Session = Depends(get_db)):
    rows = db.scalars(select(Provider).order_by(Provider.priority, Provider.id)).all()
    return [
        {"id": r.id, "name": r.name, "base_url": r.base_url, "api_key": "********", "priority": r.priority, "active": r.active}
        for r in rows
    ]


@app.post("/api/admin/providers", dependencies=[Depends(admin_auth)])
def create_provider(body: ProviderBody, db: Session = Depends(get_db)):
    if db.scalar(select(Provider).where(Provider.name == body.name.strip())):
        raise HTTPException(status_code=409, detail="Provider name already exists")
    row = Provider(
        name=body.name.strip(),
        base_url=body.base_url.rstrip("/"),
        api_key_encrypted=encrypt_secret(body.api_key.strip()),
        priority=body.priority,
        active=body.active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id}


@app.put("/api/admin/providers/{provider_id}", dependencies=[Depends(admin_auth)])
def update_provider(provider_id: int, body: ProviderBody, db: Session = Depends(get_db)):
    row = db.get(Provider, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    row.name = body.name.strip()
    row.base_url = body.base_url.rstrip("/")
    if body.api_key != "********":
        row.api_key_encrypted = encrypt_secret(body.api_key.strip())
    row.priority = body.priority
    row.active = body.active
    db.commit()
    return {"ok": True}


@app.post("/api/admin/providers/{provider_id}/test", dependencies=[Depends(admin_auth)])
async def test_provider(provider_id: int, db: Session = Depends(get_db)):
    row = db.get(Provider, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(row.base_url + "/models", headers={"Authorization": "Bearer " + decrypt_secret(row.api_key_encrypted)})
        return {"ok": response.is_success, "status": response.status_code, "latency_ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc), "latency_ms": int((time.perf_counter() - started) * 1000)}


@app.get("/api/admin/models", dependencies=[Depends(admin_auth)])
def list_models(db: Session = Depends(get_db)):
    rows = db.scalars(select(ModelConfig).order_by(ModelConfig.public_name)).all()
    return [
        {
            "id": r.id,
            "public_name": r.public_name,
            "upstream_model": r.upstream_model,
            "provider_id": r.provider_id,
            "provider_name": r.provider.name,
            "input_cost": float(r.input_cost),
            "output_cost": float(r.output_cost),
            "input_price": float(r.input_price),
            "output_price": float(r.output_price),
            "endpoint_type": r.endpoint_type,
            "unit_cost": float(r.routes[0].unit_cost) if r.routes else 0,
            "unit_price": float(r.unit_price),
            "active": r.active,
            "route_count": len(r.routes),
        }
        for r in rows
    ]


@app.post("/api/admin/models", dependencies=[Depends(admin_auth)])
def create_model(body: ModelBody, db: Session = Depends(get_db)):
    if not db.get(Provider, body.provider_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    if db.scalar(select(ModelConfig).where(ModelConfig.public_name == body.public_name.strip())):
        raise HTTPException(status_code=409, detail="Public model name already exists")
    row = ModelConfig(**body.model_dump(exclude={"unit_cost"}))
    row.public_name = row.public_name.strip()
    row.upstream_model = row.upstream_model.strip()
    db.add(row)
    db.flush()
    db.add(
        ModelRoute(
            model_config_id=row.id,
            provider_id=body.provider_id,
            upstream_model=body.upstream_model.strip(),
            input_cost=body.input_cost,
            output_cost=body.output_cost,
            unit_cost=body.unit_cost,
            priority=10,
            weight=100,
            active=body.active,
        )
    )
    db.commit()
    db.refresh(row)
    return {"id": row.id}


@app.put("/api/admin/models/{model_id}", dependencies=[Depends(admin_auth)])
def update_model(model_id: int, body: ModelBody, db: Session = Depends(get_db)):
    row = db.get(ModelConfig, model_id)
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    for key, value in body.model_dump(exclude={"unit_cost"}).items():
        setattr(row, key, value)
    primary_route = db.scalar(select(ModelRoute).where(ModelRoute.model_config_id == row.id).order_by(ModelRoute.priority, ModelRoute.id))
    if primary_route:
        primary_route.provider_id = body.provider_id
        primary_route.upstream_model = body.upstream_model.strip()
        primary_route.input_cost = body.input_cost
        primary_route.output_cost = body.output_cost
        primary_route.unit_cost = body.unit_cost
        primary_route.active = body.active
    db.commit()
    return {"ok": True}


@app.get("/api/admin/models/{model_id}/routes", dependencies=[Depends(admin_auth)])
def list_model_routes(model_id: int, db: Session = Depends(get_db)):
    if not db.get(ModelConfig, model_id):
        raise HTTPException(status_code=404, detail="Model not found")
    rows = db.scalars(select(ModelRoute).where(ModelRoute.model_config_id == model_id).order_by(ModelRoute.priority, ModelRoute.id)).all()
    return [
        {
            "id": row.id,
            "provider_id": row.provider_id,
            "provider_name": row.provider.name,
            "upstream_model": row.upstream_model,
            "input_cost": float(row.input_cost),
            "output_cost": float(row.output_cost),
            "unit_cost": float(row.unit_cost),
            "priority": row.priority,
            "weight": row.weight,
            "active": row.active,
            "failure_count": row.failure_count,
            "disabled_until": row.disabled_until.isoformat() if row.disabled_until else None,
            "last_error": row.last_error,
        }
        for row in rows
    ]


@app.post("/api/admin/models/{model_id}/routes", dependencies=[Depends(admin_auth)])
def create_model_route(model_id: int, body: RouteBody, db: Session = Depends(get_db)):
    if not db.get(ModelConfig, model_id):
        raise HTTPException(status_code=404, detail="Model not found")
    if not db.get(Provider, body.provider_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    row = ModelRoute(model_config_id=model_id, **body.model_dump())
    row.upstream_model = row.upstream_model.strip()
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id}


@app.put("/api/admin/routes/{route_id}", dependencies=[Depends(admin_auth)])
def update_model_route(route_id: int, body: RouteBody, db: Session = Depends(get_db)):
    row = db.get(ModelRoute, route_id)
    if not row:
        raise HTTPException(status_code=404, detail="Route not found")
    if not db.get(Provider, body.provider_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.failure_count = 0
    row.disabled_until = None
    row.last_error = None
    db.commit()
    return {"ok": True}


@app.get("/api/admin/customers", dependencies=[Depends(admin_auth)])
def list_customers(db: Session = Depends(get_db)):
    rows = db.scalars(select(Customer).order_by(Customer.created_at.desc())).all()
    return [
        {
            "id": r.id,
            "email": r.email,
            "gmail": r.google_email,
            "email_verified": r.email_verified,
            "gmail_bound_at": r.gmail_bound_at.isoformat() if r.gmail_bound_at else None,
            "balance": float(r.balance),
            "active": r.active,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.get("/api/admin/customers/{customer_id}/keys", dependencies=[Depends(admin_auth)])
def list_customer_keys_admin(customer_id: int, db: Session = Depends(get_db)):
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    rows = db.scalars(select(ApiKey).where(ApiKey.customer_id == customer_id).order_by(ApiKey.created_at.desc())).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "prefix": row.key_prefix,
            "active": row.active,
            "rpm_limit": row.rpm_limit,
            "tpm_limit": row.tpm_limit,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        }
        for row in rows
    ]


@app.patch("/api/admin/keys/{key_id}/limits", dependencies=[Depends(admin_auth)])
def update_key_limits(key_id: int, body: KeyLimitBody, db: Session = Depends(get_db)):
    row = db.get(ApiKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="Key not found")
    row.rpm_limit = body.rpm_limit
    row.tpm_limit = body.tpm_limit
    db.commit()
    return {"rpm_limit": row.rpm_limit, "tpm_limit": row.tpm_limit}


@app.post("/api/admin/topup", dependencies=[Depends(admin_auth)])
def admin_topup(body: TopupBody, db: Session = Depends(get_db)):
    customer = db.get(Customer, body.customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    amount = money(body.amount)
    if amount == 0:
        raise HTTPException(status_code=422, detail="Amount cannot be zero")
    if customer.balance + amount < 0:
        raise HTTPException(status_code=422, detail="Balance cannot be negative")
    customer.balance += amount
    db.add(Ledger(customer_id=customer.id, amount=amount, kind="admin_topup", note=body.note))
    db.commit()
    return {"balance": float(customer.balance)}


@app.get("/api/admin/logs", dependencies=[Depends(admin_auth)])
def admin_logs(db: Session = Depends(get_db)):
    rows = db.scalars(select(UsageLog).order_by(UsageLog.created_at.desc()).limit(200)).all()
    return [
        {
            "id": r.id,
            "customer_id": r.customer_id,
            "model": r.model,
            "endpoint": r.endpoint,
            "units": r.units,
            "tokens": r.input_tokens + r.output_tokens,
            "cost": float(r.upstream_cost),
            "charge": float(r.charge),
            "status": r.status,
            "latency_ms": r.latency_ms,
            "error": r.error,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.get("/api/pricing")
def pricing(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ModelConfig)
        .join(Provider)
        .where(ModelConfig.active.is_(True), Provider.active.is_(True))
        .order_by(ModelConfig.public_name)
    ).all()
    data = []
    for row in rows:
        input_price = float(row.input_price)
        data.append(
            {
                "model_name": row.public_name,
                "vendor_name": row.provider.name,
                "quota_type": 0,
                "model_ratio": input_price / 2,
                "completion_ratio": float(row.output_price / row.input_price) if row.input_price else 1,
                "cache_ratio": None,
                "endpoint_type": row.endpoint_type,
                "unit_price": float(row.unit_price),
                "group_ratio": {"default": 1},
                "description": f"{row.provider.name} / {row.upstream_model}",
            }
        )
    return {"success": True, "data": data}


@app.get("/api/catalog")
def model_catalog():
    return {"success": True, "count": 31, "data": catalog_payload()}


@app.get("/v1/models")
def openai_models(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ModelConfig)
        .join(ModelRoute, ModelRoute.model_config_id == ModelConfig.id)
        .join(Provider, ModelRoute.provider_id == Provider.id)
        .where(ModelConfig.active.is_(True), ModelRoute.active.is_(True), Provider.active.is_(True))
        .distinct()
    ).all()
    return {"object": "list", "data": [{"id": row.public_name, "object": "model", "owned_by": APP_NAME} for row in rows]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    customer, key = customer_from_api_key(authorization, db)
    body = await request.json()
    public_model = str(body.get("model", ""))
    routes = available_routes(db, public_model)
    if not routes:
        raise HTTPException(status_code=404, detail="Model is not enabled")
    model = routes[0].model
    if model.endpoint_type != "chat":
        raise HTTPException(status_code=400, detail="This model must be called through its image endpoint")
    required_balance = estimate_max_charge(body, model)
    limit = consume(key.id, key.rpm_limit, key.tpm_limit, estimate_rate_tokens(body))
    if not limit.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"API key rate limit exceeded. Retry in {limit.retry_after} seconds.",
            headers={"Retry-After": str(limit.retry_after)},
        )
    request_id = uuid.uuid4().hex
    reserve_balance(db, customer.id, required_balance, public_model, request_id)

    if body.get("stream"):
        body["stream_options"] = {**(body.get("stream_options") or {}), "include_usage": True}
        started = time.perf_counter()
        errors: list[str] = []
        selected_route = None
        upstream = None
        client = None
        for route in routes:
            candidate_client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20))
            upstream_body = dict(body)
            upstream_body["model"] = route.upstream_model
            try:
                upstream_request = candidate_client.build_request(
                    "POST",
                    route.provider.base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + decrypt_secret(route.provider.api_key_encrypted), "Content-Type": "application/json"},
                    json=upstream_body,
                )
                candidate = await candidate_client.send(upstream_request, stream=True)
                if candidate.is_success:
                    selected_route, upstream, client = route, candidate, candidate_client
                    mark_success(db, route)
                    break
                error_text = (await candidate.aread()).decode(errors="replace")[:2000]
                await candidate.aclose()
                await candidate_client.aclose()
                mark_failure(db, route, error_text)
                errors.append(f"{route.provider.name}: HTTP {candidate.status_code} {error_text}")
                if candidate.status_code in {400, 422}:
                    release_reserve(db, customer.id, required_balance, public_model, request_id)
                    raise HTTPException(status_code=candidate.status_code, detail="Upstream rejected the request")
            except HTTPException:
                raise
            except Exception as exc:
                await candidate_client.aclose()
                mark_failure(db, route, str(exc))
                errors.append(f"{route.provider.name}: {exc}")
        if not selected_route or not upstream or not client:
            release_reserve(db, customer.id, required_balance, public_model, request_id)
            log_failed_request(
                db,
                customer_id=customer.id,
                api_key_id=key.id,
                model_name=public_model,
                status=502,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=" | ".join(errors),
            )
            raise HTTPException(status_code=502, detail="All provider routes failed")

        async def stream_response():
            buffer = ""
            input_tokens = 0
            output_tokens = 0
            output_chars = 0
            stream_error = None
            try:
                async for chunk in upstream.aiter_bytes():
                    text_chunk = chunk.decode("utf-8", errors="ignore")
                    buffer += text_chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                            usage = event.get("usage") or {}
                            input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", input_tokens)) or input_tokens)
                            output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", output_tokens)) or output_tokens)
                            for choice in event.get("choices") or []:
                                output_chars += len(str((choice.get("delta") or {}).get("content") or ""))
                        except (ValueError, TypeError):
                            pass
                    yield chunk
            except Exception as exc:
                stream_error = str(exc)
                raise
            finally:
                await upstream.aclose()
                await client.aclose()
                with SessionLocal() as billing_db:
                    if stream_error:
                        release_reserve(billing_db, customer.id, required_balance, public_model, request_id)
                        route_row = billing_db.get(ModelRoute, selected_route.id)
                        if route_row:
                            mark_failure(billing_db, route_row, stream_error)
                        log_failed_request(
                            billing_db,
                            customer_id=customer.id,
                            api_key_id=key.id,
                            model_name=public_model,
                            status=502,
                            latency_ms=int((time.perf_counter() - started) * 1000),
                            error=stream_error,
                        )
                    else:
                        if input_tokens <= 0:
                            input_tokens = max(1, estimate_rate_tokens({**body, "max_tokens": 1}) - 1)
                        if output_tokens <= 0 and output_chars:
                            output_tokens = max(1, output_chars // 4)
                        settle_usage(
                            billing_db,
                            customer_id=customer.id,
                            api_key_id=key.id,
                            route_id=selected_route.id,
                            model_name=public_model,
                            request_id=request_id,
                            reserved=required_balance,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            status=upstream.status_code,
                            latency_ms=int((time.perf_counter() - started) * 1000),
                        )

        response_headers = {
            key_name: value
            for key_name, value in upstream.headers.items()
            if key_name.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}
        }
        return StreamingResponse(stream_response(), status_code=upstream.status_code, headers=response_headers, media_type="text/event-stream")

    started = time.perf_counter()
    errors: list[str] = []
    for route in routes:
        upstream_body = dict(body)
        upstream_body["model"] = route.upstream_model
        async with httpx.AsyncClient(timeout=300) as client:
            try:
                upstream = await client.post(
                    route.provider.base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + decrypt_secret(route.provider.api_key_encrypted), "Content-Type": "application/json"},
                    json=upstream_body,
                )
            except Exception as exc:
                mark_failure(db, route, str(exc))
                errors.append(f"{route.provider.name}: {exc}")
                continue
        if not upstream.is_success:
            error_text = upstream.text[:2000]
            mark_failure(db, route, error_text)
            errors.append(f"{route.provider.name}: HTTP {upstream.status_code} {error_text}")
            if upstream.status_code in {400, 422}:
                release_reserve(db, customer.id, required_balance, public_model, request_id)
                log_failed_request(
                    db,
                    customer_id=customer.id,
                    api_key_id=key.id,
                    model_name=public_model,
                    status=upstream.status_code,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error=error_text,
                )
                raise HTTPException(status_code=upstream.status_code, detail="Upstream rejected the request")
            continue
        mark_success(db, route)
        payload = upstream.json()
        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        settle_usage(
            db,
            customer_id=customer.id,
            api_key_id=key.id,
            route_id=route.id,
            model_name=public_model,
            request_id=request_id,
            reserved=required_balance,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status=upstream.status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return JSONResponse(payload, status_code=upstream.status_code)

    release_reserve(db, customer.id, required_balance, public_model, request_id)
    log_failed_request(
        db,
        customer_id=customer.id,
        api_key_id=key.id,
        model_name=public_model,
        status=502,
        latency_ms=int((time.perf_counter() - started) * 1000),
        error=" | ".join(errors),
    )
    raise HTTPException(status_code=502, detail="All provider routes failed")


@app.post("/v1/images/generations")
async def image_generations(request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    customer, key = customer_from_api_key(authorization, db)
    body = await request.json()
    public_model = str(body.get("model", ""))
    routes = available_routes(db, public_model)
    if not routes:
        raise HTTPException(status_code=404, detail="Model is not enabled")
    model = routes[0].model
    if model.endpoint_type != "image":
        raise HTTPException(status_code=400, detail="This model must be called through chat completions")
    units = min(max(int(body.get("n", 1) or 1), 1), 10)
    required_balance = money(model.unit_price * units)
    limit = consume(key.id, key.rpm_limit, key.tpm_limit, units)
    if not limit.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"API key rate limit exceeded. Retry in {limit.retry_after} seconds.",
            headers={"Retry-After": str(limit.retry_after)},
        )
    request_id = uuid.uuid4().hex
    reserve_balance(db, customer.id, required_balance, public_model, request_id)
    started = time.perf_counter()
    errors: list[str] = []
    for route in routes:
        upstream_body = dict(body)
        upstream_body["model"] = route.upstream_model
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                upstream = await client.post(
                    route.provider.base_url + "/images/generations",
                    headers={"Authorization": "Bearer " + decrypt_secret(route.provider.api_key_encrypted), "Content-Type": "application/json"},
                    json=upstream_body,
                )
        except Exception as exc:
            mark_failure(db, route, str(exc))
            errors.append(f"{route.provider.name}: {exc}")
            continue
        if not upstream.is_success:
            error_text = upstream.text[:2000]
            mark_failure(db, route, error_text)
            errors.append(f"{route.provider.name}: HTTP {upstream.status_code} {error_text}")
            if upstream.status_code in {400, 422}:
                release_reserve(db, customer.id, required_balance, public_model, request_id)
                raise HTTPException(status_code=upstream.status_code, detail="Upstream rejected the request")
            continue
        mark_success(db, route)
        settle_units(
            db,
            customer_id=customer.id,
            api_key_id=key.id,
            route_id=route.id,
            model_name=public_model,
            request_id=request_id,
            reserved=required_balance,
            units=units,
            status=upstream.status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return JSONResponse(upstream.json(), status_code=upstream.status_code)
    release_reserve(db, customer.id, required_balance, public_model, request_id)
    log_failed_request(
        db,
        customer_id=customer.id,
        api_key_id=key.id,
        model_name=public_model,
        status=502,
        latency_ms=int((time.perf_counter() - started) * 1000),
        error=" | ".join(errors),
    )
    raise HTTPException(status_code=502, detail="All provider routes failed")
