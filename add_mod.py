#!/usr/bin/env python3
"""Add mods from Modrinth to your Fabric server by project ID or slug."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

from lib import config as cfg_module
from lib import modrinth as modrinth_mod
from lib import downloader as dl_mod

console = Console()


def _make_client(user_agent: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=30.0,
        follow_redirects=True,
    )


def _primary_file(version: dict) -> dict | None:
    files = version.get("files", [])
    return next((f for f in files if f.get("primary")), files[0] if files else None)


async def resolve_mods(
    client: httpx.AsyncClient,
    slugs: list[str],
    mc_version: str,
) -> list[tuple[dict, dict]]:
    """Return (project, version) pairs for each slug that has a compatible release."""
    results = []
    for slug in slugs:
        with console.status(f"[cyan]Looking up {slug}…[/cyan]"):
            try:
                project = await modrinth_mod.get_project(client, slug)
                version = await modrinth_mod.get_latest_version_for_project(client, slug, mc_version)
            except httpx.HTTPStatusError as e:
                console.print(f"[red]✗ '{slug}' not found on Modrinth[/red] ({e.response.status_code})")
                continue
            except (httpx.HTTPError, KeyError) as e:
                console.print(f"[red]✗ Could not fetch '{slug}':[/red] {e}")
                continue

        if version is None:
            console.print(
                f"[yellow]⚠[/yellow] No Fabric release for [bold]{project['title']}[/bold] "
                f"on MC {mc_version}."
            )
            continue

        file = _primary_file(version)
        if file is None:
            console.print(f"[red]✗ No downloadable file for '{project['title']}'.[/red]")
            continue

        console.print(
            f"  [bold]{project['title']}[/bold]  {version['version_number']}  "
            f"([dim]{file['filename']}[/dim])"
        )
        results.append((project, version))

    return results


async def download_mods(
    client: httpx.AsyncClient,
    mods_dir: Path,
    to_download: list[tuple[dict, dict]],
) -> None:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        for project, version in to_download:
            file = _primary_file(version)
            dest = mods_dir / file["filename"]
            sha512 = file.get("hashes", {}).get("sha512", "")
            task = progress.add_task(f"{project['title']} {version['version_number']}", total=None)

            try:
                await dl_mod.download_file(client, file["url"], dest, sha512, progress, task)
                console.print(f"[green]✓[/green] Installed [bold]{project['title']}[/bold] → {dest.name}")
            except ValueError as e:
                console.print(f"[red]✗ Hash mismatch for {project['title']}:[/red] {e}")
            except (httpx.HTTPError, OSError) as e:
                console.print(f"[red]✗ Failed to download {project['title']}:[/red] {e}")


async def main(args: argparse.Namespace, config: cfg_module.Config) -> None:
    mods_dir = config.server_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)

    async with _make_client(config.user_agent) as client:
        to_download = await resolve_mods(client, args.project_ids, config.minecraft_version)

        if not to_download:
            return

        if not args.yes:
            import questionary
            ok = await questionary.confirm("Download and install these mods?", default=True).ask_async()
            if not ok:
                console.print("[yellow]Cancelled.[/yellow]")
                return

        await download_mods(client, mods_dir, to_download)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="add_mod",
        description="Add mods from Modrinth to your Fabric server.",
    )
    parser.add_argument(
        "project_ids",
        nargs="+",
        metavar="PROJECT",
        help="Modrinth project ID or slug (e.g. 'fabric-api' or 'P7dR8mSH')",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument(
        "--config-file",
        metavar="PATH",
        default=str(cfg_module.CONFIG_FILE),
        help="Config file path (default: updater_config.json)",
    )
    parser.add_argument("--server-dir", metavar="PATH", help="Override server directory")
    return parser


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
