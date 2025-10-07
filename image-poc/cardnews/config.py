"""Configuration helpers for Cardnews CLI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

CONFIG_ENV_VAR = "CARDNEWS_CONFIG_PATH"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = "config.yaml"
LEGACY_CONFIG_PATH = Path.home() / ".config" / "cardnews" / DEFAULT_CONFIG_FILE

DEFAULT_CONFIG: Dict[str, Any] = {
    "fonts": {
        "title": {
            "path": "Pretendard-Bold.otf",
            "size": 72,
        },
        "subtitle": {
            "path": "Pretendard-Regular.otf",
            "size": 42,
        },
        "business": {
            "path": "Pretendard-Regular.otf",
            "size": 36,
        },
    },
    "image": {
        "width": 1080,
        "height": 1080,
        "overlay": True,
    },
    "gemini": {
        "model": "nanobanana",
        "image_model": "nanobanana-image",
    },
    "figma": {
        "file_key": "",
        "frame_id": "",
        "nodes": {
            "title": "",
            "subtitle": "",
            "business": "",
        },
        "names": {
            "title": "",
            "subtitle": "",
            "business": "",
        },
        "background_nodes": [],
        "background_names": [],
        "scale": 1.0,
        "format": "png",
        "clear_background": False,
    },
}


def _get_config_path() -> Path:
    """Resolve the primary config file path inside the project workspace."""
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        path = Path(override).expanduser()
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        path.mkdir(parents=True, exist_ok=True)
        return path / DEFAULT_CONFIG_FILE

    target = PACKAGE_ROOT / DEFAULT_CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


CONFIG_PATH = _get_config_path()


def load_config() -> Dict[str, Any]:
    """Load configuration from disk, falling back to defaults."""
    data = _load_yaml(CONFIG_PATH)
    if data is None:
        legacy = _load_yaml(LEGACY_CONFIG_PATH)
        data = legacy if legacy is not None else {}

    return _deep_merge_dicts(DEFAULT_CONFIG, data)


def save_config(config: Dict[str, Any]) -> None:
    """Persist configuration to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, sort_keys=True, allow_unicode=True)


def update_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Apply updates to the current configuration and save the result."""
    current = load_config()
    merged = _deep_merge_dicts(current, updates)
    save_config(merged)
    return merged


def _load_yaml(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
            if isinstance(loaded, dict):
                return loaded
            raise RuntimeError(f"Invalid configuration structure at {path}; expected a mapping.")
    except yaml.YAMLError as err:
        raise RuntimeError(f"Invalid configuration at {path}: {err}") from err


def _deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries without mutating inputs."""
    result: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result
