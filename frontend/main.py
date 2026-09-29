"""Minimal FastAPI proxy for a deployed A2A agent (Agent Runtime, agents-cli 1.1.0+).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over the A2A protocol, returning replies as
structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.
"""

import json
import os
import uuid

import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
import importlib

_a2a_types = importlib.import_module("a2a.types")
AgentCard = getattr(_a2a_types, "AgentCard", None)
Message = getattr(_a2a_types, "Message", None)
Part = getattr(_a2a_types, "Part", None)
Role = getattr(_a2a_types, "Role", None)
TaskArtifactUpdateEvent = getattr(_a2a_types, "TaskArtifactUpdateEvent", None)
TextPart = getattr(_a2a_types, "TextPart", None)
TransportProtocol = getattr(_a2a_types, "TransportProtocol", None)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

RESOURCE = os.environ.get(
    "AGENT_ENGINE_RESOURCE_NAME",
    "projects/415074386920/locations/us-east1/reasoningEngines/4487782053093310464",
)
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"
_A2UI_MIME = "application/json+a2ui"

_creds = None


def _get_creds():
    global _creds
    if _creds is None:
        _creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    return _creds


def _auth_headers() -> dict[str, str]:
    creds = _get_creds()
    creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


_contexts: dict[str, str] = {}
_card: AgentCard | None = None


def _parse_agent_card(data: dict, text: str) -> AgentCard:
    if hasattr(AgentCard, "model_validate"):
        try:
            return AgentCard.model_validate(data)
        except Exception:
            pass
    if hasattr(AgentCard, "model_validate_json"):
        try:
            return AgentCard.model_validate_json(text)
        except Exception:
            pass
    fields = getattr(AgentCard, "__fields__", None) or getattr(
        AgentCard, "__annotations__", {}
    )
    kwargs = {k: v for k, v in data.items() if k in fields}
    return AgentCard(**kwargs)


async def _get_card(client: httpx.AsyncClient) -> AgentCard:
    global _card
    if _card is None:
        resp = await client.get(A2A_CARD_URL)
        resp.raise_for_status()
        data = resp.json()
        data["url"] = A2A_BASE
        if "preferredTransport" in data:
            data["preferred_transport"] = data.pop("preferredTransport")
        if TransportProtocol is not None and hasattr(TransportProtocol, "jsonrpc"):
            data["preferred_transport"] = TransportProtocol.jsonrpc
        card = _parse_agent_card(data, json.dumps(data))
        try:
            setattr(card, "url", A2A_BASE)
        except Exception:
            pass
        if TransportProtocol is not None and hasattr(TransportProtocol, "jsonrpc"):
            try:
                setattr(card, "preferred_transport", TransportProtocol.jsonrpc)
            except Exception:
                pass
        _card = card
    return _card


def _extract_parts(parts: list) -> list[dict]:
    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        if getattr(root, "text", None):
            out.append({"kind": "text", "text": root.text})
        elif getattr(root, "data", None) is not None:
            meta = getattr(root, "metadata", None) or {}
            mime = meta.get("mimeType") if isinstance(meta, dict) else None
            if mime == _A2UI_MIME:
                out.append({"kind": "a2ui", "data": root.data})
        else:
            file_obj = getattr(root, "file", None)
            uri = getattr(file_obj, "uri", None) if file_obj else None
            if uri:
                out.append({"kind": "text", "text": uri})
    return out


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        card = await _get_card(client)
        if TransportProtocol is not None and hasattr(TransportProtocol, "jsonrpc"):
            try:
                setattr(card, "preferred_transport", TransportProtocol.jsonrpc)
            except Exception:
                pass
        factory = ClientFactory(ClientConfig(httpx_client=client))
        a2a_client = factory.create(card)

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            parts=[Part(root=TextPart(text=message))],
            context_id=_contexts.get(user_id),
        )

        last_task = None
        got_artifact_update = False
        async for event in a2a_client.send_message(msg):
            if not isinstance(event, tuple):
                continue
            task, update = event
            if task is not None:
                last_task = task
                if getattr(task, "context_id", None):
                    _contexts[user_id] = task.context_id
            if isinstance(update, TaskArtifactUpdateEvent):
                got_artifact_update = True
                parts.extend(_extract_parts(update.artifact.parts))

        if not got_artifact_update and last_task is not None:
            for artifact in getattr(last_task, "artifacts", None) or []:
                parts.extend(_extract_parts(artifact.parts))

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
