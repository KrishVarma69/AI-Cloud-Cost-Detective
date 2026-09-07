"""Amazon RDS for PostgreSQL access layer (see prompts/03-rds-postgres-websocket.md).

Uses a single asyncpg pool. Tables are created on startup if missing.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analyses (
    id                TEXT PRIMARY KEY,
    user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    region            TEXT NOT NULL,
    resource_group    TEXT,
    account_id        TEXT,
    resources_scanned INTEGER NOT NULL DEFAULT 0,
    issues_found      INTEGER NOT NULL DEFAULT 0,
    monthly_cost      NUMERIC,
    estimated_savings TEXT,
    analysis_result   JSONB,
    status            TEXT NOT NULL DEFAULT 'running',
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS analyses_user_created_idx
    ON analyses (user_id, created_at DESC);

-- Migration for databases created before multi-account support.
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS account_id TEXT;
"""


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at your Amazon RDS for PostgreSQL "
            "instance (see backend/.env.example)."
        )
    # asyncpg wants ssl=... as a kwarg, not the libpq sslmode= query param.
    return dsn


async def init_db() -> None:
    global _pool
    dsn = _dsn()
    ssl = None
    if "sslmode=require" in dsn or "sslmode=verify" in dsn:
        ssl = True
        dsn = dsn.split("?")[0]
    _pool = await asyncpg.create_pool(dsn=dsn, ssl=ssl, min_size=1, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute(_SCHEMA)


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _require_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialised")
    return _pool


# ── users ────────────────────────────────────────────────────────────────────
async def create_user(email: str, password_hash: str) -> asyncpg.Record:
    pool = _require_pool()
    return await pool.fetchrow(
        "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING id, email, created_at",
        email.lower(),
        password_hash,
    )


async def get_user_by_email(email: str) -> Optional[asyncpg.Record]:
    pool = _require_pool()
    return await pool.fetchrow(
        "SELECT id, email, password_hash, created_at FROM users WHERE email = $1",
        email.lower(),
    )


async def get_user_by_id(user_id: int) -> Optional[asyncpg.Record]:
    pool = _require_pool()
    return await pool.fetchrow(
        "SELECT id, email, created_at FROM users WHERE id = $1", user_id
    )


# ── analyses ─────────────────────────────────────────────────────────────────
async def create_analysis(
    analysis_id: str,
    user_id: int,
    region: str,
    resource_group: str | None,
    account_id: str | None = None,
) -> None:
    pool = _require_pool()
    await pool.execute(
        """INSERT INTO analyses (id, user_id, region, resource_group, account_id, status)
           VALUES ($1, $2, $3, $4, $5, 'running')""",
        analysis_id,
        user_id,
        region,
        resource_group,
        account_id,
    )


async def complete_analysis(
    analysis_id: str,
    *,
    resources_scanned: int,
    issues_found: int,
    monthly_cost: float | None,
    estimated_savings: str,
    analysis_result: dict[str, Any],
) -> None:
    pool = _require_pool()
    await pool.execute(
        """UPDATE analyses
              SET resources_scanned = $2,
                  issues_found       = $3,
                  monthly_cost       = $4,
                  estimated_savings  = $5,
                  analysis_result    = $6::jsonb,
                  status             = 'complete',
                  error              = NULL
            WHERE id = $1""",
        analysis_id,
        resources_scanned,
        issues_found,
        monthly_cost,
        estimated_savings,
        json.dumps(analysis_result, default=str),
    )


async def fail_analysis(analysis_id: str, message: str) -> None:
    pool = _require_pool()
    await pool.execute(
        "UPDATE analyses SET status = 'failed', error = $2 WHERE id = $1",
        analysis_id,
        message,
    )


async def list_analyses(user_id: int) -> list[dict]:
    pool = _require_pool()
    rows = await pool.fetch(
        """SELECT id, region, resource_group, account_id, resources_scanned, issues_found,
                  monthly_cost, estimated_savings, status, error, created_at
             FROM analyses
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 100""",
        user_id,
    )
    return [_row_to_dict(r) for r in rows]


async def get_analysis(analysis_id: str, user_id: int) -> Optional[dict]:
    pool = _require_pool()
    row = await pool.fetchrow(
        """SELECT id, region, resource_group, account_id, resources_scanned, issues_found,
                  monthly_cost, estimated_savings, analysis_result, status, error, created_at
             FROM analyses
            WHERE id = $1 AND user_id = $2""",
        analysis_id,
        user_id,
    )
    if not row:
        return None
    d = _row_to_dict(row)
    result = row["analysis_result"]
    if isinstance(result, str):
        result = json.loads(result)
    d["analysis_result"] = result
    return d


async def analysis_exists_for_user(analysis_id: str, user_id: int) -> bool:
    pool = _require_pool()
    val = await pool.fetchval(
        "SELECT 1 FROM analyses WHERE id = $1 AND user_id = $2",
        analysis_id,
        user_id,
    )
    return val is not None


def _row_to_dict(r: asyncpg.Record) -> dict:
    d = dict(r)
    if d.get("created_at") is not None:
        d["created_at"] = d["created_at"].isoformat()
    if d.get("monthly_cost") is not None:
        d["monthly_cost"] = float(d["monthly_cost"])
    return d
