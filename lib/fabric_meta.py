from __future__ import annotations

import httpx

BASE = "https://meta.fabricmc.net/v2"


async def get_stable_game_versions(client: httpx.AsyncClient) -> list[str]:
    resp = await client.get(f"{BASE}/versions/game")
    resp.raise_for_status()
    return [v["version"] for v in resp.json() if v.get("stable")]


async def get_latest_loader_version(client: httpx.AsyncClient) -> str:
    resp = await client.get(f"{BASE}/versions/loader")
    resp.raise_for_status()
    for entry in resp.json():
        if entry.get("stable"):
            return entry["version"]
    # Fallback: return first entry
    return resp.json()[0]["version"]


async def get_latest_installer_version(client: httpx.AsyncClient) -> tuple[str, str]:
    """Returns (version, download_url)."""
    resp = await client.get(f"{BASE}/versions/installer")
    resp.raise_for_status()
    for entry in resp.json():
        if entry.get("stable"):
            return entry["version"], entry["url"]
    entry = resp.json()[0]
    return entry["version"], entry["url"]


def get_server_jar_url(mc: str, loader: str, installer: str) -> str:
    return f"{BASE}/versions/loader/{mc}/{loader}/{installer}/server/jar"
