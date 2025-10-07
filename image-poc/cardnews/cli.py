"""Command line interface for the Cardnews generator."""

from __future__ import annotations

import datetime as _dt
import copy
import math
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, Iterator, Mapping, Optional, Tuple

import click
from PIL import Image as PILImage, ImageDraw, ImageChops

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
@click.option("--figma-title-name", type=str, help="타이틀 텍스트 레이어 이름")
@click.option("--figma-subtitle-name", type=str, help="서브타이틀 텍스트 레이어 이름")
@click.option("--figma-business-name", type=str, help="상호명 텍스트 레이어 이름")
@click.option("--figma-background-node", type=str, multiple=True, help="제거할 배경 노드 ID")
@click.option("--figma-background-name", type=str, multiple=True, help="제거할 배경 레이어 이름")
@click.option("--figma-scale", type=float, default=None, help="Figma 렌더링 배율")
@click.option("--figma-format", type=click.Choice(["png", "jpg", "jpeg"]), default=None, help="Figma 렌더링 포맷")
@click.option("--figma-token", type=str, help="Figma API 토큰")
@click.option(
    "--figma-clear-background/--no-figma-clear-background",
    default=None,
    help="Figma 프레임 배경을 투명 처리",
)
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
    figma_title_name: Optional[str],
    figma_subtitle_name: Optional[str],
    figma_business_name: Optional[str],
    figma_background_node: Tuple[str, ...],
    figma_background_name: Tuple[str, ...],
    figma_scale: Optional[float],
    figma_format: Optional[str],
    figma_token: Optional[str],
    figma_clear_background: Optional[bool],
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
    names_cfg = figma_cfg.get("names", {}) if isinstance(figma_cfg, dict) else {}
    slot_names = {
        "title": figma_title_name or _string_or_default(names_cfg.get("title")),
        "subtitle": figma_subtitle_name or _string_or_default(names_cfg.get("subtitle")),
        "business": figma_business_name or _string_or_default(names_cfg.get("business")),
    }

    background_nodes_cfg = figma_cfg.get("background_nodes", []) if isinstance(figma_cfg, dict) else []
    background_names_cfg = figma_cfg.get("background_names", []) if isinstance(figma_cfg, dict) else []

    def _normalize_sequence(items: Iterable[object]) -> Tuple[str, ...]:
        normalized = []
        for item in items:
            value = _string_or_default(item)
            if value:
                normalized.append(value)
        return tuple(normalized)

    background_nodes = _normalize_sequence(list(figma_background_node) + list(background_nodes_cfg))
    background_names = _normalize_sequence(list(figma_background_name) + list(background_names_cfg))

    missing_slots = [slot for slot in ("title", "subtitle") if not (slot_nodes.get(slot) or slot_names.get(slot))]
    if missing_slots:
        raise click.UsageError(
            "Figma 템플릿 설정이 부족합니다. config의 figma.nodes 또는 figma.names 값을 확인하거나 명령 옵션으로 레이어 정보를 지정하세요."
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

    clear_background_cfg = figma_cfg.get("clear_background")
    clear_background = (
        figma_clear_background
        if figma_clear_background is not None
        else bool(clear_background_cfg)
    )

    client = FigmaClient(token)

    try:
        layout = client.fetch_layout(
            file_key=file_key,
            frame_id=frame_id,
            slot_nodes=slot_nodes,
            slot_names=slot_names,
            background_nodes=background_nodes,
            background_names=background_names,
            scale=scale,
        )
        overlay_image = client.render_frame(file_key=file_key, frame_id=frame_id, scale=scale, format=image_format)
    except FigmaNotConfigured as err:
        raise click.UsageError(str(err)) from err
    except FigmaAPIError as err:
        raise click.ClickException(str(err)) from err

    if clear_background:
        background_boxes = layout.background_boxes()
        if background_boxes:
            overlay_image = _clear_background_regions(overlay_image, background_boxes)
        else:
            overlay_image = _clear_uniform_background(overlay_image)

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
    slot_keys = set(slot_nodes.keys()) | set(slot_names.keys())
    for slot in slot_keys:
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


@main.command(name="figma-nodes")
@click.option("--figma-file-key", type=str, help="Figma 파일 키")
@click.option("--figma-node-id", type=str, help="탐색할 노드 ID (미지정 시 프레임 ID 사용)")
@click.option("--figma-frame-id", type=str, help="기본 프레임 ID")
@click.option("--figma-token", type=str, help="Figma API 토큰")
@click.option("--max-depth", type=int, default=None, help="탐색할 최대 깊이 (0=루트만)")
@click.option("--show-bounds", is_flag=True, help="absoluteBoundingBox 좌표 출력")
@click.option("--show-text", is_flag=True, help="텍스트 노드의 내용을 함께 출력")
@click.pass_context
def figma_nodes(
    ctx: click.Context,
    figma_file_key: Optional[str],
    figma_node_id: Optional[str],
    figma_frame_id: Optional[str],
    figma_token: Optional[str],
    max_depth: Optional[int],
    show_bounds: bool,
    show_text: bool,
) -> None:
    """Figma 프레임/노드의 하위 레이어와 ID를 출력합니다."""

    config = ctx.obj["config"]
    figma_cfg = config.get("figma", {}) if isinstance(config, dict) else {}

    file_key = figma_file_key or _string_or_default(figma_cfg.get("file_key"))
    if not file_key:
        raise click.UsageError("Figma 파일 키가 필요합니다. --figma-file-key 또는 설정 값을 확인하세요.")

    default_node = figma_frame_id or _string_or_default(figma_cfg.get("frame_id"))
    target_node = figma_node_id or default_node
    if not target_node:
        raise click.UsageError("노드 ID가 필요합니다. --figma-node-id 또는 --figma-frame-id 옵션을 확인하세요.")

    token = figma_token or get_figma_token() or _string_or_default(figma_cfg.get("token"))
    if not token:
        raise click.UsageError(
            f"Figma API 토큰이 필요합니다. {FIGMA_TOKEN_ENV} 환경 변수 또는 --figma-token 옵션을 사용해주세요."
        )

    client = FigmaClient(token)
    try:
        root = client.fetch_node_tree(file_key=file_key, node_id=target_node)
    except FigmaNotConfigured as err:
        raise click.UsageError(str(err)) from err
    except FigmaAPIError as err:
        raise click.ClickException(str(err)) from err

    rows = list(_iter_figma_nodes(root, max_depth=max_depth))
    click.echo(f"노드 {target_node} 기준 {len(rows)}개 레이어")
    for depth, node_id, name, node_type, bbox, characters in rows:
        indent = "  " * depth
        label = name or "<unnamed>"
        type_suffix = f" [{node_type}]" if node_type else ""
        details = []
        if show_bounds and bbox:
            details.append(_format_bbox(bbox))
        if show_text and characters:
            details.append(_format_characters(characters))
        detail_str = f" | {' | '.join(details)}" if details else ""
        click.echo(f"{indent}- {label} ({node_id}){type_suffix}{detail_str}")


@main.command(name="figma-frames")
@click.option("--figma-file-key", type=str, help="Figma 파일 키")
@click.option("--figma-token", type=str, help="Figma API 토큰")
@click.option("--max-depth", type=int, default=None, help="프레임을 탐색할 최대 깊이")
@click.pass_context
def figma_frames(
    ctx: click.Context,
    figma_file_key: Optional[str],
    figma_token: Optional[str],
    max_depth: Optional[int],
) -> None:
    """파일 전체에서 프레임 노드와 ID를 나열합니다."""

    config = ctx.obj["config"]
    figma_cfg = config.get("figma", {}) if isinstance(config, dict) else {}

    file_key = figma_file_key or _string_or_default(figma_cfg.get("file_key"))
    if not file_key:
        raise click.UsageError("Figma 파일 키가 필요합니다. --figma-file-key 옵션 또는 설정 값을 확인하세요.")

    token = figma_token or get_figma_token() or _string_or_default(figma_cfg.get("token"))
    if not token:
        raise click.UsageError(
            f"Figma API 토큰이 필요합니다. {FIGMA_TOKEN_ENV} 환경 변수 또는 --figma-token 옵션을 사용해주세요."
        )

    client = FigmaClient(token)
    try:
        document = client.fetch_file_document(file_key=file_key)
    except FigmaNotConfigured as err:
        raise click.UsageError(str(err)) from err
    except FigmaAPIError as err:
        raise click.ClickException(str(err)) from err

    pages = document.get("children", []) if isinstance(document, Mapping) else []
    if not pages:
        click.echo("페이지 정보를 찾지 못했습니다.")
        return

    total_frames = 0
    for page in pages:
        if not isinstance(page, Mapping) or page.get("type") != "CANVAS":
            continue
        page_name = str(page.get("name", "")) or "(페이지)"
        page_id = str(page.get("id", ""))
        click.echo(f"[페이지] {page_name} ({page_id})")

        frames = list(_iter_frame_nodes(page.get("children"), max_depth=max_depth))
        if not frames:
            click.echo("  (프레임 없음)")
            continue

        for depth, node in frames:
            indent = "  " * (depth + 1)
            name = str(node.get("name", "")) or "<unnamed>"
            node_id = str(node.get("id", ""))
            click.echo(f"{indent}- {name} ({node_id})")
            total_frames += 1

    click.echo(f"총 {total_frames}개 프레임")


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


def _format_bbox(bbox: Mapping[str, object]) -> str:
    try:
        x = float(bbox.get("x", 0.0))
        y = float(bbox.get("y", 0.0))
        w = float(bbox.get("width", 0.0))
        h = float(bbox.get("height", 0.0))
    except (TypeError, ValueError):
        return "bbox=?"
    return f"x={x:.2f}, y={y:.2f}, w={w:.2f}, h={h:.2f}"


def _format_characters(text: str, *, limit: int = 60) -> str:
    trimmed = text.strip()
    if len(trimmed) > limit:
        trimmed = f"{trimmed[:limit]}…"
    return f'"{trimmed}"'


def _clear_background_regions(
    image: PILImage.Image,
    boxes: Iterable[Tuple[int, int, int, int]],
) -> PILImage.Image:
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    mask = PILImage.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.rectangle(box, fill=255)

    if mask.getbbox() is None:
        return image

    result = image.copy()
    alpha = result.getchannel("A")
    keep_alpha = PILImage.eval(mask, lambda px: 0 if px else 255)
    new_alpha = ImageChops.multiply(alpha, keep_alpha)
    result.putalpha(new_alpha)
    return result


def _clear_uniform_background(image: PILImage.Image, tolerance: int = 8) -> PILImage.Image:
    """Drop uniform frame backgrounds so custom backdrops remain visible."""

    if image.mode != "RGBA":
        image = image.convert("RGBA")

    width, height = image.size
    if width == 0 or height == 0:
        return image

    pixels = image.load()
    corners = [
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    ]
    valid_corners = [color for color in corners if isinstance(color, tuple) and len(color) == 4]
    if not valid_corners:
        return image
    reference, _ = Counter(valid_corners).most_common(1)[0]

    ref_r, ref_g, ref_b, _ = reference
    result = image.copy()
    result_pixels = result.load()
    for y in range(height):
        for x in range(width):
            r, g, b, a = result_pixels[x, y]
            if (
                abs(r - ref_r) <= tolerance
                and abs(g - ref_g) <= tolerance
                and abs(b - ref_b) <= tolerance
            ):
                result_pixels[x, y] = (r, g, b, 0)
    return result


def _iter_figma_nodes(
    node: Mapping[str, object],
    max_depth: Optional[int] = None,
    *,
    _depth: int = 0,
) -> Iterator[Tuple[int, str, str, str, Optional[Mapping[str, object]], Optional[str]]]:
    node_id = str(node.get("id", ""))
    name = str(node.get("name", "") or "")
    node_type = str(node.get("type", "") or "")
    bbox = node.get("absoluteBoundingBox") if isinstance(node.get("absoluteBoundingBox"), Mapping) else None
    characters = node.get("characters")
    if not isinstance(characters, str):
        characters = None
    yield (_depth, node_id, name, node_type, bbox, characters)

    if max_depth is not None and _depth >= max_depth:
        return

    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, Mapping):
                yield from _iter_figma_nodes(child, max_depth=max_depth, _depth=_depth + 1)


