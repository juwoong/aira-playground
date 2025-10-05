"""Utilities for composing card news images."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

Gradient = Sequence[Tuple[int, int, int]]


@dataclass
class FontSpec:
    path: Optional[str]
    size: int


@dataclass
class RenderOptions:
    width: int = 1080
    height: int = 1080
    add_overlay: bool = True
    shadow: bool = True


@dataclass
class TextSpec:
    title: str
    subtitle: str
    title_font: FontSpec
    subtitle_font: FontSpec


@dataclass
class TextBlock:
    text: str
    font: FontSpec
    box: Tuple[int, int, int, int]
    fill: Optional[Tuple[int, int, int]] = None


def create_card(
    title: str,
    subtitle: str,
    prompt: Optional[str],
    background_path: Optional[str],
    fonts: Tuple[FontSpec, FontSpec],
    options: RenderOptions,
    background_image: Optional[Image.Image] = None,
) -> Image.Image:
    """Create a composed card image."""
    target = min(options.width, options.height)
    target_size = (target, target)

    if background_image is not None:
        background = ensure_square(background_image).resize(target_size, Image.LANCZOS)
    elif background_path:
        background = load_background(background_path, target_size)
    else:
        background = generate_prompt_gradient(prompt, target_size)

    background = background.convert("RGBA")

    if options.add_overlay:
        overlay = Image.new("RGBA", background.size, (0, 0, 0, 96))
        background = Image.alpha_composite(background, overlay)

    title_font = load_font(fonts[0])
    subtitle_font = load_font(fonts[1])

    text_color = pick_text_color(background)

    canvas = background.copy()
    draw = ImageDraw.Draw(canvas)

    _draw_text_block(
        draw,
        title,
        title_font,
        box=(0, 0, canvas.width, int(canvas.height * 0.40)),
        fill=text_color,
        shadow=options.shadow,
    )
    _draw_text_block(
        draw,
        subtitle,
        subtitle_font,
        box=(0, int(canvas.height * 0.38), canvas.width, int(canvas.height * 0.75)),
        fill=text_color,
        shadow=options.shadow,
    )

    return canvas.convert("RGB")


def draw_text_blocks(
    image: Image.Image,
    blocks: Sequence[TextBlock],
    *,
    shadow: bool = True,
    default_fill: Optional[Tuple[int, int, int]] = None,
) -> Image.Image:
    """Render multiple text blocks onto a copy of the image."""

    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)

    for block in blocks:
        if not block.text:
            continue

        font = load_font(block.font)
        fill = block.fill or default_fill or pick_text_color(canvas)

        _draw_text_block(
            draw,
            block.text,
            font,
            box=block.box,
            fill=fill,
            shadow=shadow,
        )

    return canvas


def load_background(path: str, size: Tuple[int, int]) -> Image.Image:
    """Load a background image from disk and resize it."""
    image = Image.open(path)
    image = ensure_square(image.convert("RGB"))
    return image.resize(size, Image.LANCZOS)


def generate_prompt_gradient(prompt: Optional[str], size: Tuple[int, int]) -> Image.Image:
    """Generate a deterministic gradient background from a prompt."""
    colors = _prompt_to_gradient(prompt or "default gradient")
    return linear_gradient(size, colors)


def load_font(spec: FontSpec) -> ImageFont.FreeTypeFont:
    """Load a font from the given spec, falling back to a default font."""
    if spec.path:
        try:
            return ImageFont.truetype(spec.path, spec.size)
        except OSError:
            pass
    fallback_fonts = [
        "Pretendard-Bold.otf",
        "Pretendard-SemiBold.otf",
        "Pretendard-Regular.otf",
        "Pretendard.ttf",
        "Pretendard.otf",
        "Arial.ttf",
        "arial.ttf",
    ]
    for candidate in fallback_fonts:
        try:
            return ImageFont.truetype(candidate, spec.size)
        except OSError:
            continue
    return ImageFont.load_default()


def pick_text_color(image: Image.Image) -> Tuple[int, int, int]:
    """Pick a readable text color based on average luminance."""
    grayscale = image.convert("L")
    sample = grayscale.resize((10, 10), Image.BOX)
    avg = sum(sample.getdata()) / 100.0
    return (20, 20, 20) if avg > 160 else (240, 240, 240)


def linear_gradient(size: Tuple[int, int], colors: Gradient) -> Image.Image:
    """Create a vertical linear gradient with optional blur blend."""
    width, height = size
    base = Image.new("RGB", size)
    draw = ImageDraw.Draw(base)
    top, bottom = colors[0], colors[-1]
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(top[0] * (1 - ratio) + bottom[0] * ratio)
        g = int(top[1] * (1 - ratio) + bottom[1] * ratio)
        b = int(top[2] * (1 - ratio) + bottom[2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    if len(colors) > 2:
        overlay = Image.new("RGB", size)
        overlay_draw = ImageDraw.Draw(overlay)
        steps = len(colors) - 1
        for index, (start, end) in enumerate(zip(colors[:-1], colors[1:])):
            y0 = int(height * index / steps)
            y1 = int(height * (index + 1) / steps)
            for y in range(y0, y1):
                ratio = (y - y0) / max(y1 - y0, 1)
                r = int(start[0] * (1 - ratio) + end[0] * ratio)
                g = int(start[1] * (1 - ratio) + end[1] * ratio)
                b = int(start[2] * (1 - ratio) + end[2] * ratio)
                overlay_draw.line([(0, y), (width, y)], fill=(r, g, b))
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=height / 12))
        base = Image.blend(base, overlay, alpha=0.4)
    return base


def _prompt_to_gradient(prompt: str) -> Gradient:
    palette = [
        (255, 92, 87),
        (255, 149, 0),
        (255, 204, 0),
        (76, 217, 100),
        (90, 200, 250),
        (88, 86, 214),
        (255, 45, 85),
        (142, 142, 147),
    ]
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    picks = [digest[i] % len(palette) for i in range(3)]
    return [palette[idx] for idx in picks]


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    box: Tuple[int, int, int, int],
    fill: Tuple[int, int, int],
    shadow: bool,
) -> None:
    if not text:
        return

    max_width = box[2] - box[0] - 80
    lines = wrap_text(text, font, max_width)
    if not lines:
        return

    line_heights = [text_height(font, line) for line in lines]
    total_height = sum(line_heights) + max(0, (len(lines) - 1) * 12)
    x0, y0, x1, y1 = box
    start_y = y0 + max(0, (y1 - y0 - total_height) // 2)

    for idx, line in enumerate(lines):
        width = text_width(font, line)
        line_height = line_heights[idx]
        x = x0 + (x1 - x0 - width) / 2
        y = start_y + sum(line_heights[:idx]) + idx * 12
        if shadow:
            draw.text((x + 2, y + 2), line, font=font, fill=_shadow_color(fill))
        draw.text((x, y), line, font=font, fill=fill)


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    """Wrap text to fit in a pixel width, supporting CJK languages."""
    if not text:
        return []

    has_spaces = " " in text
    words: Iterable[str] = text.split(" ") if has_spaces else list(text)

    lines: List[str] = []
    current = ""

    for token in words:
        separator = " " if has_spaces and current else ""
        candidate = current + separator + token if has_spaces else current + token

        if current and text_width(font, candidate) > max_width:
            lines.append(current)
            current = token
            if text_width(font, current) > max_width:
                lines.append(_truncate_text(token, font, max_width))
                current = ""
        else:
            current = candidate

    if current:
        lines.append(current)

    return lines


def _truncate_text(token: str, font: ImageFont.ImageFont, max_width: int) -> str:
    accum = ""
    for char in token:
        trial = accum + char
        if text_width(font, trial) > max_width:
            break
        accum = trial
    return accum or token


def text_width(font: ImageFont.ImageFont, text: str) -> float:
    try:
        return font.getlength(text)
    except AttributeError:
        bbox = font.getbbox(text)
        return float(bbox[2] - bbox[0])


def text_height(font: ImageFont.ImageFont, text: str) -> int:
    bbox = font.getbbox(text)
    return bbox[3] - bbox[1]


def _shadow_color(color: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
    r, g, b = color
    return (max(0, r - 120), max(0, g - 120), max(0, b - 120), 180)


def ensure_square(image: Image.Image) -> Image.Image:
    """Crop the image to a centered square."""
    width, height = image.size
    if width == height:
        return image
    edge = min(width, height)
    left = (width - edge) // 2
    top = (height - edge) // 2
    right = left + edge
    bottom = top + edge
    return image.crop((left, top, right, bottom))


__all__ = [
    "FontSpec",
    "RenderOptions",
    "TextSpec",
    "TextBlock",
    "create_card",
    "draw_text_blocks",
    "generate_prompt_gradient",
    "load_background",
    "wrap_text",
    "ensure_square",
    "pick_text_color",
]
