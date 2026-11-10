"""
Light security for the dashboard API (backend/dashboard/app.py).

 1. Reading is open (the dashboard needs it), but every request that CHANGES data (POST, PUT, PATCH, DELETE under /api/)
    needs the admin key in the X-Admin-Key header. The key comes from the DASH_ADMIN_KEY environment variable; if it is
    not set, a random key is made and printed in the terminal when the server starts. It is never stored in the repository.
 2. After 5 wrong keys from one address in 5 minutes, further attempts are refused (HTTP 429) until the window passes.
 3. Every attempt to change data is written to audit.log (time, address, method, path, result). Request bodies are not logged.
 4. Security headers on every response, and no caching of API answers.

The server already listens on 127.0.0.1 only, so only this laptop can reach it. This is protection for a prototype, not a
replacement for user accounts, roles and HTTPS; those are listed as future work.
"""
import hmac
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import g, jsonify, request

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_FAILS = 5
WINDOW_S = 300


def init_security(app, log_file=None):
    key = os.environ.get("DASH_ADMIN_KEY", "").strip()
    if not key:
        key = secrets.token_urlsafe(9)
        print(f"Admin key for this session: {key}   (set DASH_ADMIN_KEY to choose your own)")
    app.config["ADMIN_KEY"] = key

    audit = logging.getLogger("dashboard.audit")
    audit.setLevel(logging.INFO)
    if not audit.handlers:
        path = Path(log_file or Path(__file__).resolve().parent / "audit.log")
        handler = RotatingFileHandler(path, maxBytes=500_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        audit.addHandler(handler)
    fails = defaultdict(deque)

    @app.before_request
    def guard():
        if request.method not in WRITE_METHODS or not request.path.startswith("/api/"):
            return None
        who = request.remote_addr or "?"
        now = time.time()
        q = fails[who]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= MAX_FAILS:
            audit.info("%s %s %s BLOCKED too many wrong keys", who, request.method, request.path)
            return jsonify({"error": "Too many wrong keys. Wait a few minutes and try again."}), 429
        given = request.headers.get("X-Admin-Key", "")
        if not hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8")):
            if given:               # only a wrong key counts toward the lock-out; a missing key just asks for the key
                q.append(now)
            audit.info("%s %s %s DENIED %s key", who, request.method, request.path, "wrong" if given else "missing")
            return jsonify({"error": "Admin key required"}), 401
        g.audited = True
        return None

    @app.after_request
    def headers(resp):
        if getattr(g, "audited", False):
            audit.info("%s %s %s ALLOWED status %s", request.remote_addr, request.method, request.path, resp.status_code)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return resp

    @app.route("/api/auth/check", methods=["POST"])
    def auth_check():
        """Lets a client test an admin key: 200 if it is right (the guard above rejects wrong ones)."""
        return jsonify({"ok": True})
