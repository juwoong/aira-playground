"""Command line interface for the Cardnews generator."""

from __future__ import annotations

import datetime as _dt
import copy
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import click

from . import get_version
from .config import DEFAULT_CONFIG, load_config, save_config, update_config
from .gemini import DEFAULT_MODEL, generate_cards as gemini_generate_cards, get_api_key
from .image import FontSpec, RenderOptions, create_card
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

    if not output and card_data.get("output"):
        output = Path(card_data["output"])

    if not output:
        output = Path(f"card_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")

    options = _build_render_options(config, size, no_overlay, no_shadow)
    fonts = _fonts_from_config(config)

    image = create_card(
        title=card_data.get("title", ""),
        subtitle=card_data.get("subtitle", ""),
        prompt=card_data.get("image_prompt"),
        background_path=str(background_path) if background_path else card_data.get("background_path"),
        fonts=fonts,
        options=options,
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

    with click.progressbar(enumerate(cards, start=1), label="카드뉴스 생성 중", length=len(cards)) as progress:
        for idx, entry in progress:
            output_path = entry.get("output") or f"card_{idx:02}.jpg"
            background_path = entry.get("background_path")
            if background_path:
                background_path = str(background_path)
            image = create_card(
                title=entry.get("title", ""),
                subtitle=entry.get("subtitle", ""),
                prompt=entry.get("image_prompt"),
                background_path=background_path,
                fonts=fonts,
                options=options,
            )
            image.save(output_dir / output_path)

    click.echo(f"총 {len(cards)}개의 이미지를 {output_dir}에 저장했습니다.")


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
    model_name = config.get("gemini", {}).get("model", DEFAULT_MODEL)
    cards = gemini_generate_cards(topic=topic, count=count, style=style, model_name=model_name, api_key=api_key)

    output_dir.mkdir(parents=True, exist_ok=True)

    for index, card in enumerate(cards, start=1):
        filename = f"{topic}_{index:02}.jpg"
        image = create_card(
            title=card.get("title", ""),
            subtitle=card.get("subtitle", ""),
            prompt=card.get("image_prompt"),
            background_path=str(card.get("background_path")) if card.get("background_path") else None,
            fonts=fonts,
            options=options,
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
    if not data.get("title"):
        raise click.UsageError("타이틀을 입력 옵션(--title) 또는 파일로 제공해야 합니다.")
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
    fonts_cfg = config.get("fonts", {}) if isinstance(config, dict) else {}
    title_cfg = fonts_cfg.get("title", {}) if isinstance(fonts_cfg, dict) else {}
    subtitle_cfg = fonts_cfg.get("subtitle", {}) if isinstance(fonts_cfg, dict) else {}
    return (
        FontSpec(path=title_cfg.get("path"), size=int(title_cfg.get("size", 72))),
        FontSpec(path=subtitle_cfg.get("path"), size=int(subtitle_cfg.get("size", 48))),
    )


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


if __name__ == "__main__":  # pragma: no cover
    main()
