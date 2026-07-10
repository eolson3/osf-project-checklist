from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

APP_NAME = "OSF Project Checklist"
OSF_API_BASE = os.getenv("OSF_API_BASE", "https://api.osf.io/v2").rstrip("/")
OSF_AUTHORIZE_URL = os.getenv(
    "OSF_AUTHORIZE_URL", "https://accounts.osf.io/oauth2/authorize"
)
OSF_TOKEN_URL = os.getenv(
    "OSF_TOKEN_URL", "https://accounts.osf.io/oauth2/token"
)
OSF_CLIENT_ID = os.getenv("OSF_CLIENT_ID", "")
OSF_CLIENT_SECRET = os.getenv("OSF_CLIENT_SECRET", "")
OSF_REDIRECT_URI = os.getenv("OSF_REDIRECT_URI", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
OSF_SCOPE = os.getenv("OSF_SCOPE", "osf.full_read")
REQUEST_TIMEOUT = 60
MAX_RETRIES = 5

app = FastAPI(title=APP_NAME)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_urlsafe(48)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    https_only=os.getenv("COOKIE_HTTPS_ONLY", "true").lower() == "true",
    same_site="lax",
    max_age=60 * 60 * 8,
)


def token_cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(SESSION_SECRET.encode()).digest())
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return token_cipher().encrypt(token.encode()).decode()


def decrypt_token(value: str) -> str | None:
    try:
        return token_cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def configured() -> bool:
    return all((OSF_CLIENT_ID, OSF_CLIENT_SECRET, OSF_REDIRECT_URI))


def api_get(url: str, token: str, params: dict[str, Any] | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.api+json",
        "User-Agent": "OSF-Project-Checklist/1.0",
    }
    last_error = ""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            last_error = str(exc)
            time.sleep(min(2**attempt, 16))
            continue

        if response.status_code in (429, 500, 502, 503, 504):
            last_error = f"HTTP {response.status_code}"
            retry_after = response.headers.get("Retry-After")
            try:
                delay = int(retry_after) if retry_after else min(2**attempt, 16)
            except ValueError:
                delay = min(2**attempt, 16)
            time.sleep(delay)
            continue

        if response.status_code == 401:
            raise RuntimeError("Your OSF authorization has expired. Please reconnect.")
        if response.status_code == 403:
            raise RuntimeError("OSF denied access to the requested content.")
        if not response.ok:
            raise RuntimeError(
                f"OSF returned HTTP {response.status_code}: {response.text[:400]}"
            )
        return response.json()

    raise RuntimeError(f"Could not reach OSF after several attempts: {last_error}")


def relation_id(relationships: dict, name: str) -> str | None:
    data = (relationships.get(name) or {}).get("data")
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"]).lower()
    return None


def parse_node(item: dict) -> dict:
    attrs = item.get("attributes") or {}
    rels = item.get("relationships") or {}
    links = item.get("links") or {}
    guid = str(item.get("id", "")).lower()
    return {
        "guid": guid,
        "title": attrs.get("title") or f"Untitled node {guid}",
        "public": bool(attrs.get("public")),
        "category": (attrs.get("category") or "").replace("_", " ").title(),
        "modified": attrs.get("date_modified") or "",
        "url": links.get("html") or f"https://osf.io/{guid}/",
        "parent_guid": relation_id(rels, "parent"),
        "children": [],
    }


def fetch_account_and_nodes(token: str) -> tuple[str, list[dict]]:
    me = api_get(f"{OSF_API_BASE}/users/me/", token)
    me_data = me.get("data") or {}
    name = (me_data.get("attributes") or {}).get("full_name") or me_data.get("id")

    nodes: list[dict] = []
    url: str | None = f"{OSF_API_BASE}/users/me/nodes/"
    params: dict[str, Any] | None = {"page[size]": 100}

    while url:
        payload = api_get(url, token, params=params)
        nodes.extend(payload.get("data") or [])
        next_url = (payload.get("links") or {}).get("next")
        if isinstance(next_url, dict):
            next_url = next_url.get("href")
        url = next_url if isinstance(next_url, str) and next_url else None
        params = None

    return str(name or "OSF user"), nodes


