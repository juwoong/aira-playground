"""Gemini API helpers for content generation."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - dependency installed via packaging
    genai = None

DEFAULT_MODEL = "models/gemini-1.5-pro"
ENV_API_KEY = "GEMINI_API_KEY"


class GeminiNotConfigured(RuntimeError):
    """Raised when Gemini integration is requested but not configured."""


def get_api_key() -> Optional[str]:
    return os.environ.get(ENV_API_KEY)


def ensure_client(api_key: Optional[str]) -> None:
    if not api_key:
        raise GeminiNotConfigured("Gemini API key is not configured. Set GEMINI_API_KEY.")
    if genai is None:
        raise GeminiNotConfigured("google-generativeai package is not available.")
    genai.configure(api_key=api_key)


def generate_cards(
    topic: str,
    count: int,
    style: Optional[str],
    model_name: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Generate card content using Gemini, with a graceful fallback."""
    if api_key and genai is not None:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                _build_prompt(topic=topic, count=count, style=style),
                generation_config={"response_mime_type": "application/json"},
            )
            payload = _extract_json(response)
            if isinstance(payload, list):
                return [_normalise_item(item) for item in payload][:count]
        except Exception:  # pragma: no cover - external API variability
            pass

    return _fallback_cards(topic, count, style)


def _build_prompt(topic: str, count: int, style: Optional[str]) -> str:
    style_text = f" in the style of {style}" if style else ""
    return (
        "You are a Korean social media copywriter. Create brief Instagram card content. "
        "Respond strictly with JSON: an array of objects containing title, subtitle, and image_prompt. "
        f"Topic: {topic}.{style_text}\n"
        f"Generate {count} unique entries."
    )


def _extract_json(response: Any) -> Any:
    if hasattr(response, "text") and response.text:
        candidate = response.text
    elif getattr(response, "candidates", None):
        candidate = response.candidates[0].content.parts[0].text
    else:  # pragma: no cover
        return None

    candidate = candidate.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        parts = candidate.split("\n", 1)
        candidate = parts[1] if len(parts) > 1 else parts[0]
    return json.loads(candidate)


def _normalise_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": item.get("title", ""),
        "subtitle": item.get("subtitle", ""),
        "image_prompt": item.get("image_prompt", ""),
    }


def _fallback_cards(topic: str, count: int, style: Optional[str]) -> List[Dict[str, Any]]:
    templates = [
        ("오늘의 통찰", "{topic}에 관한 짧은 생각", "minimal gradient, modern, {topic}"),
        ("하루 한 걸음", "{topic} 실천 팁", "soft lighting, inspirational, {topic}"),
        ("기억해둘 말", "{topic}에 대한 핵심 메시지", "bold typography, vibrant, {topic}"),
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


__all__ = ["generate_cards", "get_api_key", "GeminiNotConfigured", "DEFAULT_MODEL"]
