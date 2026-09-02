"""FastAPI entrypoint for the AI Cloud Cost Detective (AWS).

Wires together: custom JWT auth, the AWS CLI scanner, the OpenAI analyzer,
RDS PostgreSQL persistence, and a WebSocket that streams live progress.
"""
from __future__ import annotations

import asyncio
import os
import uuid
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
from aws_scanner import AwsError, list_regions, list_resource_groups, scan_region

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
JWT_TTL = timedelta(days=7)
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")


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
    await db.init_db()
    yield
    await db.close_db()


app = FastAPI(title="AI Cloud Cost Detective (AWS)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer = HTTPBearer(auto_error=True)


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────
def _make_token(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "email": email, "iat": now, "exp": now + JWT_TTL}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict[str, Any]:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    user = await db.get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return {"id": user["id"], "email": user["email"]}


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AnalyzeRequest(BaseModel):
    region: str
    resource_group: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/auth/signup")
async def signup(body: Credentials):
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


# ─────────────────────────────────────────────────────────────────────────────
# Analyze
# ─────────────────────────────────────────────────────────────────────────────
async def _run_analysis(analysis_id: str, user_id: int, region: str, resource_group: str | None) -> None:
    loop = asyncio.get_running_loop()

    def progress(stage: str, message: str, pct: int) -> None:
        asyncio.run_coroutine_threadsafe(
            hub.publish(analysis_id, {"stage": stage, "message": message, "pct": pct}),
            loop,
        )

    try:
        await hub.publish(analysis_id, {"stage": "start", "message": f"Scanning {region}...", "pct": 5})
        scan = await asyncio.to_thread(scan_region, region, resource_group, progress)

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


@app.post("/api/analyze")
async def start_analyze(body: AnalyzeRequest, user: dict = Depends(current_user)):
    analysis_id = uuid.uuid4().hex
    await db.create_analysis(analysis_id, user["id"], body.region, body.resource_group)
    asyncio.create_task(_run_analysis(analysis_id, user["id"], body.region, body.resource_group))
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
