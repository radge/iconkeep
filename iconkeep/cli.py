from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import sys
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

APP_SEARCH_DIRS = [
    Path("/Applications"),
    Path("/System/Applications"),
    Path("~/Applications").expanduser(),
]


class IconkeepError(Exception):
    pass


@dataclass(frozen=True)
class BackupRecord:
    app_path: str
    bundle_id: str | None
    display_name: str
    icon_relpath: str
    backup_path: str
    timestamp: str


def _xdg_dir(env_var: str, default: Path) -> Path:
    return Path(os.environ.get(env_var, default)).expanduser()


def data_dir() -> Path:
    return _xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share") / "iconkeep" / "backups"


def cache_dir() -> Path:
    return _xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache") / "iconkeep"


def state_dir() -> Path:
    return _xdg_dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / "iconkeep"


def config_dir() -> Path:
    return _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config") / "iconkeep"


def load_app_list() -> list[str]:
    config_path = config_dir() / "apps"
    if not config_path.exists():
        raise IconkeepError(f"Missing app list at {config_path}")

    apps: list[str] = []
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        apps.append(line)

    if not apps:
        raise IconkeepError(f"No apps listed in {config_path}")

    return apps


def normalize_app_name(name: str) -> str:
    if name.lower().endswith(".app"):
        name = name[:-4]
    return name.strip().lower()


def find_app_bundle(app_name: str) -> Path:
    candidate = Path(app_name).expanduser()
    if candidate.exists():
        if candidate.suffix == ".app":
            return candidate
        for parent in candidate.parents:
            if parent.suffix == ".app":
                return parent
        raise IconkeepError(f"{app_name!r} exists but is not inside an .app bundle")

    target = normalize_app_name(app_name)
    for root in APP_SEARCH_DIRS:
        if not root.exists():
            continue
        for app in root.rglob("*.app"):
            if normalize_app_name(app.name) == target:
                return app
    raise IconkeepError(f"Could not find app bundle for {app_name!r}")


def read_info_plist(app_path: Path) -> dict:
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        raise IconkeepError(f"Missing Info.plist at {plist_path}")
    with plist_path.open("rb") as handle:
        return plistlib.load(handle)


def _icon_candidates(info: dict) -> Iterable[str]:
    icon_file = info.get("CFBundleIconFile")
    if icon_file:
        yield icon_file

    icon_files = info.get("CFBundleIconFiles")
    if isinstance(icon_files, list):
        for entry in icon_files:
            if entry:
                yield entry

    icons = info.get("CFBundleIcons")
    if isinstance(icons, dict):
        primary = icons.get("CFBundlePrimaryIcon")
        if isinstance(primary, dict):
            primary_files = primary.get("CFBundleIconFiles")
            if isinstance(primary_files, list):
                for entry in primary_files:
                    if entry:
                        yield entry


def resolve_icon_path(app_path: Path, info: dict) -> Path:
    resources = app_path / "Contents" / "Resources"
    for candidate in _icon_candidates(info):
        candidate_path = resources / candidate
        if candidate_path.suffix == "":
            candidate_path = candidate_path.with_suffix(".icns")
        if candidate_path.exists():
            return candidate_path

    icns_files = sorted(resources.glob("*.icns")) if resources.exists() else []
    if icns_files:
        return icns_files[0]

    raise IconkeepError("Could not locate an .icns icon file for this app")


def manifest_path_for(slug: str) -> Path:
    return data_dir() / slug / "manifest.json"


def slug_for(app_path: Path, bundle_id: str | None) -> str:
    if bundle_id:
        return bundle_id
    return app_path.stem


def write_manifest(record: BackupRecord) -> None:
    manifest_path = Path(record.backup_path).parent / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(record), handle, indent=2, sort_keys=True)


def load_manifest(paths: Iterable[Path]) -> BackupRecord:
    for path in paths:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return BackupRecord(**data)
    raise IconkeepError("No backup manifest found for this app")


def backup(app_name: str) -> None:
    app_path = find_app_bundle(app_name)
    info = read_info_plist(app_path)
    bundle_id = info.get("CFBundleIdentifier")
    display_name = info.get("CFBundleName") or app_path.stem
    icon_path = resolve_icon_path(app_path, info)

    slug = slug_for(app_path, bundle_id)
    backup_root = data_dir() / slug
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_icon_path = backup_root / "icon.icns"

    shutil.copy2(icon_path, backup_icon_path)

    record = BackupRecord(
        app_path=str(app_path),
        bundle_id=bundle_id,
        display_name=display_name,
        icon_relpath=str(icon_path.relative_to(app_path)),
        backup_path=str(backup_icon_path),
        timestamp=datetime.utcnow().isoformat() + "Z",
    )
    write_manifest(record)

    print(f"Backed up icon for {display_name} -> {backup_icon_path}")


def restore(app_name: str) -> None:
    app_path = find_app_bundle(app_name)
    info = read_info_plist(app_path)
    bundle_id = info.get("CFBundleIdentifier")

    possible_manifests = [
        manifest_path_for(bundle_id) if bundle_id else None,
        manifest_path_for(app_path.stem),
        manifest_path_for(normalize_app_name(app_name)),
    ]
    manifest = load_manifest(path for path in possible_manifests if path)

    backup_icon_path = Path(manifest.backup_path)
    if not backup_icon_path.exists():
        raise IconkeepError(f"Backup icon not found at {backup_icon_path}")

    icon_target = app_path / manifest.icon_relpath
    icon_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_icon_path, icon_target)

    print(f"Restored icon for {manifest.display_name} -> {icon_target}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iconkeep",
        description="Back up and restore macOS application icons.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="Back up an app icon.")
    backup_parser.add_argument(
        "app",
        nargs="?",
        help="Application name or path to .app bundle (omit to use config list)",
    )

    restore_parser = subparsers.add_parser("restore", help="Restore an app icon.")
    restore_parser.add_argument(
        "app",
        nargs="?",
        help="Application name or path to .app bundle (omit to use config list)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "backup":
            if args.app:
                backup(args.app)
            else:
                failures = []
                for app in load_app_list():
                    try:
                        backup(app)
                    except IconkeepError as exc:
                        failures.append((app, exc))
                if failures:
                    for app, exc in failures:
                        print(f"Error: {app}: {exc}", file=sys.stderr)
                    sys.exit(1)
        elif args.command == "restore":
            if args.app:
                restore(args.app)
            else:
                failures = []
                for app in load_app_list():
                    try:
                        restore(app)
                    except IconkeepError as exc:
                        failures.append((app, exc))
                if failures:
                    for app, exc in failures:
                        print(f"Error: {app}: {exc}", file=sys.stderr)
                    sys.exit(1)
        else:
            parser.error("Unknown command")
    except IconkeepError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
