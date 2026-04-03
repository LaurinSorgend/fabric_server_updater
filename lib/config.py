from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

CONFIG_FILE = Path("updater_config.json")

_NEW_JAR_PATTERN = re.compile(
    r"fabric-server-mc\.(?P<mc>[^-]+)-loader\.(?P<loader>[^-]+)-launcher\.(?P<installer>[^.]+)\.jar"
)


@dataclass
class Config:
    server_dir: Path
    minecraft_version: str
    fabric_loader_version: str
    fabric_installer_version: str
    user_agent: str = "fabric-updater/1.0 (github.com/user/fabric-updater)"
    backup_dir: Optional[Path] = None
    overrides: dict[str, str] = field(default_factory=dict)
    mc_compat_overrides: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self):
        self.server_dir = Path(self.server_dir)
        if self.backup_dir is None:
            self.backup_dir = self.server_dir / "backups"
        else:
            self.backup_dir = Path(self.backup_dir)

    def save(self, path: Path = CONFIG_FILE) -> None:
        data = {
            "server_dir": str(self.server_dir),
            "minecraft_version": self.minecraft_version,
            "fabric_loader_version": self.fabric_loader_version,
            "fabric_installer_version": self.fabric_installer_version,
            "user_agent": self.user_agent,
            "backup_dir": str(self.backup_dir),
            "overrides": self.overrides,
            "mc_compat_overrides": self.mc_compat_overrides,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "Config":
        data = json.loads(path.read_text())
        return cls(
            server_dir=Path(data["server_dir"]),
            minecraft_version=data["minecraft_version"],
            fabric_loader_version=data["fabric_loader_version"],
            fabric_installer_version=data["fabric_installer_version"],
            user_agent=data.get("user_agent", "fabric-updater/1.0"),
            backup_dir=Path(data["backup_dir"]) if data.get("backup_dir") else None,
            overrides=data.get("overrides", {}),
            mc_compat_overrides=data.get("mc_compat_overrides", {}),
        )


def detect_fabric_versions(server_dir: Path) -> tuple[str, str, str] | None:
    """
    Try to detect MC version, loader version, and installer version from the
    server JAR filename. Returns (mc, loader, installer) or None if not found.
    """
    for jar in server_dir.glob("fabric-server-mc.*.jar"):
        m = _NEW_JAR_PATTERN.match(jar.name)
        if m:
            return m.group("mc"), m.group("loader"), m.group("installer")
    # Old-style launcher — versions unknown
    if (server_dir / "fabric-server-launch.jar").exists():
        return None
    return None


def create_config_interactively(config_path: Path = CONFIG_FILE) -> Config:
    """Prompt the user for server_dir, auto-detect the rest, save and return Config."""
    import questionary
    from rich.console import Console

    console = Console()

    console.print("[bold cyan]Fabric Server Updater — First Run Setup[/bold cyan]")
    console.print("No configuration found. Let's set things up.\n")

    server_dir_str = questionary.path(
        "Path to your Fabric server directory:",
        only_directories=True,
    ).ask()

    if not server_dir_str:
        raise SystemExit("Setup cancelled.")

    server_dir = Path(server_dir_str).expanduser().resolve()
    if not server_dir.is_dir():
        console.print(f"[red]Directory not found: {server_dir}[/red]")
        raise SystemExit(1)

    versions = detect_fabric_versions(server_dir)
    if versions:
        mc, loader, installer = versions
        console.print(f"[green]Detected:[/green] MC {mc}, Loader {loader}, Installer {installer}")
    else:
        console.print("[yellow]Could not auto-detect versions from server JAR filename.[/yellow]")
        mc = questionary.text("Minecraft version (e.g. 1.21.1):").ask() or ""
        loader = questionary.text("Fabric loader version (e.g. 0.16.0):").ask() or ""
        installer = questionary.text("Fabric installer version (e.g. 1.0.1):").ask() or ""

    cfg = Config(
        server_dir=server_dir,
        minecraft_version=mc,
        fabric_loader_version=loader,
        fabric_installer_version=installer,
    )
    cfg.save(config_path)
    console.print(f"[green]Config saved to {config_path}[/green]\n")
    return cfg


def load_or_create_config(config_path: Path = CONFIG_FILE) -> Config:
    if config_path.exists():
        return Config.load(config_path)
    return create_config_interactively(config_path)
