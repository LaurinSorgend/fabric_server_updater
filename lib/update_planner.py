from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .mod_scanner import ModInfo


@dataclass
class FabricUpdate:
    current_loader: str
    latest_loader: str
    current_installer: str
    latest_installer: str
    mc_version: str
    download_url: str
    is_update: bool  # True if loader or installer changed


@dataclass
class ModUpdate:
    mod: ModInfo
    latest_version_number: str
    latest_version_id: str
    download_url: str
    file_sha512: str
    changelog: str
    is_update: bool  # False = already up-to-date


@dataclass
class UpdatePlan:
    fabric_update: Optional[FabricUpdate]
    mod_updates: list[ModUpdate] = field(default_factory=list)
    unknown_mods: list[ModInfo] = field(default_factory=list)
    mc_upgrade_possible: Optional[bool] = None
    mc_upgrade_blockers: list[ModInfo] = field(default_factory=list)

    @property
    def available_mod_updates(self) -> list[ModUpdate]:
        return [u for u in self.mod_updates if u.is_update]


def build_plan(
    mods: list[ModInfo],
    latest_versions: dict[str, dict],   # sha512 -> version_object from Modrinth
    current_loader: str,
    latest_loader: str,
    current_installer: str,
    latest_installer: str,
    mc_version: str,
    fabric_jar_url: str,
    compat_results: dict[str, bool] | None = None,
    candidate_mc_version: str | None = None,
) -> UpdatePlan:
    """
    Pure function. Combines all gathered data into an UpdatePlan.
    No I/O.
    """
    fabric_is_update = (
        current_loader != latest_loader or current_installer != latest_installer
    )
    fabric_update = FabricUpdate(
        current_loader=current_loader,
        latest_loader=latest_loader,
        current_installer=current_installer,
        latest_installer=latest_installer,
        mc_version=mc_version,
        download_url=fabric_jar_url,
        is_update=fabric_is_update,
    )

    mod_updates: list[ModUpdate] = []
    unknown_mods: list[ModInfo] = []

    for mod in mods:
        if mod.source != "modrinth":
            unknown_mods.append(mod)
            continue

        latest = latest_versions.get(mod.sha512)
        if latest is None:
            # No update found for this MC version — still list it
            mod_updates.append(
                ModUpdate(
                    mod=mod,
                    latest_version_number=mod.installed_version,
                    latest_version_id=mod.modrinth_version_id or "",
                    download_url="",
                    file_sha512="",
                    changelog="",
                    is_update=False,
                )
            )
            continue

        latest_vid = latest.get("id", "")
        is_update = latest_vid != mod.modrinth_version_id

        # Get primary file info
        files = latest.get("files", [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else {})
        download_url = primary.get("url", "")
        file_sha512 = primary.get("hashes", {}).get("sha512", "")

        mod_updates.append(
            ModUpdate(
                mod=mod,
                latest_version_number=latest.get("version_number", ""),
                latest_version_id=latest_vid,
                download_url=download_url,
                file_sha512=file_sha512,
                changelog=latest.get("changelog") or "",
                is_update=is_update,
            )
        )

    # MC upgrade compat
    mc_upgrade_possible: Optional[bool] = None
    blockers: list[ModInfo] = []

    if compat_results is not None and candidate_mc_version:
        mc_upgrade_possible = True
        for mod in mods:
            if mod.source != "modrinth" or not mod.modrinth_project_id:
                continue
            if not compat_results.get(mod.modrinth_project_id, False):
                mc_upgrade_possible = False
                blockers.append(mod)

    return UpdatePlan(
        fabric_update=fabric_update,
        mod_updates=mod_updates,
        unknown_mods=unknown_mods,
        mc_upgrade_possible=mc_upgrade_possible,
        mc_upgrade_blockers=blockers,
    )
