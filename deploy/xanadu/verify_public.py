from __future__ import annotations

import base64
import re
import urllib.error
import urllib.request
from pathlib import Path


BASE = "https://pianwei.shadlc.net/due-diligence"
PASSWORD_FILE = Path(
    "/home/pianwei/apps/due-diligence-assistant/ops-basic-auth-password.txt"
)


def fetch(path: str, authorization: str | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path)
    if authorization:
        request.add_header("Authorization", authorization)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


home_status, home = fetch("/")
asset_match = re.search(rb'(?:src|href)="(/due-diligence/assets/[^"]+)"', home)
if not asset_match:
    raise RuntimeError("public asset URL not found")
with urllib.request.urlopen(
    "https://pianwei.shadlc.net" + asset_match.group(1).decode(), timeout=20
) as asset_response:
    asset_status = asset_response.status

password = PASSWORD_FILE.read_text(encoding="utf-8").strip()
token = base64.b64encode(f"opsadmin:{password}".encode()).decode()
authorization = "Basic " + token

checks = {
    "home": home_status,
    "asset": asset_status,
    "health": fetch("/api/v1/health")[0],
    "ops_unauthenticated": fetch("/ops")[0],
    "ops_authenticated": fetch("/ops", authorization)[0],
    "ops_api_authenticated": fetch("/api/v1/ops/metrics", authorization)[0],
}
for name, status in checks.items():
    print(f"{name}={status}")

expected = {
    "home": 200,
    "asset": 200,
    "health": 200,
    "ops_unauthenticated": 401,
    "ops_authenticated": 200,
    "ops_api_authenticated": 200,
}
if checks != expected:
    raise SystemExit(1)
