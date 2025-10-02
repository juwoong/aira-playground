"""Input parsing utilities."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def load_card(path: str) -> Dict[str, str]:
    """Load a single card definition from JSON."""
    data = _load_json(Path(path))
    if not isinstance(data, dict):
        raise ValueError("Card definition must be a JSON object with title/subtitle/image_prompt.")
    return {k: str(v) for k, v in data.items() if v is not None}


def load_cards(path: str) -> List[Dict[str, str]]:
    """Load multiple cards from JSON array or CSV."""
    file_path = Path(path)
    if file_path.suffix.lower() == ".csv":
        return list(_load_csv(file_path))
    data = _load_json(file_path)
    if isinstance(data, list):
        return [{k: str(v) for k, v in item.items() if v is not None} for item in data]
    if isinstance(data, dict):
        return [{k: str(v) for k, v in data.items() if v is not None}]
    raise ValueError("Unsupported input structure. Provide JSON array/object or CSV file.")


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_csv(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            yield {k: v for k, v in row.items() if v}


__all__ = ["load_card", "load_cards"]
