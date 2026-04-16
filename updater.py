#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

import httpx
from rich.console import Console
from rich.table import Table
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

from lib import config as cfg_module
from lib import fabric_meta
from lib import modrinth as modrinth_mod
from lib import mod_scanner
from lib import update_planner
from lib import backup as backup_mod
from lib import downloader as dl_mod
from lib.update_planner import UpdatePlan, ModUpdate

console = Console()

_START_SCRIPT_NAMES = ("start.sh", "start.bat", "run.sh", "run.bat")


def _patch_start_scripts(server_dir: Path, old_jar_name: str | None, new_jar_name: str) -> None:
    if not old_jar_name or old_jar_name == new_jar_name:
        return
    for script_name in _START_SCRIPT_NAMES:
        script = server_dir / script_name
        if not script.exists():
            continue
        text = script.read_text(encoding="utf-8")
        if old_jar_name not in text:
            continue
        script.write_text(text.replace(old_jar_name, new_jar_name), encoding="utf-8")
        console.print(f"[dim]Updated {script_name}: {old_jar_name} → {new_jar_name}[/dim]")


def _make_client(user_agent: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=30.0,
        follow_redirects=True,
    )


def _print_update_table(plan: UpdatePlan) -> None:
    # Fabric section
    if plan.fabric_update:
        fu = plan.fabric_update
        fab_table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
        fab_table.add_column(style="bold")
        fab_table.add_column()
        fab_table.add_column()
        fab_table.add_column()

        loader_status = "[green]UPDATE[/green]" if fu.current_loader != fu.latest_loader else "[dim]OK[/dim]"
        inst_status = "[green]UPDATE[/green]" if fu.current_installer != fu.latest_installer else "[dim]OK[/dim]"

        fab_table.add_row("Fabric Loader", fu.current_loader, f"→  {fu.latest_loader}", loader_status)
        fab_table.add_row("Fabric Installer", fu.current_installer, f"→  {fu.latest_installer}", inst_status)

        console.print("\n[bold]Fabric Server JAR[/bold]")
        console.print(fab_table)

    # Mods section
    if plan.mod_updates:
        mod_table = Table(box=box.ROUNDED, padding=(0, 1))
        mod_table.add_column("Mod", style="bold")
        mod_table.add_column("Installed")
        mod_table.add_column("Latest")
        mod_table.add_column("Status")

        for mu in sorted(plan.mod_updates, key=lambda x: x.mod.mod_name.lower()):
            if mu.is_update:
                status = "[green]UPDATE[/green]"
                latest = mu.latest_version_number
            else:
                status = "[dim]OK[/dim]"
                latest = mu.latest_version_number or mu.mod.installed_version

            mod_table.add_row(
                mu.mod.mod_name,
                mu.mod.installed_version,
                latest,
                status,
            )

        console.print("\n[bold]Mods[/bold]")
        console.print(mod_table)

    if plan.unknown_mods:
        console.print(f"\n[yellow]{len(plan.unknown_mods)} mod(s) not from Modrinth (skipped):[/yellow]")
        for m in plan.unknown_mods:
            hp = f"  [dim]{m.homepage}[/dim]" if m.homepage else ""
            console.print(f"  [dim]{m.mod_name}[/dim]{hp}")


def _summarise_plan(plan: UpdatePlan) -> None:
    updates = len(plan.available_mod_updates)
    fabric_upd = plan.fabric_update and plan.fabric_update.is_update
    if updates == 0 and not fabric_upd:
        console.print("\n[green]Everything is up to date.[/green]")
    else:
        parts = []
        if fabric_upd:
            parts.append("Fabric server JAR")
        if updates:
            parts.append(f"{updates} mod(s)")
        console.print(f"\n[bold green]{', '.join(parts)} can be updated.[/bold green]")


