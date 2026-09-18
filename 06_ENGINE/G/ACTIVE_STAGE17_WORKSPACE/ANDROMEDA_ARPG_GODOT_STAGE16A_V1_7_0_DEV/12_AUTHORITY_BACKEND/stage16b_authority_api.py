"""Stage16B authority HTTP surface.

Thin FastAPI shell over ``Stage16BAuthorityAdapter``. It parses requests, calls one
adapter method and serialises the answer. No gameplay logic lives here.

Transport rule: ``andromeda_bridge.gd`` treats any non-200 response as a transport
failure and enters reconnect backoff. Domain rejections are therefore returned as
HTTP 200 with ``{"status": "REJECTED", ...}``.

Launch (single worker — one process owns the authoritative SQLite world):

    C:/Users/thall/ANDROMEDA_PRODUCT/.venv/Scripts/python.exe -m uvicorn \
        stage16b_authority_api:app --host 127.0.0.1 --port 8000 --workers 1
"""

from __future__ import annotations

import json
import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from andromeda_authority_adapter import Stage16BAuthorityAdapter

ADAPTER: Stage16BAuthorityAdapter | None = None
BOOT_ERROR: str = ""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global ADAPTER, BOOT_ERROR
    try:
        ADAPTER = Stage16BAuthorityAdapter()
    except Exception as exc:  # boot failure must be visible on /health, not a crash loop
        BOOT_ERROR = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    yield
    if ADAPTER is not None:
        ADAPTER.close()
        ADAPTER = None


app = FastAPI(title="Andromeda Stage16B Authority Adapter", lifespan=lifespan)


def _ok(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=200, content=payload)


def _unavailable() -> JSONResponse:
    return _ok(
        {
            "status": "FAIL",
            "reason": "AUTHORITY_NOT_BOOTED",
            "detail": BOOT_ERROR,
            "service": Stage16BAuthorityAdapter.SERVICE,
            "server_authoritative": True,
        }
    )


def _internal(exc: Exception) -> JSONResponse:
    traceback.print_exc()
    return _ok(
        {
            "status": "FAIL",
            "reason": "INTERNAL_ADAPTER_ERROR",
            "detail": f"{type(exc).__name__}: {exc}",
            "adapter_authority": Stage16BAuthorityAdapter.ADAPTER_AUTHORITY,
        }
    )


async def _body(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        raw = await request.body()
        if not raw:
            return {}, None
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        return None, _ok(
            {
                "status": "REJECTED",
                "reason": "INVALID_JSON_BODY",
                "adapter_authority": Stage16BAuthorityAdapter.ADAPTER_AUTHORITY,
            }
        )
    if not isinstance(parsed, dict):
        return None, _ok(
            {
                "status": "REJECTED",
                "reason": "INVALID_JSON_BODY",
                "adapter_authority": Stage16BAuthorityAdapter.ADAPTER_AUTHORITY,
            }
        )
    return parsed, None


def _session_from_query(request: Request) -> str:
    return (
        request.query_params.get("session_ref")
        or request.headers.get("x-andromeda-session")
        or ""
    ).strip()


@app.get("/health")
def health() -> JSONResponse:
    if ADAPTER is None:
        return _unavailable()
    try:
        return _ok(ADAPTER.health())
    except Exception as exc:
        return _internal(exc)


@app.post("/session/bind")
async def session_bind(request: Request) -> JSONResponse:
    if ADAPTER is None:
        return _unavailable()
    body, error = await _body(request)
    if error is not None:
        return error
    try:
        return _ok(ADAPTER.bind_session(body.get("session_ref")))
    except Exception as exc:
        return _internal(exc)


@app.post("/session/revoke")
async def session_revoke(request: Request) -> JSONResponse:
    if ADAPTER is None:
        return _unavailable()
    body, error = await _body(request)
    if error is not None:
        return error
    try:
        return _ok(ADAPTER.revoke_session(body.get("session_ref")))
    except Exception as exc:
        return _internal(exc)


@app.post("/session/resync")
async def session_resync(request: Request) -> JSONResponse:
    if ADAPTER is None:
        return _unavailable()
    body, error = await _body(request)
    if error is not None:
        return error
    try:
        return _ok(
            ADAPTER.resync(
                body.get("session_ref"),
                body.get("last_snapshot_sequence"),
                body.get("last_snapshot_id"),
            )
        )
    except Exception as exc:
        return _internal(exc)


@app.get("/snapshot")
def snapshot(request: Request) -> JSONResponse:
    if ADAPTER is None:
        return _unavailable()
    try:
        return _ok(ADAPTER.snapshot(_session_from_query(request)))
    except Exception as exc:
        return _internal(exc)


@app.post("/command")
async def command(request: Request) -> JSONResponse:
    if ADAPTER is None:
        return _unavailable()
    body, error = await _body(request)
    if error is not None:
        return error
    try:
        return _ok(ADAPTER.command(body))
    except Exception as exc:
        return _internal(exc)
