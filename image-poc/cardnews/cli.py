"""Command line interface for the Cardnews generator."""

from __future__ import annotations

import copy
import datetime as _dt
import math
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple

import click
from click.core import ParameterSource
from PIL import Image as PILImage

from . import get_version
from .config import DEFAULT_CONFIG, load_config, save_config, update_config
from .gemini import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_MODEL,
    GeminiNotConfigured,
    generate_background_image,
    generate_cards as gemini_generate_cards,
    get_api_key,
)
from .image import FontSpec, RenderOptions, create_brand_card, create_card, generate_prompt_gradient
from .io import load_card, load_cards


@click.group()
@click.version_option(version=get_version(), prog_name="cardnews")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Nanobanana 스타일의 인스타그램 카드뉴스를 생성하는 CLI."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()


@main.command()
@click.option("--title", type=str, help="카드 타이틀 텍스트")
@click.option("--subtitle", type=str, help="카드 서브타이틀 텍스트")
@click.option("--image-prompt", type=str, help="배경 이미지를 위한 프롬프트")
@click.option("--background-path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--input", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="JSON 입력 파일")
@click.option("--output", type=click.Path(dir_okay=False, writable=True, path_type=Path), required=False)
@click.option("--size", type=str, default=None, help="출력 사이즈, 예: 1080x1080")
@click.option("--no-overlay", is_flag=True, help="텍스트 영역 오버레이 비활성화")
@click.option("--no-shadow", is_flag=True, help="텍스트 그림자 비활성화")
@click.option("--dry-run", is_flag=True, help="이미지를 저장하지 않고 동작만 확인")
@click.pass_context
def create(
    ctx: click.Context,
    title: Optional[str],
    subtitle: Optional[str],
    image_prompt: Optional[str],
    background_path: Optional[Path],
    input: Optional[Path],
    output: Optional[Path],
    size: Optional[str],
    no_overlay: bool,
    no_shadow: bool,
    dry_run: bool,
) -> None:
    """단일 카드뉴스 이미지를 생성합니다."""
    config = ctx.obj["config"]
    card_data = _load_card_input(input, title, subtitle, image_prompt)
    card_data["image_prompt"] = _ensure_realistic_prompt(card_data.get("image_prompt"))

    interactive = input is None

    if interactive:
        if not card_data.get("title"):
            card_data["title"] = click.prompt("타이틀", type=str)
        if not card_data.get("subtitle"):
            card_data["subtitle"] = click.prompt("서브타이틀", type=str)
        if not card_data.get("image_prompt") and not background_path:
            card_data["image_prompt"] = click.prompt("배경 이미지 프롬프트", type=str)

    if not card_data.get("title"):
        raise click.UsageError("타이틀을 입력 옵션(--title) 또는 프롬프트로 제공해야 합니다.")

    if not output and card_data.get("output"):
        output = Path(card_data["output"])

    if not output:
        default_name = f"card_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        output_str = click.prompt("출력 파일 경로", default=default_name)
        output = Path(output_str)

    options = _build_render_options(config, size, no_overlay, no_shadow)
    fonts = _fonts_from_config(config)
    api_key = get_api_key()

    background_source: Optional[str] = None
    if background_path:
        background_source = str(background_path)
    elif card_data.get("background_path"):
        background_source = str(card_data["background_path"])

    background_image = None
    if not background_source and not card_data.get("image_prompt"):
        raise click.UsageError("배경 이미지를 생성하려면 image_prompt 또는 --background-path가 필요합니다.")

    if not background_source:
        background_image = _maybe_generate_background(
            ctx,
            prompt=card_data.get("image_prompt"),
            options=options,
            config=config,
            api_key=api_key,
        )

    image = create_card(
        title=card_data.get("title", ""),
        subtitle=card_data.get("subtitle", ""),
        prompt=card_data.get("image_prompt"),
        background_path=background_source,
        fonts=fonts,
        options=options,
        background_image=background_image,
    )

    if dry_run:
        click.echo(f"[DRY-RUN] {output}에 저장될 이미지를 생성했습니다.")
        return

    image.save(output)
    click.echo(f"생성 완료: {output}")