def _iter_frame_nodes(
    nodes: Optional[object],
    max_depth: Optional[int] = None,
    *,
    _depth: int = 0,
) -> Iterator[Tuple[int, Mapping[str, object]]]:
    if not isinstance(nodes, list):
        return

    for child in nodes:
        if not isinstance(child, Mapping):
            continue
        node_type = child.get("type")
        if node_type == "FRAME":
            yield (_depth, child)
            if max_depth is None or _depth < max_depth:
                yield from _iter_frame_nodes(child.get("children"), max_depth=max_depth, _depth=_depth + 1)
        else:
            if max_depth is None or _depth <= max_depth:
                yield from _iter_frame_nodes(child.get("children"), max_depth=max_depth, _depth=_depth)


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
        "figma-file-key": ("figma", "file_key"),
        "figma-frame-id": ("figma", "frame_id"),
        "figma-title-node": ("figma", "nodes", "title"),
        "figma-subtitle-node": ("figma", "nodes", "subtitle"),
        "figma-business-node": ("figma", "nodes", "business"),
        "figma-title-name": ("figma", "names", "title"),
        "figma-subtitle-name": ("figma", "names", "subtitle"),
        "figma-business-name": ("figma", "names", "business"),
        "figma-background-node": ("figma", "background_nodes"),
        "figma-background-name": ("figma", "background_names"),
        "figma-scale": ("figma", "scale"),
        "figma-format": ("figma", "format"),
        "figma-clear-background": ("figma", "clear_background"),
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
    elif final in {"overlay", "clear_background"}:
        cursor[final] = value.lower() in {"1", "true", "yes", "on"}
    elif final == "scale":
        try:
            cursor[final] = float(value)
        except ValueError as err:
            raise click.UsageError("figma.scale 값은 숫자여야 합니다.") from err
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
