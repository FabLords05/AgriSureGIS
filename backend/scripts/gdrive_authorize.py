"""
One-time Google Drive authorization for backups (2026-10-22).

Mints the GDRIVE_REFRESH_TOKEN that app/services/backup_service.py uses to
upload pg_dump files into a personal Gmail's Drive. Run it once, by hand, on
any machine with a browser -- then paste the printed token into backend/.env.

Before running:
  1. Google Cloud Console -> APIs & Services -> enable "Google Drive API".
  2. Credentials -> Create OAuth client ID -> Application type "Desktop app".
     Put its client id/secret in backend/.env as GDRIVE_CLIENT_ID and
     GDRIVE_CLIENT_SECRET.
  3. OAuth consent screen: add the Gmail account as a test user, and set the
     publishing status to "In production" -- refresh tokens of apps left in
     "Testing" expire after 7 days.

Usage (from backend/):
    python scripts/gdrive_authorize.py

Scope is drive.file: the app can only see files it uploaded itself, not the
rest of that Drive. Uses only the standard library + httpx (already in
requirements.txt), so nothing new needs installing.
"""
import os
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from dotenv import load_dotenv

load_dotenv()

SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        _CallbackHandler.result = params
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        message = "Authorized. You can close this tab." if "code" in params else "Authorization failed."
        self.wfile.write(f"<p>AgriSureGIS backups: {message}</p>".encode())

    def log_message(self, *args):
        pass


def main() -> int:
    client_id = os.getenv("GDRIVE_CLIENT_ID")
    client_secret = os.getenv("GDRIVE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Set GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET in backend/.env first (see this file's docstring).")
        return 1

    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        # offline + consent: always return a refresh token, even on a re-run.
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })

    print("Opening the Google sign-in page. If it doesn't open, visit:\n\n" + url + "\n")
    webbrowser.open(url)
    server.handle_request()
    server.server_close()

    result = _CallbackHandler.result
    if result.get("state") != state or "code" not in result:
        print(f"Authorization failed: {result.get('error', 'no code returned')}")
        return 1

    response = httpx.post(TOKEN_URL, data={
        "code": result["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=30)
    if response.status_code != 200:
        print(f"Token exchange failed: {response.text}")
        return 1
    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        print("Google returned no refresh token. Remove the app's access at "
              "https://myaccount.google.com/permissions and run this again.")
        return 1

    print("Add this line to backend/.env (keep it secret):\n")
    print(f"GDRIVE_REFRESH_TOKEN={refresh_token}\n")
    print("Then set GDRIVE_FOLDER_ID to the id at the end of the target Drive folder's URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
