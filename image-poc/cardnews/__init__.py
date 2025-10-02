"""Cardnews CLI package."""

from importlib import metadata


def get_version() -> str:
    """Return the package version, or '0.0.0' if metadata is unavailable."""
    try:
        return metadata.version("cardnews-cli")
    except metadata.PackageNotFoundError:  # pragma: no cover - during local dev
        return "0.0.0"


__all__ = ["get_version"]
