from __future__ import annotations

import asyncio
import json as _json
from typing import Any

import httpx

from .mod_scanner import ModInfo

BASE = "https://api.modrinth.com/v2"
_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(5)
    return _SEMAPHORE


async def _get(client: httpx.AsyncClient, url: str, **kwargs) -> Any:
    async with _get_semaphore():
        resp = await client.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()


async def _post(client: httpx.AsyncClient, url: str, **kwargs) -> Any:
    async with _get_semaphore():
        resp = await client.post(url, **kwargs)
        resp.raise_for_status()
        return resp.json()


async def identify_mods_by_hash(
    client: httpx.AsyncClient, mods: list[ModInfo]
) -> dict[str, dict]:
    """
    POST /version_files — identify mods by SHA512 hash.
    Returns dict mapping sha512 -> version object (with project_id, id, etc.)
    Updates ModInfo.modrinth_project_id, modrinth_version_id, source in-place.
    """
    if not mods:
        return {}

    hashes = [m.sha512 for m in mods]
    data = await _post(
        client,
        f"{BASE}/version_files",
        json={"hashes": hashes, "algorithm": "sha512"},
    )
    # data: { sha512: version_object }

    hash_to_mod = {m.sha512: m for m in mods}
    for sha512, version_obj in data.items():
        mod = hash_to_mod.get(sha512)
        if mod:
            mod.modrinth_project_id = version_obj.get("project_id")
            mod.modrinth_version_id = version_obj.get("id")
            mod.source = "modrinth"

    return data


async def get_latest_versions(
    client: httpx.AsyncClient,
    mods: list[ModInfo],
    mc_version: str,
) -> dict[str, dict]:
    """
    POST /version_files/update — get latest compatible version for each mod.
    Only sends mods that are identified as Modrinth mods.
    Returns dict mapping sha512 -> latest version object.
    """
    modrinth_mods = [m for m in mods if m.source == "modrinth"]
    if not modrinth_mods:
        return {}

    hashes = [m.sha512 for m in modrinth_mods]
    data = await _post(
        client,
        f"{BASE}/version_files/update",
        json={
            "hashes": hashes,
            "algorithm": "sha512",
            "loaders": ["fabric"],
            "game_versions": [mc_version],
        },
    )
    return data  # { sha512: latest_version_object }


async def get_project(client: httpx.AsyncClient, project_id_or_slug: str) -> dict:
    """GET /project/{id|slug} — fetch project metadata."""
    return await _get(client, f"{BASE}/project/{project_id_or_slug}")


async def get_latest_version_for_project(
    client: httpx.AsyncClient,
    project_id_or_slug: str,
    mc_version: str,
) -> dict | None:
    """
    GET /project/{id}/version — fetch the latest fabric version for a given MC version.
    Returns the version object or None if no compatible version exists.
    """
    try:
        versions = await _get(
            client,
            f"{BASE}/project/{project_id_or_slug}/version",
            params={
                "loaders": _json.dumps(["fabric"]),
                "game_versions": _json.dumps([mc_version]),
            },
        )
    except httpx.HTTPStatusError:
        return None
    if not versions:
        return None
    return versions[0]


async def check_mc_compat(
    client: httpx.AsyncClient,
    mods: list[ModInfo],
    candidate_mc_version: str,
) -> dict[str, bool]:
    """
    For each Modrinth mod, check if any version exists for candidate_mc_version.
    Returns dict mapping modrinth_project_id -> bool (True = compatible).
    """
    modrinth_mods = [m for m in mods if m.source == "modrinth" and m.modrinth_project_id]
    if not modrinth_mods:
        return {}

    async def check_one(mod: ModInfo) -> tuple[str, bool]:
        try:
            versions = await _get(
                client,
                f"{BASE}/project/{mod.modrinth_project_id}/version",
                params={
                    "loaders": _json.dumps(["fabric"]),
                    "game_versions": _json.dumps([candidate_mc_version]),
                },
            )
            return mod.modrinth_project_id, len(versions) > 0
        except httpx.HTTPStatusError:
            return mod.modrinth_project_id, False

    results = await asyncio.gather(*[check_one(m) for m in modrinth_mods])
    return dict(results)
