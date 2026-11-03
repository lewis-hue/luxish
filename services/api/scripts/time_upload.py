"""Measure what a person actually waits for after photographing a garment.

Uploads over HTTP exactly as the app does, then polls the garment the way the
client polls it, and reports the two numbers that matter: time until the
garment is sorted (which is what ends the spinner) and time until the cut-out
replaces the photograph.

    python scripts/time_upload.py <image> <username> <password>
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

API = os.environ.get("TRACE_API", "http://192.168.100.2:8010")
ISSUER = os.environ.get("TRACE_ISSUER", "https://luxish-kc.loca.lt/realms/luxish")

#: Tokens are minted against Keycloak directly, not through the public tunnel.
#:
#: `KC_HOSTNAME` makes the realm stamp the tunnel issuer on every token no
#: matter which address it was reached on, so a token minted here carries the
#: issuer the API validates against. The tunnel exists for the phone's browser
#: and for Google, neither of which is involved in a script, and routing these
#: through it only made every run depend on a third party staying up.
MINT_URL = "http://localhost:55080/realms/luxish"


async def main() -> int:
    image, username, password = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    data = image.read_bytes()

    async with httpx.AsyncClient(timeout=120) as http:
        token = (await http.post(
            f"{MINT_URL}/protocol/openid-connect/token",
            data={"client_id": "luxish-mobile", "grant_type": "password",
                  "scope": "openid profile email",
                  "username": username, "password": password},
        )).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        started = time.monotonic()
        issued = (await http.post(f"{API}/v1/uploads/authorize", headers=auth, json={
            "kind": "garment_photo", "content_type": "image/webp",
            "content_length": len(data)})).json()
        await http.put(issued["upload_url"],
                       headers={**auth, **issued.get("required_headers", {})},
                       content=data)
        created = (await http.post(f"{API}/v1/wardrobe/garments", headers=auth, json={
            "name": image.stem, "media_asset_id": issued["asset_id"],
            "availability": "available"})).json()
        gid = created["id"]
        print(f"upload accepted in {time.monotonic() - started:.1f}s  ({gid})")

        sorted_at = cutout_at = None
        while time.monotonic() - started < 180:
            await asyncio.sleep(1.0)
            g = (await http.get(f"{API}/v1/wardrobe/garments/{gid}", headers=auth)).json()
            now = time.monotonic() - started
            if sorted_at is None and g.get("category"):
                sorted_at = now
                print(f"SORTED           {now:5.1f}s  category={g['category']}")
            if cutout_at is None and g.get("background_removed_url"):
                cutout_at = now
                print(f"cut-out ready    {now:5.1f}s")
            if sorted_at and cutout_at:
                break

        if sorted_at is None:
            print("never sorted within 180s")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
