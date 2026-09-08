from __future__ import annotations

import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import settings


def _sqlite_path() -> Path:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        raise RuntimeError("The built-in backup command currently supports the SQLite pilot database only")
    return Path(settings.database_url[len(prefix):]).resolve()


def create_backup(destination: str | Path | None = None) -> Path:
    source_db = _sqlite_path()
    if not source_db.exists():
        raise RuntimeError(f"Database not found: {source_db}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_path = Path(destination) if destination else settings.data_dir / "backups" / f"rmr-platform-{timestamp}.tar.gz"
    destination_path = destination_path.resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="rmr-backup-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        snapshot_db = temp_dir / "rmr_platform.db"
        source = sqlite3.connect(source_db)
        target = sqlite3.connect(snapshot_db)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        training_source = settings.data_dir / "training"
        if training_source.exists():
            shutil.copytree(training_source, temp_dir / "training", dirs_exist_ok=True)
        manifest = {
            "product": "RMR Platform",
            "version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": "sqlite",
            "database_file": "rmr_platform.db",
            "training_directory": "training",
        }
        (temp_dir / "backup-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with tarfile.open(destination_path, "w:gz") as archive:
            archive.add(temp_dir / "backup-manifest.json", arcname="backup-manifest.json")
            archive.add(snapshot_db, arcname="rmr_platform.db")
            if (temp_dir / "training").exists():
                archive.add(temp_dir / "training", arcname="training")
    return destination_path


def restore_backup(source: str | Path) -> Path:
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise RuntimeError(f"Backup not found: {source_path}")
    database_path = _sqlite_path()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rmr-restore-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        with tarfile.open(source_path, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                member_path = (temp_dir / member.name).resolve()
                if temp_dir.resolve() not in member_path.parents and member_path != temp_dir.resolve():
                    raise RuntimeError("Backup contains an unsafe path")
            archive.extractall(temp_dir)
        manifest_path = temp_dir / "backup-manifest.json"
        restored_db = temp_dir / "rmr_platform.db"
        if not manifest_path.exists() or not restored_db.exists():
            raise RuntimeError("Backup is missing its manifest or database snapshot")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("product") != "RMR Platform" or manifest.get("database") != "sqlite":
            raise RuntimeError("Backup is not a compatible RMR Platform SQLite backup")
        if database_path.exists():
            safety = create_backup(settings.data_dir / "backups" / f"pre-restore-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.tar.gz")
        else:
            safety = source_path
        temp_target = database_path.with_suffix(".restore.tmp")
        shutil.copy2(restored_db, temp_target)
        temp_target.replace(database_path)
        training_target = settings.data_dir / "training"
        restored_training = temp_dir / "training"
        if restored_training.exists():
            if training_target.exists():
                shutil.rmtree(training_target)
            shutil.copytree(restored_training, training_target)
        training_target.mkdir(parents=True, exist_ok=True)
    return safety