async def _gather_update_info(
    config: cfg_module.Config,
    include_snapshots: bool = False,
) -> tuple[UpdatePlan, list[mod_scanner.ModInfo]]:
    mods = mod_scanner.scan_mods(config.server_dir, config.overrides)

    async with _make_client(config.user_agent) as client:
        if config.mode == "server":
            with console.status("[cyan]Fetching Fabric meta…[/cyan]"):
                latest_loader, (latest_installer, _installer_url) = await asyncio.gather(
                    fabric_meta.get_latest_loader_version(client),
                    fabric_meta.get_latest_installer_version(client),
                )
        else:
            latest_loader = latest_installer = None

        with console.status("[cyan]Identifying mods via Modrinth…[/cyan]"):
            await modrinth_mod.identify_mods_by_hash(client, mods)

        with console.status("[cyan]Checking for mod updates…[/cyan]"):
            latest_versions = await modrinth_mod.get_latest_versions(client, mods, config.minecraft_version)

    if config.mode == "server":
        fabric_jar_url = fabric_meta.get_server_jar_url(
            config.minecraft_version, latest_loader, latest_installer
        )
    else:
        fabric_jar_url = None

    plan = update_planner.build_plan(
        mods=mods,
        latest_versions=latest_versions,
        current_loader=config.fabric_loader_version or None,
        latest_loader=latest_loader,
        current_installer=config.fabric_installer_version or None,
        latest_installer=latest_installer,
        mc_version=config.minecraft_version,
        fabric_jar_url=fabric_jar_url,
    )
    return plan, mods


async def _apply_updates(
    config: cfg_module.Config,
    plan: UpdatePlan,
    update_fabric: bool,
    selected_mod_updates: list[ModUpdate],
    dry_run: bool,
) -> None:
    if dry_run:
        console.print("\n[yellow][DRY RUN] No files will be changed.[/yellow]")
        if update_fabric and plan.fabric_update and plan.fabric_update.is_update:
            fu = plan.fabric_update
            old_jar = backup_mod.find_fabric_jar(config.server_dir)
            new_jar_name = (
                f"fabric-server-mc.{fu.mc_version}"
                f"-loader.{fu.latest_loader}"
                f"-launcher.{fu.latest_installer}.jar"
            )
            console.print(f"  Would download Fabric JAR → {config.server_dir / new_jar_name}")
            if old_jar:
                console.print(f"  Would delete old JAR: {old_jar.name}")
            for script_name in _START_SCRIPT_NAMES:
                if (config.server_dir / script_name).exists():
                    console.print(f"  Would patch {script_name}: {old_jar.name if old_jar else '?'} → {new_jar_name}")
        for mu in selected_mod_updates:
            console.print(f"  Would update: {mu.mod.mod_name} → {mu.latest_version_number}")
        return

    fabric_jar = backup_mod.find_fabric_jar(config.server_dir) if update_fabric else None
    mod_paths = [mu.mod.path for mu in selected_mod_updates]

    if fabric_jar or mod_paths:
        backup_path = backup_mod.create_backup(
            config.server_dir,
            config.backup_dir,
            mod_paths,
            fabric_jar if update_fabric else None,
        )
        console.print(f"[dim]Backup created: {backup_path}[/dim]")

    async with _make_client(config.user_agent) as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
        ) as progress:
            if update_fabric and plan.fabric_update and plan.fabric_update.is_update:
                fu = plan.fabric_update
                jar_name = (
                    f"fabric-server-mc.{fu.mc_version}"
                    f"-loader.{fu.latest_loader}"
                    f"-launcher.{fu.latest_installer}.jar"
                )
                dest = config.server_dir / jar_name
                task = progress.add_task(f"Fabric JAR ({jar_name})", total=None)
                await dl_mod.download_file(client, fu.download_url, dest, "", progress, task)

                if fabric_jar and fabric_jar.resolve() != dest.resolve():
                    fabric_jar.unlink(missing_ok=True)

                _patch_start_scripts(config.server_dir, fabric_jar.name if fabric_jar else None, jar_name)

                config.fabric_loader_version = fu.latest_loader
                config.fabric_installer_version = fu.latest_installer
                config.save()
                console.print(f"[green]✓[/green] Fabric JAR updated.")

            for mu in selected_mod_updates:
                if not mu.download_url:
                    console.print(f"[yellow]⚠[/yellow] No download URL for {mu.mod.mod_name}, skipping.")
                    continue

                url_filename = mu.download_url.split("?")[0].rsplit("/", 1)[-1]
                dest = config.server_dir / "mods" / url_filename
                task = progress.add_task(f"{mu.mod.mod_name} {mu.latest_version_number}", total=None)

                try:
                    await dl_mod.download_file(client, mu.download_url, dest, mu.file_sha512, progress, task)
                    if mu.mod.path != dest and mu.mod.path.exists():
                        mu.mod.path.unlink()
                    console.print(f"[green]✓[/green] {mu.mod.mod_name} → {mu.latest_version_number}")
                except ValueError as e:
                    console.print(f"[red]✗ Hash verification failed for {mu.mod.mod_name}:[/red] {e}")
                except Exception as e:
                    console.print(f"[red]✗ Failed to download {mu.mod.mod_name}:[/red] {e}")


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

