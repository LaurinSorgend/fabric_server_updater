from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def create_backup(
    server_dir: Path,
    backup_dir: Path,
    mods_to_backup: list[Path],
    fabric_jar: Path | None = None,
) -> Path:
    """
    Creates a timestamped backup of the given mod files and optionally the Fabric JAR.
    Returns the path to the backup directory created.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / timestamp
    dest.mkdir(parents=True, exist_ok=True)

    if fabric_jar and fabric_jar.exists():
        shutil.copy2(fabric_jar, dest / fabric_jar.name)

    if mods_to_backup:
        mods_dest = dest / "mods"
        mods_dest.mkdir(exist_ok=True)
        for mod_path in mods_to_backup:
            if mod_path.exists():
                shutil.copy2(mod_path, mods_dest / mod_path.name)

    return dest


def find_fabric_jar(server_dir: Path) -> Path | None:
    """Return the Fabric server launcher JAR if found."""
    # New-style: fabric-server-mc.X.Y.Z-loader.A.B.C-launcher.D.E.F.jar
    matches = list(server_dir.glob("fabric-server-mc.*.jar"))
    if matches:
        return matches[0]
    # Old-style
    old = server_dir / "fabric-server-launch.jar"
    if old.exists():
        return old
    return None
