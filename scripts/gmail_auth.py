#!/usr/bin/env python3
"""One-time OAuth consent (loopback + PKCE) that mints a refresh token limited to the gmail.send scope.

Setup: Google Cloud Console -> create OAuth client of type "Desktop app" -> enable Gmail API.
Run:   GMAIL_CLIENT_ID=... GMAIL_CLIENT_SECRET=... python3 scripts/gmail_auth.py
Then store the printed GMAIL_REFRESH_TOKEN in your secrets manager (never commit it).
"""
import ssl, base64, hashlib, http.server, json, os, secrets, sys, threading, urllib.parse, urllib.request, webbrowser

SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
SCOPE = " ".join(SCOPES)
cid, csec = os.getenv("GMAIL_CLIENT_ID"), os.getenv("GMAIL_CLIENT_SECRET")
if not (cid and csec):
    sys.exit("set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET")

verifier = secrets.token_urlsafe(64)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
state, got = secrets.token_urlsafe(16), {}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        got.update(q)
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
        self.wfile.write(b"Authorized. You can close this tab.")
        threading.Thread(target=self.server.shutdown).start()

    def log_message(self, *a): pass


srv = http.server.HTTPServer(("127.0.0.1", 0), H)
redirect = f"http://127.0.0.1:{srv.server_port}"
url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
    "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE, "state": state,
    "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"})
print("Opening browser for consent (send + read-only; nothing else)...\n", url)
webbrowser.open(url)
srv.serve_forever()
if got.get("state") != state or "code" not in got:
    sys.exit(f"authorization failed: {got}")
data = urllib.parse.urlencode({"client_id": cid, "client_secret": csec, "code": got["code"], "code_verifier": verifier,
                               "grant_type": "authorization_code", "redirect_uri": redirect}).encode()
try:
    import certifi; ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    ctx = ssl.create_default_context()
tok = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data, context=ctx))
if set(tok.get("scope", "").split()) != set(SCOPES):
    sys.exit(f"unexpected scopes granted: {tok.get('scope')}")
print("\nGMAIL_REFRESH_TOKEN=" + tok["refresh_token"])
