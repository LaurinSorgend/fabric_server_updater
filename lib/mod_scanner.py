from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


@dataclass
class ModInfo:
    path: Path
    filename: str
    mod_id: str
    mod_name: str
    installed_version: str
    sha1: str
    sha512: str
    modrinth_project_id: Optional[str] = None
    modrinth_version_id: Optional[str] = None
    source: Literal["modrinth", "unknown"] = "unknown"
    homepage: Optional[str] = None


def _compute_hashes(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    return (
        hashlib.sha1(data).hexdigest(),
        hashlib.sha512(data).hexdigest(),
    )


def _extract_mod_json(jar_path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(jar_path) as zf:
            if "fabric.mod.json" in zf.namelist():
                return json.loads(zf.read("fabric.mod.json"))
    except zipfile.BadZipFile:
        return None
    except Exception:
        return None
    return None


def _get_homepage(meta: dict) -> Optional[str]:
    contact = meta.get("contact", {})
    for key in ("sources", "homepage", "issues"):
        val = contact.get(key)
        if val and isinstance(val, str):
            return val
    return None


def scan_mods(server_dir: Path, overrides: dict[str, str] | None = None) -> list[ModInfo]:
    overrides = overrides or {}
    mods_dir = server_dir / "mods"
    if not mods_dir.is_dir():
        return []

    results: list[ModInfo] = []

    for jar in sorted(mods_dir.glob("*.jar")):
        if jar.is_relative_to(server_dir / "backups"):
            continue

        sha1, sha512 = _compute_hashes(jar)
        meta = _extract_mod_json(jar)

        if meta is None:
            mod_info = ModInfo(
                path=jar,
                filename=jar.name,
                mod_id="unknown",
                mod_name=jar.stem,
                installed_version="unknown",
                sha1=sha1,
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
                sha1=sha1,
                sha512=sha512,
                homepage=_get_homepage(meta),
            )

        if jar.name in overrides:
            mod_info.modrinth_project_id = overrides[jar.name]

        results.append(mod_info)

    return results