@main.command()
@click.option("--input", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True, help="JSON/CSV 입력 파일")
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("output"))
@click.option("--size", type=str, default=None, help="출력 사이즈, 예: 1080x1080")
@click.option("--no-overlay", is_flag=True, help="텍스트 영역 오버레이 비활성화")
@click.option("--no-shadow", is_flag=True, help="텍스트 그림자 비활성화")
@click.pass_context
def batch(
    ctx: click.Context,
    input: Path,
    output_dir: Path,
    size: Optional[str],
    no_overlay: bool,
    no_shadow: bool,
) -> None:
    """여러 카드뉴스를 일괄로 생성합니다."""
    config = ctx.obj["config"]
    cards = load_cards(str(input))
    if not cards:
        raise click.UsageError("입력 파일에서 카드 데이터를 찾을 수 없습니다.")

    output_dir.mkdir(parents=True, exist_ok=True)
    options = _build_render_options(config, size, no_overlay, no_shadow)
    fonts = _fonts_from_config(config)
    api_key = get_api_key()

    with click.progressbar(enumerate(cards, start=1), label="카드뉴스 생성 중", length=len(cards)) as progress:
        for idx, entry in progress:
            output_path = entry.get("output") or f"card_{idx:02}.jpg"
            background_path = entry.get("background_path")
            background_image = None
            prompt_value = _ensure_realistic_prompt(entry.get("image_prompt"))
            if background_path:
                background_path = str(background_path)
            else:
                if not prompt_value:
                    raise click.UsageError(
                        f"배경 이미지를 생성하려면 입력 데이터에 image_prompt 값을 제공해야 합니다. (index={idx})"
                    )
                background_image = _maybe_generate_background(
                    ctx,
                    prompt=prompt_value,
                    options=options,
                    config=config,
                    api_key=api_key,
                )
            image = create_card(
                title=entry.get("title", ""),
                subtitle=entry.get("subtitle", ""),
                prompt=prompt_value,
                background_path=background_path,
                fonts=fonts,
                options=options,
                background_image=background_image,
            )
            image.save(output_dir / output_path)

    click.echo(f"총 {len(cards)}개의 이미지를 {output_dir}에 저장했습니다.")