async def cmd_check(args: argparse.Namespace, config: cfg_module.Config) -> None:
    plan, _ = await _gather_update_info(config)
    _print_update_table(plan)
    _summarise_plan(plan)


async def _prompt_update_selection(
    plan: UpdatePlan,
    yes: bool,
    fabric_only: bool = False,
    mods_only: bool = False,
) -> tuple[bool, list[ModUpdate]] | None:
    """Return (update_fabric, selected_mods), or None if cancelled/nothing to do."""
    available_mods = plan.available_mod_updates
    fabric_available = plan.fabric_update and plan.fabric_update.is_update

    if yes:
        update_fabric = (not mods_only) and bool(fabric_available)
        selected = [] if fabric_only else available_mods
        if not selected and not update_fabric:
            return None
        return update_fabric, selected

    import questionary

    choices_fabric = []
    if not mods_only and fabric_available:
        fu = plan.fabric_update
        choices_fabric = [questionary.Choice(
            title=f"Fabric Loader {fu.current_loader} → {fu.latest_loader}"
                  f"  /  Installer {fu.current_installer} → {fu.latest_installer}",
            value="fabric",
            checked=True,
        )]

    choices_mods = [] if fabric_only else [
        questionary.Choice(
            title=f"{mu.mod.mod_name}  {mu.mod.installed_version} → {mu.latest_version_number}",
            value=mu,
            checked=True,
        )
        for mu in available_mods
    ]

    all_choices = choices_fabric + choices_mods
    if not all_choices:
        return None

    selected_values = await questionary.checkbox(
        "Select updates to apply:", choices=all_choices
    ).ask_async()

    if not selected_values:
        return None

    update_fabric = "fabric" in selected_values
    selected = [v for v in selected_values if isinstance(v, update_planner.ModUpdate)]
    return update_fabric, selected


async def cmd_update(
    args: argparse.Namespace,
    config: cfg_module.Config,
    fabric_only: bool = False,
    mods_only: bool = False,
) -> None:
    plan, _ = await _gather_update_info(config)
    _print_update_table(plan)
    _summarise_plan(plan)

    if not plan.available_mod_updates and not (plan.fabric_update and plan.fabric_update.is_update):
        return

    result = await _prompt_update_selection(plan, args.yes, fabric_only, mods_only)
    if result is None:
        console.print("[yellow]No updates selected. Exiting.[/yellow]")
        return

    update_fabric, selected = result
    await _apply_updates(config, plan, update_fabric, selected, dry_run=args.dry_run)


async def cmd_check_mc(args: argparse.Namespace, config: cfg_module.Config) -> None:
    candidate = args.version
    mods = mod_scanner.scan_mods(config.server_dir, config.overrides)

    async with _make_client(config.user_agent) as client:
        with console.status("[cyan]Identifying mods…[/cyan]"):
            await modrinth_mod.identify_mods_by_hash(client, mods)
        with console.status(f"[cyan]Checking compatibility with MC {candidate}…[/cyan]"):
            compat = await modrinth_mod.check_mc_compat(client, mods, candidate)

    console.print(f"\n[bold]MC Version Compatibility Check: {config.minecraft_version} → {candidate}[/bold]\n")

    table = Table(box=box.ROUNDED, padding=(0, 1))
    table.add_column("Mod", style="bold")
    table.add_column("Status")
    table.add_column("Note")

    force_compatible: set[str] = set(args.force_compatible)
    for filename, versions in config.mc_compat_overrides.items():
        if "*" in versions or candidate in versions:
            force_compatible.add(filename)

    blockers = []
    unchecked = []
    for mod in mods:
        if mod.filename in force_compatible:
            table.add_row(mod.mod_name, "[green]✓[/green]", "manual override")
        elif mod.source == "modrinth" and mod.modrinth_project_id:
            supported = compat.get(mod.modrinth_project_id, False)
            if supported:
                table.add_row(mod.mod_name, "[green]✓[/green]", "")
            else:
                table.add_row(mod.mod_name, "[red]✗[/red]", f"No version for {candidate}")
                blockers.append(mod)
        else:
            note = mod.homepage or "not on Modrinth"
            table.add_row(mod.mod_name, "[yellow]?[/yellow]", note)
            unchecked.append(mod)

    console.print(table)

    if blockers:
        console.print(
            f"\n[bold red]BLOCKED[/bold red] — {len(blockers)} mod(s) have no release for MC {candidate}:"
        )
        for m in blockers:
            console.print(f"  • {m.mod_name}")
    else:
        if unchecked:
            console.print(
                f"\n[yellow]Note:[/yellow] {len(unchecked)} mod(s) could not be checked (not on Modrinth)."
            )
        console.print(f"[green]All known mods support MC {candidate}.[/green]")


