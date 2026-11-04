"""Browser-facing hardening (spec S1, S2, ADR-0013, ADR-0022).

``SecurityMiddleware`` is a pure ASGI middleware in front of every route:

* **Host allowlist** (DNS rebinding): ``127.0.0.1:<port>`` and ``localhost:<port>`` only.
* **Origin check** (CSRF): a state-changing request with a foreign ``Origin`` or a cross-site
  ``Sec-Fetch-Site`` is refused; ``/api`` reads are refused cross-site as well.
* **Session token**: one random token per Studio launch. ``/api`` needs it in
  ``Authorization: Bearer`` or ``X-P11-Token``; the ``p11_session`` cookie (``HttpOnly``,
  ``SameSite=Strict``) is accepted for safe methods only, so ``<img>`` and ``EventSource`` work
  but a forged POST never does. The browser gets the token by redeeming a one-time **launch code**
  (``p11 open`` puts it in the URL fragment) at ``POST /api/session``.
* **Headers**: strict CSP, ``nosniff``, ``no-referrer``, no framing, no caching of ``/api``.
  ``index.html`` is revalidated on every load, so a rebuilt bundle reaches an open app window;
  the content-hashed ``/assets`` stay cacheable (ADR-0043).
* **Size caps**: ``Content-Length`` and the streamed body are both counted.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from p11 import logs, paths

TOKEN_FILE = "studio.token"
COOKIE = "p11_session"
TOKEN_HEADER = "x-p11-token"
LAUNCH_TTL = 120.0
#: Outstanding launch codes kept at most; minting more drops the oldest (Phase 16 hardening).
MAX_LAUNCH_CODES = 16
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Paths under ``/api`` that work without the token.
PUBLIC_API = frozenset({("POST", "/api/session")})

CSP = "; ".join(
    [
        "default-src 'self'",
        "img-src 'self' blob: data:",
        "media-src 'self' blob:",
        "script-src 'self'",
        "style-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]
)
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
)

KIB = 1024
MIB = 1024 * KIB
#: Body caps per path prefix (longest match wins); everything else gets ``DEFAULT_BODY_CAP``.
DEFAULT_BODY_CAP = 1 * MIB
BODY_CAPS: dict[str, int] = {"/api/uploads": 1024 * MIB, "/api/templates/import": 1 * MIB}


# ---------------------------------------------------------------------------------------------
# Session token and launch codes


@dataclass
class Session:
    """The per-launch token plus outstanding one-time launch codes."""

    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    _codes: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        logs.register_secret(self.token)

    def check(self, candidate: str | None) -> bool:
        return candidate is not None and _same(candidate, self.token)

    def mint_launch_code(self, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        live = sorted(((t, c) for c, t in self._codes.items() if t > now), reverse=True)
        self._codes = {c: t for t, c in live[: MAX_LAUNCH_CODES - 1]}
        code = secrets.token_urlsafe(24)
        logs.register_secret(code)
        self._codes[code] = now + LAUNCH_TTL
        return code

    def redeem(self, code: str, now: float | None = None) -> bool:
        """True once per unexpired code; the code is spent either way."""
        now = time.monotonic() if now is None else now
        match = next((c for c in self._codes if _same(c, code)), None)
        if match is None:
            return False
        expires = self._codes.pop(match)
        return expires > now

    def write(self, path: Path | None = None) -> Path:
        """Write the token ``0600`` for ``p11 open``/``status`` (same user only)."""
        path = path or token_path()
        paths.ensure_private_dir(path.parent)
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(self.token)
        tmp.replace(path)
        return path


def _same(a: str, b: str) -> bool:
    """Constant-time compare that also takes non-ASCII input (headers decode as latin-1;
    ``hmac.compare_digest`` raises ``TypeError`` on non-ASCII ``str``)."""
    return hmac.compare_digest(a.encode("utf-8", "surrogateescape"), b.encode("utf-8"))


def token_path() -> Path:
    return paths.runtime_dir() / TOKEN_FILE


def read_token(path: Path | None = None) -> str | None:
    path = path or token_path()
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


# ---------------------------------------------------------------------------------------------
# Middleware


def allowed_hosts(port: int) -> frozenset[str]:
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


def allowed_origins(port: int) -> frozenset[str]:
    return frozenset({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})


def body_cap(path: str) -> int:
    best = ""
    for prefix in BODY_CAPS:
        if (path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?")) and (
            len(prefix) > len(best)
        ):
            best = prefix
    return BODY_CAPS[best] if best else DEFAULT_BODY_CAP


def _headers(scope: Scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in scope.get("headers", []):
        out.setdefault(k.decode("latin-1").lower(), v.decode("latin-1"))
    return out


def _cookie(header: str, name: str) -> str | None:
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


def request_token(headers: dict[str, str], method: str) -> str | None:
    auth = headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    if TOKEN_HEADER in headers:
        return headers[TOKEN_HEADER].strip()
    if method in SAFE_METHODS:
        return _cookie(headers.get("cookie", ""), COOKIE)
    return None


class _BodyTooLarge(Exception):
    pass


async def _problem(send: Send, status: int, code: str, message: str, hint: str = "") -> None:
    body = json.dumps({"code": code, "message": message, "hint": hint}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                *SECURITY_HEADERS,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, session: Session, port: int) -> None:
        self.app = app
        self.session = session
        self.hosts = allowed_hosts(port)
        self.origins = allowed_origins(port)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":  # P11 uses SSE; refuse websockets outright
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        method: str = scope["method"]
        path: str = scope["path"]
        is_api = path == "/api" or path.startswith("/api/")
        is_asset = path.startswith("/assets/")

        if headers.get("host") not in self.hosts:
            await _problem(
                send,
                421,
                "security.host",
                "This address is not P11 Studio's.",
                "Open P11 with `p11 open` (it uses http://127.0.0.1).",
            )
            return
        origin = headers.get("origin")
        site = headers.get("sec-fetch-site")
        cross = (origin is not None and origin not in self.origins) or (
            site is not None and site not in ("same-origin", "none")
        )
        if cross and (method not in SAFE_METHODS or is_api):
            await _problem(
                send,
                403,
                "security.origin",
                "Request from another website refused.",
                "Only P11 Studio's own page can use its API.",
            )
            return
        needs_token = is_api and (method, path) not in PUBLIC_API
        if needs_token and not self.session.check(request_token(headers, method)):
            await _problem(
                send,
                401,
                "security.token",
                "Missing or wrong session token.",
                "Open P11 with `p11 open`. Scripts send the token in an Authorization header "
                "(`p11 status --token-file` prints where it is).",
            )
            return

        cap = body_cap(path)
        length = headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > cap):
            await _problem(
                send, 413, "request.too-large", "The request is too large.", _cap_hint(cap)
            )
            return

        received = 0
        overflow = False

        async def capped_receive() -> Message:
            nonlocal received, overflow
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > cap:
                    overflow = True
                    raise _BodyTooLarge
            return message

        started = False

        async def secured_send(message: Message) -> None:
            nonlocal started
            if overflow:
                # The app turned the aborted body into its own error (FastAPI: 400); send 413.
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await _problem(send, 413, "request.too-large", "The request is too large.",
                                   _cap_hint(cap))  # fmt: skip
                return
            if message["type"] == "http.response.start":
                started = True
                hdrs: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                present = {k.lower() for k, _ in hdrs}
                hdrs += [(k, v) for k, v in SECURITY_HEADERS if k not in present]
                if b"cache-control" not in present and not is_asset:
                    hdrs.append((b"cache-control", b"no-store" if is_api else b"no-cache"))
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, capped_receive, secured_send)
        except _BodyTooLarge:
            if not started:
                await _problem(
                    send, 413, "request.too-large", "The request is too large.", _cap_hint(cap)
                )


def _cap_hint(cap: int) -> str:
    return f"The limit for this request is {cap // MIB} MB."


def session_cookie(token: str) -> str:
    return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict"
