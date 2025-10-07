"""Gemini API helpers for text and image generation."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from PIL import Image

try:  # pragma: no cover - import guarded for optional dependency
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - handled gracefully at runtime
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]

DEFAULT_TEXT_MODEL = "nanobanana"
DEFAULT_IMAGE_MODEL = "nanobanana-image"
ENV_API_KEY = "GEMINI_API_KEY"

MODEL_ALIASES = {
    "nanobanana": "gemini-2.0-flash",
    "nanobanana-image": "gemini-2.5-flash-image",
}


class GeminiNotConfigured(RuntimeError):
    """Raised when Gemini integration is requested but not configured."""


def get_api_key() -> Optional[str]:
    """Return the Gemini API key, attempting to load from a `.env` file if needed."""
    key = os.environ.get(ENV_API_KEY)
    if key:
        return key

    for env_path in _candidate_env_paths():
        if env_path.exists():
            parsed = _parse_env_file(env_path)
            key = parsed.get(ENV_API_KEY)
            if key:
                os.environ[ENV_API_KEY] = key
                return key
    return None


def generate_cards(
    topic: str,
    count: int,
    style: Optional[str],
    *,
    model_name: str = DEFAULT_TEXT_MODEL,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return card content suggestions, falling back to canned templates on failure."""
    key = api_key or get_api_key()
    if key and genai is not None and types is not None:
        try:
            client = _get_client(key)
            resolved_model = _resolve_model_name(model_name)
            response = client.models.generate_content(
                model=resolved_model,
                contents=[_build_text_prompt(topic=topic, count=count, style=style)],
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            payload = _extract_text(response)
            if payload:
                data = json.loads(payload)
                if isinstance(data, list):
                    return [_normalise_item(item) for item in data][:count]
        except Exception:  # pragma: no cover - remote API variances
            pass

    return _fallback_cards(topic, count, style)


def generate_background_image(
    prompt: str,
    *,
    aspect_ratio: str,
    model_name: str = DEFAULT_IMAGE_MODEL,
    api_key: Optional[str] = None,
) -> Image.Image:
    """Generate a Nanobanana-style background image with Gemini."""
    key = api_key or get_api_key()
    if not key:
        raise GeminiNotConfigured("Gemini API key is not configured. Set GEMINI_API_KEY or .env entry.")
    if genai is None or types is None:
        raise GeminiNotConfigured("google-genai package is not available; install google-genai.")

    client = _get_client(key)
    resolved_model = _resolve_model_name(model_name)
    response = client.models.generate_content(
        model=resolved_model,
        contents=[_build_image_prompt(prompt)],
        config=types.GenerateContentConfig(
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        ),
    )

    for part in _iter_parts(response):
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            image = Image.open(BytesIO(inline.data))
            return image.convert("RGB")
    raise RuntimeError("Gemini response did not include image data.")


def _build_text_prompt(topic: str, count: int, style: Optional[str]) -> str:
    style_text = f" in the style of {style}" if style else ""
    return (
        "You are a Korean social media copywriter. Create concise Instagram card content. "
        "Respond strictly with JSON: an array of objects containing title, subtitle, and image_prompt. "
        f"Topic: {topic}.{style_text}\n"
        f"Generate {count} unique entries."
    )


def _build_image_prompt(prompt: str) -> str:
    base = (
        "Create a Nanobanana-inspired abstract background suitable for an Instagram card. "
        "Use smooth gradients, soft lighting, and keep the composition free of text or logos."
    )
    prompt = prompt.strip()
    if prompt:
        base += f" Incorporate the following concepts: {prompt}."
    return base


def _extract_text(response: Any) -> Optional[str]:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    for part in _iter_parts(response):
        candidate_text = getattr(part, "text", None)
        if isinstance(candidate_text, str) and candidate_text.strip():
            return candidate_text
    return None


def _iter_parts(response: Any) -> Iterable[Any]:
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            yield part


def _normalise_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": str(item.get("title", "")),
        "subtitle": str(item.get("subtitle", "")),
        "image_prompt": str(item.get("image_prompt", "")),
    }


def _fallback_cards(topic: str, count: int, style: Optional[str]) -> List[Dict[str, Any]]:
    templates = [
        ("오늘의 통찰", "{topic}에 관한 짧은 생각", "Nanobanana gradient, modern, {topic}"),
        ("하루 한 걸음", "{topic} 실천 팁", "Nanobanana pastel blend, inspirational, {topic}"),
        ("기억해둘 말", "{topic}에 대한 핵심 메시지", "Nanobanana glow, vibrant, {topic}"),
    ]
    results: List[Dict[str, Any]] = []
    for index in range(count):
        title_tpl, subtitle_tpl, prompt_tpl = templates[index % len(templates)]
        results.append(
            {
                "title": title_tpl.format(topic=topic, style=style or ""),
                "subtitle": subtitle_tpl.format(topic=topic, style=style or ""),
                "image_prompt": prompt_tpl.format(topic=topic, style=style or ""),
            }
        )
    return results


def _candidate_env_paths() -> Iterable[Path]:
    cwd = Path.cwd()
    yield cwd / ".env"
    try:
        package_root = Path(__file__).resolve().parent.parent
    except Exception:  # pragma: no cover - defensive
        package_root = cwd
    yield package_root / ".env"


def _parse_env_file(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[key] = value
    except OSError:
        pass
    return result


def _resolve_model_name(model: str) -> str:
    actual = MODEL_ALIASES.get(model.lower()) if isinstance(model, str) else None
    return actual or model


@lru_cache(maxsize=2)
def _get_client(api_key: str):  # pragma: no cover - thin wrapper
    if genai is None:
        raise GeminiNotConfigured("google-genai package is not available; install google-genai.")
    return genai.Client(api_key=api_key)


__all__ = [
    "generate_cards",
    "generate_background_image",
    "get_api_key",
    "GeminiNotConfigured",
    "DEFAULT_TEXT_MODEL",
    "DEFAULT_IMAGE_MODEL",
]