async def cmd_update_mc(args: argparse.Namespace, config: cfg_module.Config) -> None:
    target = args.version
    if target == config.minecraft_version:
        console.print(f"[yellow]Already on MC {target}.[/yellow]")
        return

    console.print(
        f"\n[bold]Upgrading MC {config.minecraft_version} → {target}[/bold]\n"
    )
    config.minecraft_version = target  # persisted only on successful apply

    plan, _ = await _gather_update_info(config)

    # Force fabric JAR download — its filename embeds the MC version even when
    # loader/installer versions haven't changed.
    if plan.fabric_update and not plan.fabric_update.is_update:
        plan.fabric_update.is_update = True

    _print_update_table(plan)
    _summarise_plan(plan)

    result = await _prompt_update_selection(plan, args.yes)
    if result is None:
        console.print("[yellow]No updates selected. Exiting.[/yellow]")
        return

    update_fabric, selected = result
    await _apply_updates(config, plan, update_fabric, selected, dry_run=args.dry_run)

    if not args.dry_run:
        config.save()  # ensure new minecraft_version is persisted even if fabric was skipped
        console.print(f"[bold green]Minecraft version set to {target} in config.[/bold green]")


async def cmd_config(args: argparse.Namespace, config: cfg_module.Config) -> None:
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("mode", config.mode)
    table.add_row("server_dir", str(config.server_dir))
    table.add_row("minecraft_version", config.minecraft_version)
    if config.mode == "server":
        table.add_row("fabric_loader_version", config.fabric_loader_version)
        table.add_row("fabric_installer_version", config.fabric_installer_version)
    table.add_row("backup_dir", str(config.backup_dir))
    table.add_row("user_agent", config.user_agent)
    if config.overrides:
        table.add_row("overrides", str(config.overrides))
    if config.mc_compat_overrides:
        table.add_row("mc_compat_overrides", str(config.mc_compat_overrides))
    console.print("\n[bold]Current Configuration[/bold]")
    console.print(table)
    console.print(f"\n[dim]Config file: {cfg_module.CONFIG_FILE.resolve()}[/dim]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="updater",
        description="Fabric server and mod updater",
    )
    parser.add_argument("--server-dir", metavar="PATH", help="Override server directory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done, no downloads")
    parser.add_argument("--yes", "-y", action="store_true", help="Apply all updates without prompting")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--include-snapshots", action="store_true", help="Include snapshot MC versions")
    parser.add_argument("--config-file", metavar="PATH", default=str(cfg_module.CONFIG_FILE),
                        help="Config file path (default: updater_config.json)")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Show available updates, no downloads")
    sub.add_parser("update", help="Interactive full update (default)")
    sub.add_parser("update-fabric", help="Update Fabric server JAR only")
    sub.add_parser("update-mods", help="Update Modrinth mods only")

    mc = sub.add_parser("check-mc", help="Check if all mods support a given MC version")
    mc.add_argument("version", help="Target Minecraft version, e.g. 1.21.4")
    mc.add_argument(
        "--force-compatible",
        metavar="FILENAME",
        action="append",
        default=[],
        help="Mark a mod file as compatible (can be used multiple times)",
    )

    umc = sub.add_parser("update-mc", help="Switch to a new MC version and update all mods + Fabric JAR")
    umc.add_argument("version", help="Target Minecraft version, e.g. 1.21.4")

    sub.add_parser("config", help="Show current configuration")

    return parser


async def main(args: argparse.Namespace, config: cfg_module.Config) -> None:
    command = args.command or "update"

    if command == "check":
        await cmd_check(args, config)
    elif command == "update":
        await cmd_update(args, config)
    elif command == "update-fabric":
        await cmd_update(args, config, fabric_only=True)
    elif command == "update-mods":
        await cmd_update(args, config, mods_only=True)
    elif command == "check-mc":
        await cmd_check_mc(args, config)
    elif command == "update-mc":
        await cmd_update_mc(args, config)
    elif command == "config":
        await cmd_config(args, config)
    else:
        build_parser().print_help()


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    if args.no_color:
        console._force_terminal = False

    config_path = Path(args.config_file)
    try:
        config = cfg_module.load_or_create_config(config_path)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        sys.exit(0)

    if args.server_dir:
        config.server_dir = Path(args.server_dir).expanduser().resolve()

    try:
        asyncio.run(main(args, config))
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        sys.exit(0)
