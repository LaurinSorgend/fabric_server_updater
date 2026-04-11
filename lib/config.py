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
    fabric_loader_version: str = ""
    fabric_installer_version: str = ""
    mode: str = "server"  # "server" or "client"
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
            "mode": self.mode,
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
            fabric_loader_version=data.get("fabric_loader_version", ""),
            fabric_installer_version=data.get("fabric_installer_version", ""),
            mode=data.get("mode", "server"),
            user_agent=data.get("user_agent", "fabric-updater/1.0"),
            backup_dir=Path(data["backup_dir"]) if data.get("backup_dir") else None,
            overrides=data.get("overrides", {}),
            mc_compat_overrides=data.get("mc_compat_overrides", {}),
        )


def detect_mc_version_from_instance(instance_dir: Path) -> str | None:
    """
    Try to detect MC version from a Prism/MultiMC mmc-pack.json.
    Checks both the given directory and its parent (in case user pointed to .minecraft/).
    """
    for candidate in (instance_dir, instance_dir.parent):
        mmc_pack = candidate / "mmc-pack.json"
        if mmc_pack.exists():
            try:
                data = json.loads(mmc_pack.read_text())
                for component in data.get("components", []):
                    if component.get("uid") == "net.minecraft":
                        return component.get("version")
            except Exception:
                pass
    return None


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
    """Prompt the user for configuration, save and return Config."""
    import questionary
    from rich.console import Console

    console = Console()

    console.print("[bold cyan]Fabric Updater — First Run Setup[/bold cyan]")
    console.print("No configuration found. Let's set things up.\n")

    mode = questionary.select(
        "What are you updating?",
        choices=[
            questionary.Choice("Fabric server", value="server"),
            questionary.Choice("Modded client instance (Prism, MultiMC, …)", value="client"),
        ],
    ).ask()

    if not mode:
        raise SystemExit("Setup cancelled.")

    if mode == "server":
        dir_prompt = "Path to your Fabric server directory:"
    else:
        dir_prompt = "Path to your instance's .minecraft directory (where mods/ lives):"

    dir_str = questionary.path(dir_prompt, only_directories=True).ask()
    if not dir_str:
        raise SystemExit("Setup cancelled.")

    instance_dir = Path(dir_str).expanduser().resolve()
    if not instance_dir.is_dir():
        console.print(f"[red]Directory not found: {instance_dir}[/red]")
        raise SystemExit(1)

    if mode == "server":
        versions = detect_fabric_versions(instance_dir)
        if versions:
            mc, loader, installer = versions
            console.print(f"[green]Detected:[/green] MC {mc}, Loader {loader}, Installer {installer}")
        else:
            console.print("[yellow]Could not auto-detect versions from server JAR filename.[/yellow]")
            mc = questionary.text("Minecraft version (e.g. 1.21.1):").ask() or ""
            loader = questionary.text("Fabric loader version (e.g. 0.16.0):").ask() or ""
            installer = questionary.text("Fabric installer version (e.g. 1.0.1):").ask() or ""
        cfg = Config(
            server_dir=instance_dir,
            minecraft_version=mc,
            fabric_loader_version=loader,
            fabric_installer_version=installer,
            mode="server",
        )
    else:
        mc = detect_mc_version_from_instance(instance_dir)
        if mc:
            console.print(f"[green]Detected MC version:[/green] {mc}")
        else:
            mc = questionary.text("Minecraft version (e.g. 1.21.4):").ask() or ""
        cfg = Config(
            server_dir=instance_dir,
            minecraft_version=mc,
            mode="client",
        )

    cfg.save(config_path)
    console.print(f"[green]Config saved to {config_path}[/green]\n")
    return cfg


def load_or_create_config(config_path: Path = CONFIG_FILE) -> Config:
    if config_path.exists():
        return Config.load(config_path)
    return create_config_interactively(config_path)
