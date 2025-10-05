"""Command line interface for the Cardnews generator."""

from __future__ import annotations

import datetime as _dt
import copy
import math
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import click
from PIL import Image as PILImage

from . import get_version
from .config import DEFAULT_CONFIG, load_config, save_config, update_config
from .figma import (
    FIGMA_TOKEN_ENV,
    FigmaAPIError,
    FigmaClient,
    FigmaNotConfigured,
    get_token as get_figma_token,
)
from .gemini import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_MODEL,
    GeminiNotConfigured,
    generate_background_image,
    generate_cards as gemini_generate_cards,
    get_api_key,
)
from .image import FontSpec, RenderOptions, TextBlock, create_card, draw_text_blocks, pick_text_color
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
            if background_path:
                background_path = str(background_path)
            else:
                if not entry.get("image_prompt"):
                    raise click.UsageError(
                        f"배경 이미지를 생성하려면 입력 데이터에 image_prompt 값을 제공해야 합니다. (index={idx})"
                    )
                background_image = _maybe_generate_background(
                    ctx,
                    prompt=entry.get("image_prompt"),
                    options=options,
                    config=config,
                    api_key=api_key,
                )
            image = create_card(
                title=entry.get("title", ""),
                subtitle=entry.get("subtitle", ""),
                prompt=entry.get("image_prompt"),
                background_path=background_path,
                fonts=fonts,
                options=options,
                background_image=background_image,
            )
            image.save(output_dir / output_path)

    click.echo(f"총 {len(cards)}개의 이미지를 {output_dir}에 저장했습니다.")


