"""
State persistence and rollback backup manager for Audeze Maxwell 2 settings and EQ profiles.
Ensures every write is preceded by an immutable backup snapshot.
"""

import os
import json
import time
from typing import Dict, Any, List, Optional

DEFAULT_CONFIG_DIR = os.path.expanduser("~/.config/maxwell2")
DEFAULT_BACKUP_DIR = os.path.join(DEFAULT_CONFIG_DIR, "backups")


def get_backup_dir() -> str:
    """Returns the backup directory path, creating it if necessary."""
    backup_dir = os.environ.get("MAXWELL2_BACKUP_DIR", DEFAULT_BACKUP_DIR)
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def create_backup(action_name: str, state_data: Dict[str, Any]) -> str:
    """
    Saves a timestamped JSON backup file before applying any write.
    Returns the absolute path to the created backup file.
    """
    backup_dir = get_backup_dir()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    clean_action = "".join(c if c.isalnum() or c in "-_" else "_" for c in action_name)
    filename = f"backup_{clean_action}_{timestamp}.json"
    filepath = os.path.join(backup_dir, filename)

    payload = {
        "action": action_name,
        "timestamp": timestamp,
        "created_at_epoch": time.time(),
        "state": state_data,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return filepath


def list_backups() -> List[Dict[str, Any]]:
    """Returns a list of available backups sorted from newest to oldest."""
    backup_dir = get_backup_dir()
    backups = []
    for fname in sorted(os.listdir(backup_dir), reverse=True):
        if fname.endswith(".json") and fname.startswith("backup_"):
            fpath = os.path.join(backup_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                backups.append({
                    "filename": fname,
                    "filepath": fpath,
                    "action": data.get("action", "unknown"),
                    "timestamp": data.get("timestamp", "unknown"),
                })
            except Exception:
                continue
    return backups


def load_backup(filepath: str) -> Dict[str, Any]:
    """Loads a backup file."""
    if not os.path.exists(filepath):
        # Check if only the filename was given
        candidate = os.path.join(get_backup_dir(), filepath)
        if os.path.exists(candidate):
            filepath = candidate
        else:
            raise FileNotFoundError(f"Backup file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)
