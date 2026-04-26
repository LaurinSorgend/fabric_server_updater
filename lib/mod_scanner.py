from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

_HASH_CHUNK_SIZE = 1 << 20  # 1 MiB


@dataclass
class ModInfo:
    path: Path
    filename: str
    mod_id: str
    mod_name: str
    installed_version: str
    sha512: str
    modrinth_project_id: Optional[str] = None
    modrinth_version_id: Optional[str] = None
    source: Literal["modrinth", "unknown"] = "unknown"
    homepage: Optional[str] = None


def _compute_sha512(path: Path) -> str:
    hasher = hashlib.sha512()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _extract_mod_json(jar_path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(jar_path) as zf:
            if "fabric.mod.json" in zf.namelist():
                return json.loads(zf.read("fabric.mod.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError):
        return None
    return None


def _get_homepage(meta: dict) -> Optional[str]:
    contact = meta.get("contact", {})
    for key in ("sources", "homepage", "issues"):
        val = contact.get(key)
        if val and isinstance(val, str):
            return val
    return None


def scan_mods(
    server_dir: Path, overrides: dict[str, str] | None = None
) -> list[ModInfo]:
    overrides = overrides or {}
    mods_dir = server_dir / "mods"
    if not mods_dir.is_dir():
        return []

    results: list[ModInfo] = []

    for jar in sorted(mods_dir.glob("*.jar")):
        if jar.is_relative_to(server_dir / "backups"):
            continue

        sha512 = _compute_sha512(jar)
        meta = _extract_mod_json(jar)

        if meta is None:
            mod_info = ModInfo(
                path=jar,
                filename=jar.name,
                mod_id="unknown",
                mod_name=jar.stem,
                installed_version="unknown",
                sha512=sha512,
                homepage=None,
            )
        else:
            mod_info = ModInfo(
                path=jar,
                filename=jar.name,
                mod_id=meta.get("id", "unknown"),
                mod_name=meta.get("name", jar.stem),
                installed_version=meta.get("version", "unknown"),
                sha512=sha512,
                homepage=_get_homepage(meta),
            )

        if jar.name in overrides:
            mod_info.modrinth_project_id = overrides[jar.name]

        results.append(mod_info)

    return results