def build_tree(raw_nodes: list[dict]) -> tuple[list[dict], list[dict]]:
    by_id = {}
    for item in raw_nodes:
        node = parse_node(item)
        if node["guid"]:
            by_id[node["guid"]] = node

    roots, orphans = [], []
    for node in by_id.values():
        parent = node["parent_guid"]
        if parent and parent in by_id:
            by_id[parent]["children"].append(node)
        elif parent:
            orphans.append(node)
        else:
            roots.append(node)

    def sort_branch(node: dict) -> None:
        node["children"].sort(key=lambda n: n["title"].casefold())
        for child in node["children"]:
            sort_branch(child)

    roots.sort(key=lambda n: n["title"].casefold())
    orphans.sort(key=lambda n: n["title"].casefold())
    for item in roots + orphans:
        sort_branch(item)
    return roots, orphans


def flatten(nodes: list[dict], depth: int = 0, parent_guid: str = "") -> list[dict]:
    rows = []
    for node in nodes:
        row = {**node, "depth": depth, "parent_guid": parent_guid}
        row.pop("children", None)
        rows.append(row)
        rows.extend(flatten(node["children"], depth + 1, node["guid"]))
    return rows


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    connected = bool(request.session.get("osf_token"))
    return templates.TemplateResponse(
        request,
        "home.html",
        {"connected": connected, "configured": configured()},
    )


@app.get("/connect/osf")
def connect_osf(request: Request):
    if not configured():
        return RedirectResponse("/?error=configuration", status_code=303)

    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    query = urlencode(
        {
            "response_type": "code",
            "client_id": OSF_CLIENT_ID,
            "redirect_uri": OSF_REDIRECT_URI,
            "scope": OSF_SCOPE,
            "state": state,
        }
    )
    return RedirectResponse(f"{OSF_AUTHORIZE_URL}?{query}", status_code=303)


@app.get("/callback/osf")
def callback_osf(request: Request, code: str = "", state: str = "", error: str = ""):
    expected = request.session.pop("oauth_state", None)
    if error:
        return RedirectResponse(f"/?error={error}", status_code=303)
    if not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/?error=invalid_state", status_code=303)

    response = requests.post(
        OSF_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": OSF_REDIRECT_URI,
            "client_id": OSF_CLIENT_ID,
            "client_secret": OSF_CLIENT_SECRET,
        },
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    if not response.ok:
        return RedirectResponse("/?error=token_exchange", status_code=303)

    access_token = response.json().get("access_token")
    if not access_token:
        return RedirectResponse("/?error=missing_token", status_code=303)

    request.session["osf_token"] = encrypt_token(access_token)
    request.session["auth_method"] = "oauth"
    return RedirectResponse("/checklist", status_code=303)


@app.post("/connect/token")
async def connect_token(request: Request):
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(raw_body, keep_blank_values=True)
    token = (form.get("token") or [""])[0].strip()

    if not token:
        return RedirectResponse("/?error=missing_personal_token", status_code=303)

    try:
        api_get(f"{OSF_API_BASE}/users/me/", token)
    except RuntimeError:
        request.session.pop("osf_token", None)
        return RedirectResponse("/?error=invalid_personal_token", status_code=303)

    request.session["osf_token"] = encrypt_token(token)
    request.session["auth_method"] = "personal_access_token"
    return RedirectResponse("/checklist", status_code=303)


@app.get("/checklist", response_class=HTMLResponse)
def checklist(request: Request):
    encrypted = request.session.get("osf_token")
    token = decrypt_token(encrypted) if encrypted else None
    if not token:
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    try:
        account_name, raw_nodes = fetch_account_and_nodes(token)
        roots, orphans = build_tree(raw_nodes)
        rows = flatten(roots) + flatten(orphans)
        return templates.TemplateResponse(
            request,
            "checklist.html",
            {
                "account_name": account_name,
                "roots": roots,
                "orphans": orphans,
                "rows": rows,
                "total": len(rows),
                "root_count": len(roots),
                "public_count": sum(1 for row in rows if row["public"]),
                "private_count": sum(1 for row in rows if not row["public"]),
            },
        )
    except RuntimeError as exc:
        return templates.TemplateResponse(
            request, "error.html", {"message": str(exc)}, status_code=502
        )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok", "configured": configured()}