@main.command(name="brand-card")
@click.option("--brand-text", type=str, default="", help="상단 오른쪽 브랜드 텍스트")
@click.option("--title", type=str, help="메인 타이틀 텍스트")
@click.option("--subtitle", type=str, default="", help="서브타이틀 텍스트")
@click.option("--footer-text", type=str, default="", help="하단 오른쪽 텍스트")
@click.option("--background-path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--image-prompt", type=str, help="프롬프트 기반 배경 생성")
@click.option("--output", type=click.Path(dir_okay=False, writable=True, path_type=Path))
@click.option("--size", type=int, default=512, show_default=True, help="정사각형 한 변 크기")
@click.option("--overlay-alpha", type=int, default=48, show_default=True, help="배경 오버레이 투명도 (0-255)")
@click.option("--no-overlay", is_flag=True, help="배경 오버레이 비활성화")
@click.option("--shadow", is_flag=True, help="텍스트 그림자 활성화")
@click.option("--input", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="JSON 입력 파일")
@click.option("--dry-run", is_flag=True, help="이미지를 저장하지 않고 미리보기만 수행")
@click.pass_context
def brand_card(
    ctx: click.Context,
    brand_text: str,
    title: Optional[str],
    subtitle: str,
    footer_text: str,
    background_path: Optional[Path],
    image_prompt: Optional[str],
    output: Optional[Path],
    size: int,
    overlay_alpha: int,
    no_overlay: bool,
    shadow: bool,
    input: Optional[Path],
    dry_run: bool,
) -> None:
    """512x512 브랜드 카드 템플릿을 생성합니다."""

    config = ctx.obj["config"]
    brand_cfg = config.get("brand_card", {}) if isinstance(config, dict) else {}

    if ctx.get_parameter_source("overlay_alpha") == ParameterSource.DEFAULT:
        overlay_from_cfg = brand_cfg.get("overlay_alpha") if isinstance(brand_cfg, Mapping) else None
        if overlay_from_cfg is not None:
            try:
                overlay_alpha = int(overlay_from_cfg)
            except (TypeError, ValueError) as err:
                raise click.UsageError("brand_card.overlay_alpha 값은 정수여야 합니다.") from err

    if ctx.get_parameter_source("no_overlay") == ParameterSource.DEFAULT:
        overlay_enabled = brand_cfg.get("overlay") if isinstance(brand_cfg, Mapping) else None
        if isinstance(overlay_enabled, bool):
            no_overlay = not overlay_enabled

    if ctx.get_parameter_source("shadow") == ParameterSource.DEFAULT:
        shadow_default = brand_cfg.get("shadow") if isinstance(brand_cfg, Mapping) else None
        if isinstance(shadow_default, bool):
            shadow = shadow_default

    if size <= 0:
        raise click.UsageError("--size 값은 1 이상의 정수여야 합니다.")
    if not 0 <= overlay_alpha <= 255:
        raise click.UsageError("--overlay-alpha 값은 0~255 범위여야 합니다.")

    data: Dict[str, str] = {}
    if input:
        data.update(load_card(str(input)))

    title_text = (title or data.get("title") or "").strip()
    subtitle_text = (subtitle or data.get("subtitle") or "").strip()
    brand_value = (brand_text or data.get("brand") or data.get("brand_text") or "").strip()
    footer_value = (footer_text or data.get("footer") or data.get("footer_text") or "").strip()

    background_value: Optional[Path] = background_path or None
    if not background_value:
        bg_from_data = data.get("background_path") or data.get("background")
        if bg_from_data:
            background_value = Path(bg_from_data)

    output_value: Optional[Path] = output or None
    if not output_value:
        out_from_data = data.get("output")
        if out_from_data:
            output_value = Path(out_from_data)

    interactive = input is None

    if not title_text and interactive:
        title_text = click.prompt("타이틀", type=str)
    if not title_text:
        raise click.UsageError("타이틀 텍스트를 제공해야 합니다.")

    prompt_value = _ensure_realistic_prompt(image_prompt or data.get("image_prompt"))

    if not background_value and interactive and not prompt_value:
        bg_prompt = click.prompt(
            "배경 이미지 경로 (프롬프트를 사용할 경우 Enter)",
            default="",
            show_default=False,
        ).strip()
        if bg_prompt:
            background_value = Path(bg_prompt)

    if background_value and not background_value.exists():
        raise click.UsageError(f"배경 이미지 파일을 찾을 수 없습니다: {background_value}")

    if not background_value and not prompt_value and interactive:
        prompt_value = _ensure_realistic_prompt(click.prompt("배경 이미지 프롬프트", type=str))

    if not background_value and not prompt_value:
        raise click.UsageError("배경 이미지를 위한 경로 또는 프롬프트가 필요합니다.")

    if not output_value:
        default_name = f"brand_card_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if interactive:
            output_value = Path(click.prompt("출력 파일 경로", default=default_name))
        else:
            output_value = Path(default_name)

    overlay_color = None if no_overlay else (255, 255, 255, overlay_alpha)
    font_overrides = _brand_font_overrides(config)

    background_image = None
    background_path_value: Optional[str] = None
    if background_value:
        background_path_value = str(background_value)
    else:
        options = RenderOptions(width=size, height=size, add_overlay=not no_overlay, shadow=shadow)
        api_key = get_api_key()
        background_image = _maybe_generate_background(
            ctx,
            prompt=prompt_value,
            options=options,
            config=config,
            api_key=api_key,
        )
        if background_image is None:
            fallback_prompt = prompt_value or "brand-card"
            background_image = generate_prompt_gradient(fallback_prompt, (size, size))

    image = create_brand_card(
        background_path=background_path_value,
        background_image=background_image,
        brand_text=brand_value,
        title_text=title_text,
        subtitle_text=subtitle_text,
        footer_text=footer_value,
        size=size,
        font_specs=font_overrides,
        overlay_color=overlay_color,
        shadow=shadow,
    )

    if dry_run:
        click.echo(f"[DRY-RUN] {output_value}에 저장될 이미지를 생성했습니다.")
        return

    output_value.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_value)
    click.echo(f"생성 완료: {output_value}")


