"""C6 QnA WebSocket service.

The route in `api/routes/graphs.py` only owns FastAPI plumbing (path,
query params, schema). All session orchestration — JWT decoding,
graph lookup, QnaSession lifecycle, streaming protocol — lives here.
"""

from __future__ import annotations

import json
import logging
import os
import uuid

import jwt
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from db.database import get_session
from db.entities import Graph
from playground import QnaSession

logger = logging.getLogger("meridian.orchestrator.qna_chat")

_JWT_SECRET = os.environ.get("JWT_SECRET", "meridian-dev-secret-change-in-prod")
_JWT_ALGORITHM = "HS256"

# WS close codes (4000-4999 = application range)
_WS_INVALID_TOKEN = 4401
_WS_NOT_FOUND = 4404
_WS_NOT_READY = 4409
_WS_INTERNAL = 1011


def _decode_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.InvalidTokenError:
        return None


def _load_graph_context(
    graph_id: str, user_id: str
) -> tuple[dict, str, str] | None:
    """Return `(graph_data, repo_url, branch)` or `None` if the graph is
    missing / not owned / not ready."""
    with get_session() as session:
        row = session.execute(
            select(Graph).where(Graph.graph_id == graph_id, Graph.user_id == user_id)
        ).scalar_one_or_none()
        if row is None or row.graph_data is None:
            return None
        if row.status != "READY":
            return ("__not_ready__", row.status, "")  # type: ignore[return-value]

        return row.graph_data, row.repo_url, row.branch


async def _stream_answer(websocket: WebSocket, qna: QnaSession, prompt: str) -> None:
    """Stream one assistant turn over the WS. Errors are surfaced to the
    client without closing the socket — the user can ask another question."""
    try:
        async for delta in qna.ask(prompt):
            await websocket.send_text(json.dumps({"type": "delta", "text": delta}))

        done_payload: dict = {"type": "done"}
        r = qna.last_result
        if r is not None:
            done_payload["duration_ms"] = r.duration_ms
            if r.total_cost_usd is not None:
                done_payload["cost_usd"] = round(r.total_cost_usd, 6)
            if r.usage:
                done_payload["input_tokens"]  = r.usage.get("input_tokens")
                done_payload["output_tokens"] = r.usage.get("output_tokens")
        await websocket.send_text(json.dumps(done_payload))
    except Exception as exc:
        logger.exception("playground stream error")
        await websocket.send_text(
            json.dumps({"type": "error", "message": str(exc)})
        )


async def run_playground_session(
    websocket: WebSocket,
    graph_id: str,
    *,
    token: str,
    initial_query: str | None,
) -> None:
    """End-to-end handler for `WS /playground/{graph_id}`.

    Protocol (server → client):
        {"type": "ready"}
        {"type": "delta", "text": "..."}
        {"type": "done"}
        {"type": "error", "message": "..."}

    Inbound (client → server): JSON `{"query": "..."}` per turn (or raw text).

    Session lifetime == WS lifetime: closing the socket discards history.
    """
    user_id = _decode_token(token)
    if not user_id:
        await websocket.close(code=_WS_INVALID_TOKEN, reason="invalid token")
        return

    ctx = _load_graph_context(graph_id, user_id)
    if ctx is None:
        await websocket.close(code=_WS_NOT_FOUND, reason="graph not found")
        return
    if ctx[0] == "__not_ready__":
        await websocket.close(code=_WS_NOT_READY, reason=f"graph not ready (status={ctx[1]})")
        return

    graph_data, repo_url, branch = ctx
    await websocket.accept()

    session_id = f"qna:{graph_id}:{uuid.uuid4().hex}"

    try:
        async with QnaSession(
            session_id,
            graph_data,
            repo_url,
            branch,
        ) as qna:
            await websocket.send_text(json.dumps({"type": "ready"}))

            if initial_query:
                await _stream_answer(websocket, qna, initial_query)

            while True:
                raw = await websocket.receive_text()
                try:
                    payload = json.loads(raw)
                    user_query = (payload.get("query") or "").strip()
                except (json.JSONDecodeError, AttributeError):
                    user_query = raw.strip()
                if not user_query:
                    continue
                await _stream_answer(websocket, qna, user_query)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.exception("playground ws error")
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "message": str(exc)})
            )
        finally:
            await websocket.close(code=_WS_INTERNAL)
