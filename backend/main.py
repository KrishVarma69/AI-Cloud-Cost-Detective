"""FastAPI entrypoint for the AI Cloud Cost Detective (AWS).

Wires together: custom JWT auth, the AWS CLI scanner, the LLM analyzer
(OpenAI or Amazon Bedrock), RDS PostgreSQL persistence, and a WebSocket that
streams live progress.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

import db
from ai_analyzer import AnalyzerError, analyze
from aws_scanner import (
    AwsError,
    list_accounts,
    list_regions,
    list_resource_groups,
    scan_region,
)

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

_DEFAULT_JWT_SECRET = "dev-secret-change-me"
JWT_SECRET = os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET)
JWT_ALG = "HS256"
JWT_TTL = timedelta(days=int(os.getenv("JWT_TTL_DAYS", "7")))

# Comma-separated list of browser origins allowed by CORS.
FRONTEND_ORIGINS = [
    o.strip()
    for o in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").split(",")
    if o.strip()
]

# Self-service signup can be turned off (provision users manually) and/or
# restricted to a set of email domains.
ALLOW_SIGNUP = os.getenv("ALLOW_SIGNUP", "true").strip().lower() in {"1", "true", "yes", "on"}
SIGNUP_ALLOWED_DOMAINS = {
    d.strip().lower().lstrip("@")
    for d in os.getenv("SIGNUP_ALLOWED_DOMAINS", "").split(",")
    if d.strip()
}

ANALYZE_RATE_LIMIT_PER_HOUR = int(os.getenv("ANALYZE_RATE_LIMIT_PER_HOUR", "20"))
ANALYZE_MAX_CONCURRENT_PER_USER = int(os.getenv("ANALYZE_MAX_CONCURRENT_PER_USER", "2"))


def _check_production_config() -> None:
    """Fail fast if APP_ENV=production but dev defaults are still in place."""
    if APP_ENV != "production":
        return
    problems: list[str] = []
    if JWT_SECRET == _DEFAULT_JWT_SECRET or len(JWT_SECRET) < 32:
        problems.append("JWT_SECRET must be a random string of at least 32 characters")
    if any("localhost" in o or "127.0.0.1" in o for o in FRONTEND_ORIGINS):
        problems.append("FRONTEND_ORIGIN still contains a localhost entry")
    if problems:
        raise RuntimeError(
            "Refusing to start with APP_ENV=production: " + "; ".join(problems)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Progress hub — buffers messages so a slightly-late WebSocket never misses one
# ─────────────────────────────────────────────────────────────────────────────
class ProgressHub:
    def __init__(self) -> None:
        self._backlog: dict[str, list[dict]] = {}
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._done: set[str] = set()

    async def publish(self, pid: str, message: dict) -> None:
        self._backlog.setdefault(pid, []).append(message)
        for q in list(self._subs.get(pid, ())):
            q.put_nowait(message)

    def finish(self, pid: str) -> None:
        self._done.add(pid)
        for q in list(self._subs.get(pid, ())):
            q.put_nowait({"type": "__close__"})

    async def stream(self, pid: str, websocket: WebSocket) -> None:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(pid, set()).add(q)
        try:
            for msg in list(self._backlog.get(pid, ())):
                await websocket.send_json(msg)
            if pid in self._done:
                return
            while True:
                msg = await q.get()
                if msg.get("type") == "__close__":
                    return
                await websocket.send_json(msg)
        finally:
            subs = self._subs.get(pid)
            if subs:
                subs.discard(q)

    def cleanup(self, pid: str) -> None:
        self._backlog.pop(pid, None)
        self._subs.pop(pid, None)
        self._done.discard(pid)


hub = ProgressHub()


@asynccontextmanager
async def lifespan(_: FastAPI):
    _check_production_config()
    await db.init_db()
    yield
    await db.close_db()


app = FastAPI(title="AI Cloud Cost Detective (AWS)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer = HTTPBearer(auto_error=True)


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting — per user, per backend process
# ─────────────────────────────────────────────────────────────────────────────
class RateLimiter:
    """Caps analyses per user: a rolling hourly count and a concurrency ceiling.

    NOTE: state lives in this process only. If you run more than one backend
    replica, move this to Redis (or enforce it with a DB query) instead.
    """

    def __init__(self, per_hour: int, max_concurrent: int) -> None:
        self._per_hour = per_hour
        self._max_concurrent = max_concurrent
        self._starts: dict[int, deque[float]] = defaultdict(deque)
        self._running: dict[int, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: int) -> None:
        now = time.monotonic()
        async with self._lock:
            recent = self._starts[user_id]
            while recent and now - recent[0] > 3600:
                recent.popleft()
            if self._running[user_id] >= self._max_concurrent:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"You already have {self._max_concurrent} analyses running. "
                    "Wait for one to finish.",
                )
            if len(recent) >= self._per_hour:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Rate limit reached ({self._per_hour} analyses/hour). Try again later.",
                )
            recent.append(now)
            self._running[user_id] += 1

    async def release(self, user_id: int) -> None:
        async with self._lock:
            if self._running[user_id] > 0:
                self._running[user_id] -= 1


limiter = RateLimiter(ANALYZE_RATE_LIMIT_PER_HOUR, ANALYZE_MAX_CONCURRENT_PER_USER)


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────
class TokenError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _make_token(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "email": email, "iat": now, "exp": now + JWT_TTL}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc


async def _user_from_token(token: str) -> dict[str, Any]:
    """Resolve a raw JWT string to a user dict. Used by HTTP deps and the WS."""
    if not token:
        raise TokenError("Missing token")
    payload = _decode_token(token)
    user = await db.get_user_by_id(int(payload["sub"]))
    if not user:
        raise TokenError("User no longer exists")
    return {"id": user["id"], "email": user["email"]}


async def current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict[str, Any]:
    try:
        return await _user_from_token(creds.credentials)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.detail)


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AnalyzeRequest(BaseModel):
    region: str
    resource_group: Optional[str] = None
    account_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/auth/signup")
async def signup(body: Credentials):
    if not ALLOW_SIGNUP:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Self-service signup is disabled. Ask an administrator to create your account.",
        )
    if SIGNUP_ALLOWED_DOMAINS:
        domain = body.email.split("@")[-1].lower()
        if domain not in SIGNUP_ALLOWED_DOMAINS:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "That email domain is not allowed to sign up.",
            )
    if await db.get_user_by_email(body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists")
    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user = await db.create_user(body.email, pw_hash)
    return {"token": _make_token(user["id"], user["email"]), "email": user["email"]}


@app.post("/api/auth/login")
async def login(body: Credentials):
    user = await db.get_user_by_email(body.email)
    if not user or not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return {"token": _make_token(user["id"], user["email"]), "email": user["email"]}


@app.get("/api/me")
async def me(user: dict = Depends(current_user)):
    return user


# ─────────────────────────────────────────────────────────────────────────────
# AWS listings
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/regions")
async def regions(_: dict = Depends(current_user)):
    try:
        return {"regions": await asyncio.to_thread(list_regions)}
    except AwsError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@app.get("/api/resource-groups")
async def resource_groups(_: dict = Depends(current_user)):
    try:
        return {"resource_groups": await asyncio.to_thread(list_resource_groups)}
    except AwsError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@app.get("/api/accounts")
async def accounts(_: dict = Depends(current_user)):
    return {"accounts": list_accounts()}


# ─────────────────────────────────────────────────────────────────────────────
# Analyze
# ─────────────────────────────────────────────────────────────────────────────
async def _run_analysis(
    analysis_id: str,
    user_id: int,
    region: str,
    resource_group: str | None,
    account_id: str | None = None,
) -> None:
    loop = asyncio.get_running_loop()

    def progress(stage: str, message: str, pct: int) -> None:
        asyncio.run_coroutine_threadsafe(
            hub.publish(analysis_id, {"stage": stage, "message": message, "pct": pct}),
            loop,
        )

    try:
        await hub.publish(analysis_id, {"stage": "start", "message": f"Scanning {region}...", "pct": 5})
        scan = await asyncio.to_thread(
            scan_region, region, resource_group, progress, account_id
        )

        await hub.publish(analysis_id, {"stage": "ai", "message": "Analyzing costs with AI...", "pct": 65})
        report = await asyncio.to_thread(analyze, scan)

        await hub.publish(analysis_id, {"stage": "store", "message": "Storing results...", "pct": 90})
        cost = scan.get("cost") or {}
        monthly_cost = cost.get("current_month_to_date") if cost.get("available") else None
        full_result = {"scan": scan, "report": report}
        await db.complete_analysis(
            analysis_id,
            resources_scanned=scan.get("resource_count", 0),
            issues_found=len(report.get("issues", [])),
            monthly_cost=monthly_cost,
            estimated_savings=report.get("estimated_monthly_savings", "$0"),
            analysis_result=full_result,
        )

        await hub.publish(
            analysis_id,
            {
                "stage": "complete",
                "message": "Analysis complete",
                "pct": 100,
                "result": {**full_result, "id": analysis_id},
            },
        )
    except (AwsError, AnalyzerError) as exc:
        await db.fail_analysis(analysis_id, str(exc))
        await hub.publish(analysis_id, {"stage": "error", "message": str(exc), "pct": 100})
    except Exception as exc:  # noqa: BLE001
        await db.fail_analysis(analysis_id, f"Unexpected error: {exc}")
        await hub.publish(analysis_id, {"stage": "error", "message": f"Unexpected error: {exc}", "pct": 100})
    finally:
        hub.finish(analysis_id)
        await limiter.release(user_id)


@app.post("/api/analyze")
async def start_analyze(body: AnalyzeRequest, user: dict = Depends(current_user)):
    account_id = body.account_id or None
    if account_id and account_id not in {a["id"] for a in list_accounts()}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown account_id")

    await limiter.acquire(user["id"])
    analysis_id = uuid.uuid4().hex
    try:
        await db.create_analysis(
            analysis_id, user["id"], body.region, body.resource_group, account_id
        )
    except Exception:
        await limiter.release(user["id"])
        raise
    asyncio.create_task(
        _run_analysis(analysis_id, user["id"], body.region, body.resource_group, account_id)
    )
    return {"analysis_id": analysis_id}


@app.get("/api/history")
async def history(user: dict = Depends(current_user)):
    return {"analyses": await db.list_analyses(user["id"])}


@app.get("/api/analysis/{analysis_id}")
async def analysis_detail(analysis_id: str, user: dict = Depends(current_user)):
    row = await db.get_analysis(analysis_id, user["id"])
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return row


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket progress
# ─────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws/progress/{analysis_id}")
async def ws_progress(websocket: WebSocket, analysis_id: str):
    await websocket.accept()

    # The browser can't set an Authorization header on a WebSocket, so the token
    # arrives as a query param (?token=...). Validate it, and confirm the caller
    # owns this analysis before streaming anything.
    token = websocket.query_params.get("token", "")
    try:
        user = await _user_from_token(token)
    except TokenError as exc:
        await websocket.send_json(
            {"stage": "error", "message": f"Unauthorized: {exc.detail}", "pct": 100}
        )
        await websocket.close(code=4401)
        return

    if not await db.analysis_exists_for_user(analysis_id, user["id"]):
        await websocket.send_json(
            {"stage": "error", "message": "Analysis not found", "pct": 100}
        )
        await websocket.close(code=4404)
        return

    try:
        await hub.stream(analysis_id, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass


@app.get("/health")
async def health():
    return {"ok": True}