@main.command()
@click.option("--topic", type=str, required=True, help="생성할 주제")
@click.option("--count", type=int, default=3, show_default=True)
@click.option("--style", type=str, default=None, help="콘텐츠 스타일 (예: tips, quotes)")
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("output"))
@click.option("--size", type=str, default=None, help="출력 사이즈, 예: 1080x1080")
@click.option("--no-overlay", is_flag=True)
@click.option("--no-shadow", is_flag=True)
@click.pass_context
def generate(
    ctx: click.Context,
    topic: str,
    count: int,
    style: Optional[str],
    output_dir: Path,
    size: Optional[str],
    no_overlay: bool,
    no_shadow: bool,
) -> None:
    """Gemini API를 사용하여 카드 콘텐츠와 이미지를 자동 생성합니다."""
    config = ctx.obj["config"]
    options = _build_render_options(config, size, no_overlay, no_shadow)
    fonts = _fonts_from_config(config)

    api_key = get_api_key()
    gemini_cfg = config.get("gemini", {}) if isinstance(config, dict) else {}
    model_name = gemini_cfg.get("model", DEFAULT_TEXT_MODEL)
    image_model = gemini_cfg.get("image_model", DEFAULT_IMAGE_MODEL)
    cards = gemini_generate_cards(topic=topic, count=count, style=style, model_name=model_name, api_key=api_key)

    output_dir.mkdir(parents=True, exist_ok=True)

    for index, card in enumerate(cards, start=1):
        filename = f"{topic}_{index:02}.jpg"
        background_path = card.get("background_path")
        if background_path:
            background_path = str(background_path)
            background_image = None
        else:
            background_image = _maybe_generate_background(
                ctx,
                prompt=card.get("image_prompt"),
                options=options,
                config=config,
                api_key=api_key,
                image_model=image_model,
            )
        image = create_card(
            title=card.get("title", ""),
            subtitle=card.get("subtitle", ""),
            prompt=card.get("image_prompt"),
            background_path=background_path,
            fonts=fonts,
            options=options,
            background_image=background_image,
        )
        image.save(output_dir / filename)
        click.echo(f"생성 완료: {filename}")


@main.command()
@click.option("--get", "get_keys", multiple=True, help="특정 설정 키를 조회 (dot 표기법)")
@click.option("--set", "set_pairs", nargs=2, multiple=True, metavar="KEY VALUE", help="설정 값 변경")
@click.option("--reset", is_flag=True, help="설정을 기본값으로 초기화")
@click.pass_context
def config(ctx: click.Context, get_keys: Iterable[str], set_pairs: Iterable[Tuple[str, str]], reset: bool) -> None:
    """CLI 동작에 사용되는 설정을 관리합니다."""
    current = copy.deepcopy(DEFAULT_CONFIG) if reset else ctx.obj["config"]

    if reset:
        save_config(DEFAULT_CONFIG)
        ctx.obj["config"] = copy.deepcopy(DEFAULT_CONFIG)
        click.echo("설정을 초기화했습니다.")

    if set_pairs:
        updates: Dict[str, object] = {}
        for key, value in set_pairs:
            _apply_config_update(updates, key, value)
        merged = update_config(updates)
        ctx.obj["config"] = merged
        current = merged

    if get_keys:
        for key in get_keys:
            click.echo(f"{key}: {_lookup_key(current, key)}")
        return

    if not set_pairs and not reset:
        click.echo("현재 설정:")
        for key, value in current.items():
            click.echo(f"- {key}: {value}")


def _load_card_input(
    input_path: Optional[Path],
    title: Optional[str],
    subtitle: Optional[str],
    image_prompt: Optional[str],
) -> Dict[str, str]:
    data: Dict[str, str] = {"title": title or "", "subtitle": subtitle or "", "image_prompt": image_prompt or ""}
    if input_path:
        loaded = load_card(str(input_path))
        data.update({k: v for k, v in loaded.items() if v})
    return data


def _build_render_options(
    config: Dict[str, object],
    size: Optional[str],
    no_overlay: bool,
    no_shadow: bool,
) -> RenderOptions:
    image_cfg = config.get("image", {}) if isinstance(config, dict) else {}
    width = int(image_cfg.get("width", 1080))
    height = int(image_cfg.get("height", 1080))
    overlay_enabled = bool(image_cfg.get("overlay", True))
    if size:
        try:
            width, height = [int(part) for part in size.lower().split("x", 1)]
        except Exception as err:
            raise click.UsageError("사이즈는 WIDTHxHEIGHT 형식이어야 합니다.") from err
    return RenderOptions(
        width=width,
        height=height,
        add_overlay=overlay_enabled and not no_overlay,
        shadow=not no_shadow,
    )


def _fonts_from_config(config: Dict[str, object]) -> Tuple[FontSpec, FontSpec]:
    title_font = _font_spec_from_config(config, "title", 72)
    subtitle_font = _font_spec_from_config(config, "subtitle", 42)
    return (title_font, subtitle_font)


