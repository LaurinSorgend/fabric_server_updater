# Fabric Server Updater

A CLI tool to keep your Fabric Minecraft server up to date - server JAR and mods.

## Requirements

- Python 3.11+
- Mods must be from [Modrinth](https://modrinth.com) to be auto-updated

## Setup

```bash
pip install -r requirements.txt
python updater.py
```

On first run you'll be prompted for your target type (server or client instance) and directory. Config is saved to `updater_config.json`.

For **Prism/MultiMC client instances**, point to the `.minecraft` directory inside the instance folder. The MC version will be auto-detected from `mmc-pack.json` if present.

## Usage

```bash
python updater.py check              # show available updates, no downloads
python updater.py update             # interactive update (pick what to apply)
python updater.py update --yes       # apply all updates without prompting
python updater.py update-fabric      # update Fabric server JAR only
python updater.py update-mods        # update mods only
python updater.py check-mc 1.21.4    # check if all mods support a MC version
python updater.py check-mc 1.21.4 --force-compatible mymod-1.0.jar  # mark a mod as compatible
python updater.py config             # show current config
```

Global flags: `--dry-run`, `--server-dir PATH`, `--no-color`

## Adding Mods

```bash
python add_mod.py fabric-api          # by slug
python add_mod.py P7dR8mSH            # by Modrinth project ID
python add_mod.py fabric-api --yes    # skip confirmation
```

## Notes

- A timestamped backup is created in `backups/` before any files are changed
- Mods not from Modrinth are listed but never modified
- To manually associate a mod file with a Modrinth project, add it to the `overrides` section in `updater_config.json`:
  ```json
  "overrides": {
    "some-mod-1.0.jar": "modrinth-project-id"
  }
  ```
- To permanently mark a mod as compatible with specific MC versions (e.g. for mods not on Modrinth), add it to `mc_compat_overrides`. Use `"*"` to mark it as compatible with all versions:
  ```json
  "mc_compat_overrides": {
    "some-mod-1.0.jar": ["1.21.4"],
    "another-mod.jar": ["*"]
  }
  ```