@main.command(name="figma")
@click.option("--title", type=str, help="카드 타이틀 텍스트")
@click.option("--subtitle", type=str, help="카드 서브타이틀 텍스트")
@click.option("--business-name", type=str, help="상호명 텍스트")
@click.option("--image-prompt", type=str, help="배경 이미지를 위한 프롬프트")
@click.option("--background-path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--input", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="JSON 입력 파일")
@click.option("--output", type=click.Path(dir_okay=False, writable=True, path_type=Path))
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("output"))
@click.option("--figma-file-key", type=str, help="Figma 파일 키")
@click.option("--figma-frame-id", type=str, help="렌더링할 프레임 ID")
@click.option("--figma-title-node", type=str, help="타이틀 텍스트 슬롯 노드 ID")
@click.option("--figma-subtitle-node", type=str, help="서브타이틀 텍스트 슬롯 노드 ID")
@click.option("--figma-business-node", type=str, help="상호명 텍스트 슬롯 노드 ID")
@click.option("--figma-scale", type=float, default=None, help="Figma 렌더링 배율")
@click.option("--figma-format", type=click.Choice(["png", "jpg", "jpeg"]), default=None, help="Figma 렌더링 포맷")
@click.option("--figma-token", type=str, help="Figma API 토큰")
@click.option("--no-shadow", is_flag=True, help="텍스트 그림자 비활성화")
@click.option("--dry-run", is_flag=True, help="이미지를 저장하지 않고 동작만 확인")
@click.pass_context
def figma_template(
    ctx: click.Context,
    title: Optional[str],
    subtitle: Optional[str],
    business_name: Optional[str],
    image_prompt: Optional[str],
    background_path: Optional[Path],
    input: Optional[Path],
    output: Optional[Path],
    output_dir: Path,
    figma_file_key: Optional[str],
    figma_frame_id: Optional[str],
    figma_title_node: Optional[str],
    figma_subtitle_node: Optional[str],
    figma_business_node: Optional[str],
    figma_scale: Optional[float],
    figma_format: Optional[str],
    figma_token: Optional[str],
    no_shadow: bool,
    dry_run: bool,
) -> None:
    """Figma 템플릿을 활용해 카드뉴스 이미지를 생성합니다."""

    config = ctx.obj["config"]
    card_data = _load_card_input(input, title, subtitle, image_prompt)
    card_data["business_name"] = business_name or card_data.get("business_name", "")

    interactive = input is None

    if interactive:
        if not card_data.get("title"):
            card_data["title"] = click.prompt("타이틀", type=str)
        if not card_data.get("subtitle"):
            card_data["subtitle"] = click.prompt("서브타이틀", type=str)
        if not card_data.get("business_name"):
            card_data["business_name"] = click.prompt("상호명", type=str, default="")
        if not card_data.get("image_prompt") and not background_path:
            card_data["image_prompt"] = click.prompt("배경 이미지 프롬프트", type=str)

    if not card_data.get("title"):
        raise click.UsageError("타이틀을 입력 옵션(--title) 또는 프롬프트로 제공해야 합니다.")
    if not card_data.get("subtitle"):
        raise click.UsageError("서브타이틀을 입력 옵션(--subtitle) 또는 프롬프트로 제공해야 합니다.")

    figma_cfg = config.get("figma", {}) if isinstance(config, dict) else {}
    file_key = figma_file_key or _string_or_default(figma_cfg.get("file_key"))
    frame_id = figma_frame_id or _string_or_default(figma_cfg.get("frame_id"))
    nodes_cfg = figma_cfg.get("nodes", {}) if isinstance(figma_cfg, dict) else {}
    slot_nodes = {
        "title": figma_title_node or _string_or_default(nodes_cfg.get("title")),
        "subtitle": figma_subtitle_node or _string_or_default(nodes_cfg.get("subtitle")),
        "business": figma_business_node or _string_or_default(nodes_cfg.get("business")),
    }

    missing_slots = [slot for slot in ("title", "subtitle") if not slot_nodes.get(slot)]
    if missing_slots:
        raise click.UsageError(
            "Figma 템플릿 설정이 부족합니다. config의 figma.nodes 값을 확인하거나 명령 옵션으로 노드 ID를 지정하세요."
        )
    if not file_key or not frame_id:
        raise click.UsageError("Figma 파일 키와 프레임 ID가 필요합니다. --figma-file-key와 --figma-frame-id를 확인하세요.")

    scale = figma_scale or _coerce_float(figma_cfg.get("scale"), 1.0)
    image_format = figma_format or _string_or_default(figma_cfg.get("format"), "png")
    file_suffix = "png"
    if image_format.lower() in {"jpg", "jpeg"}:
        file_suffix = "jpg"

    token = (figma_token or get_figma_token() or _string_or_default(figma_cfg.get("token")))
    if not token:
        raise click.UsageError(
            f"Figma API 토큰이 필요합니다. {FIGMA_TOKEN_ENV} 환경 변수 또는 --figma-token 옵션을 사용해주세요."
        )

    client = FigmaClient(token)

    try:
        layout = client.fetch_layout(file_key=file_key, frame_id=frame_id, slot_nodes=slot_nodes, scale=scale)
        overlay_image = client.render_frame(file_key=file_key, frame_id=frame_id, scale=scale, format=image_format)
    except FigmaNotConfigured as err:
        raise click.UsageError(str(err)) from err
    except FigmaAPIError as err:
        raise click.ClickException(str(err)) from err

    card_prompt = _augment_image_prompt(card_data.get("image_prompt")) if card_data.get("image_prompt") else ""
    card_data["image_prompt"] = card_prompt

    background_source: Optional[str] = None
    if background_path:
        background_source = str(background_path)
    elif card_data.get("background_path"):
        background_source = str(card_data["background_path"])

    background_image: Optional[PILImage.Image] = None
    if background_source:
        background_image = _load_background_exact(background_source, overlay_image.size)
    elif card_prompt:
        options = RenderOptions(
            width=overlay_image.width,
            height=overlay_image.height,
            add_overlay=False,
            shadow=not no_shadow,
        )
        api_key = get_api_key()
        background_image = _maybe_generate_background(
            ctx,
            prompt=card_prompt,
            options=options,
            config=config,
            api_key=api_key,
        )
        if background_image is not None:
            background_image = background_image.resize(overlay_image.size, PILImage.LANCZOS)

    if background_image is not None:
        base_canvas = background_image.convert("RGBA")
        if overlay_image.mode != "RGBA":
            overlay_image = overlay_image.convert("RGBA")
        composite = PILImage.alpha_composite(base_canvas, overlay_image)
    else:
        composite = overlay_image.convert("RGBA")

    fonts = {
        "title": _font_spec_from_config(config, "title", 72),
        "subtitle": _font_spec_from_config(config, "subtitle", 48),
        "business": _font_spec_from_config(config, "business", 42),
    }

    blocks = []
    for slot, node_id in slot_nodes.items():
        if not node_id:
            continue
        box = layout.box_for(slot)
        if not box:
            continue
        if slot == "business":
            text_value = card_data.get("business_name", "").strip()
        else:
            text_value = card_data.get(slot, "").strip()
        if not text_value:
            continue
        font_spec = fonts.get(slot) or fonts["subtitle"]
        blocks.append(TextBlock(text=text_value, font=font_spec, box=box))

    if not blocks:
        raise click.UsageError("표시할 텍스트가 없습니다. 입력 데이터를 다시 확인하세요.")

    default_fill = pick_text_color(composite)
    final_image = draw_text_blocks(composite, blocks, shadow=not no_shadow, default_fill=default_fill).convert("RGB")

    if not output and card_data.get("output"):
        output = Path(card_data["output"])

    output_path = _resolve_output_path(output, output_dir, suffix=file_suffix)

    if dry_run:
        click.echo(f"[DRY-RUN] {output_path}에 저장될 이미지를 생성했습니다.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_image.save(output_path)
    click.echo(f"생성 완료: {output_path}")


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
        click.echo(current)


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
    return (
        _font_spec_from_config(config, "title", 72),
        _font_spec_from_config(config, "subtitle", 48),
    )


def _font_spec_from_config(config: Dict[str, object], key: str, default_size: int) -> FontSpec:
    fonts_cfg = config.get("fonts", {}) if isinstance(config, dict) else {}
    entry = fonts_cfg.get(key, {}) if isinstance(fonts_cfg, dict) else {}
    size = entry.get("size", default_size)
    try:
        size_int = int(size)
    except (TypeError, ValueError):
        size_int = default_size
    path_value = entry.get("path") if isinstance(entry, dict) else None
    return FontSpec(path=path_value, size=size_int)


def _string_or_default(value: Optional[object], default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _coerce_float(value: Optional[object], default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _augment_image_prompt(prompt: Optional[str]) -> str:
    requirement = "실사스러운 이미지를 생성"
    text = (prompt or "").strip()
    if not text:
        return requirement
    if requirement in text:
        return text
    return f"{text} {requirement}".strip()


def _load_background_exact(path: str, size: Tuple[int, int]) -> PILImage.Image:
    image = PILImage.open(path).convert("RGB")
    if image.size != size:
        image = image.resize(size, PILImage.LANCZOS)
    return image


def _resolve_output_path(output: Optional[Path], output_dir: Path, *, suffix: str) -> Path:
    base_dir = (output_dir or Path("output")).expanduser()
    if output:
        resolved = output if output.is_absolute() else base_dir / output
        if not resolved.suffix:
            resolved = resolved.with_suffix(f".{suffix}")
        return resolved
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"card_{timestamp}.{suffix}"
    return base_dir / filename


def _apply_config_update(target: Dict[str, object], key: str, value: str) -> None:
    mapping = {
        "font-title": ("fonts", "title", "path"),
        "font-subtitle": ("fonts", "subtitle", "path"),
        "font-title-size": ("fonts", "title", "size"),
        "font-subtitle-size": ("fonts", "subtitle", "size"),
        "image-width": ("image", "width"),
        "image-height": ("image", "height"),
        "image-overlay": ("image", "overlay"),
        "gemini-model": ("gemini", "model"),
        "gemini-image-model": ("gemini", "image_model"),
    }
    path = mapping.get(key)
    if not path:
        path = tuple(key.split("."))
    cursor = target
    for part in path[:-1]:
        cursor = cursor.setdefault(part, {})  # type: ignore[assignment]
    final = path[-1]
    if final in {"width", "height", "size"}:
        cursor[final] = int(value)
    elif final == "overlay":
        cursor[final] = value.lower() in {"1", "true", "yes", "on"}
    else:
        cursor[final] = value


def _lookup_key(data: Dict[str, object], dotted: str):
    cursor = data
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
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
    prompt = (prompt or "").strip()
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