def _brand_font_overrides(config: Dict[str, object]) -> Optional[Dict[str, FontSpec]]:
    brand_cfg = config.get("brand_card", {}) if isinstance(config, dict) else {}
    fonts_cfg = brand_cfg.get("fonts", {}) if isinstance(brand_cfg, Mapping) else {}
    if not isinstance(fonts_cfg, Mapping):
        return None

    overrides: Dict[str, FontSpec] = {}
    for key in ("brand", "title", "subtitle", "footer"):
        entry = fonts_cfg.get(key)
        if not isinstance(entry, Mapping):
            continue
        path = _string_or_default(entry.get("path")) or None
        size_value = entry.get("size")
        if size_value is None:
            continue
        try:
            size = int(size_value)
        except (TypeError, ValueError) as err:
            raise click.UsageError(f"brand_card.fonts.{key}.size 값은 정수여야 합니다.") from err
        overrides[key] = FontSpec(path=path, size=size)

    return overrides or None


def _font_spec_from_config(config: Dict[str, object], key: str, default_size: int) -> FontSpec:
    fonts_cfg = config.get("fonts", {}) if isinstance(config, dict) else {}
    entry = fonts_cfg.get(key, {}) if isinstance(fonts_cfg, Mapping) else {}
    path = _string_or_default(entry.get("path")) or None
    size_value = entry.get("size")
    try:
        size = int(size_value) if size_value is not None else default_size
    except (TypeError, ValueError) as err:
        raise click.UsageError(f"fonts.{key}.size 값은 정수여야 합니다.") from err
    return FontSpec(path=path, size=size)


def _string_or_default(value: Optional[object], default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _ensure_realistic_prompt(prompt: Optional[str]) -> str:
    requirement = "실사스러운 이미지를 생성"
    text = (prompt or "").strip()
    if not text:
        return ""
    if requirement in text:
        return text
    return f"{text} {requirement}".strip()


def _apply_config_update(target: Dict[str, object], key: str, value: str) -> None:
    parts = key.split(".")
    cursor: Dict[str, object] = target
    for segment in parts[:-1]:
        cursor = cursor.setdefault(segment, {})  # type: ignore[assignment]
        if not isinstance(cursor, dict):  # pragma: no cover - defensive
            raise click.UsageError(f"{segment}에 하위 키를 설정할 수 없습니다.")
    cursor[parts[-1]] = value


def _lookup_key(data: Dict[str, object], dotted: str):
    parts = dotted.split(".")
    cursor: object = data
    for part in parts:
        if isinstance(cursor, Mapping) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    return cursor


def _maybe_generate_background(
    ctx: click.Context,
    *,
    prompt: Optional[str],
    options: RenderOptions,
    config: Dict[str, object],
    api_key: Optional[str],
    image_model: Optional[str] = None,
) -> Optional[PILImage.Image]:
    if not prompt:
        return None

    gemini_cfg = config.get("gemini", {}) if isinstance(config, dict) else {}
    model_name = image_model or gemini_cfg.get("image_model", DEFAULT_IMAGE_MODEL)
    aspect_ratio = _aspect_ratio_string(options.width, options.height)

    if not api_key:
        _emit_warning_once(ctx, "gemini-missing", "Gemini API 키가 없어 배경 이미지는 그라데이션으로 대체됩니다.")
        return None

    try:
        return generate_background_image(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            model_name=model_name,
            api_key=api_key,
        )
    except GeminiNotConfigured:
        _emit_warning_once(ctx, "gemini-missing", "Gemini API 키가 없어 배경 이미지는 그라데이션으로 대체됩니다.")
    except Exception as err:  # pragma: no cover - network variability
        _emit_warning_once(
            ctx,
            "gemini-background-failed",
            f"Gemini 배경 이미지 생성 실패: {err}. 그라데이션으로 대체합니다.",
        )
    return None


def _aspect_ratio_string(width: int, height: int) -> str:
    gcd = math.gcd(width, height) or 1
    return f"{width // gcd}:{height // gcd}"


def _emit_warning_once(ctx: click.Context, key: str, message: str) -> None:
    store = ctx.obj.setdefault("_warnings", set())
    if key in store:
        return
    store.add(key)
    click.echo(message, err=True)


if __name__ == "__main__":  # pragma: no cover
    main()
