"""Helpers for interacting with the Figma API."""

from __future__ import annotations

import os
import time
from io import BytesIO
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

import requests
from PIL import Image


FIGMA_TOKEN_ENV = "FIGMA_API_KEY"
_LEGACY_FIGMA_TOKEN_ENV = "FIGMA_ACCESS_TOKEN"
FIGMA_BASE_URL = "https://api.figma.com/v1"


class FigmaNotConfigured(RuntimeError):
    """Raised when Figma integration is requested but not configured."""


class FigmaAPIError(RuntimeError):
    """Raised when the Figma API returns an unexpected response."""


@dataclass(frozen=True)
class NodeBounds:
    """Bounding box information for a Figma node in frame coordinates."""

    node_id: str
    name: str
    x: float
    y: float
    width: float
    height: float

    def to_box(self, scale: float, origin_x: float, origin_y: float) -> Tuple[int, int, int, int]:
        """Return a Pillow-friendly bounding box for a rendered frame."""

        x0 = (self.x - origin_x) * scale
        y0 = (self.y - origin_y) * scale
        x1 = x0 + self.width * scale
        y1 = y0 + self.height * scale
        return (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))


@dataclass
class TemplateLayout:
    """Resolved layout information for a Figma frame."""

    frame_bounds: NodeBounds
    slots: Mapping[str, NodeBounds]
    backgrounds: Tuple[NodeBounds, ...]
    scale: float

    def box_for(self, slot: str) -> Optional[Tuple[int, int, int, int]]:
        node = self.slots.get(slot)
        if not node:
            return None
        frame = self.frame_bounds
        return node.to_box(self.scale, frame.x, frame.y)

    def background_boxes(self) -> Tuple[Tuple[int, int, int, int], ...]:
        frame = self.frame_bounds
        return tuple(node.to_box(self.scale, frame.x, frame.y) for node in self.backgrounds)


def get_token() -> Optional[str]:
    """Return the configured Figma personal access token, if available."""

    token = os.environ.get(FIGMA_TOKEN_ENV) or os.environ.get(_LEGACY_FIGMA_TOKEN_ENV)
    if token:
        return token.strip()
    return None


def build_headers(token: str) -> Mapping[str, str]:
    """Return headers suitable for Figma personal access tokens."""

    return {
        "X-Figma-Token": token,
        "Accept": "application/json",
    }


class FigmaClient:
    """Simple wrapper around the Figma REST API."""

    def __init__(self, token: str, session: Optional[requests.Session] = None) -> None:
        if not token:
            raise FigmaNotConfigured(
                "Figma API 토큰이 설정되지 않았습니다. FIGMA_API_KEY 또는 FIGMA_ACCESS_TOKEN 환경 변수를 확인하세요."
            )
        self._token = token
        self._session = session or requests.Session()

    # Public API ---------------------------------------------------------

    def fetch_layout(
        self,
        file_key: str,
        frame_id: str,
        slot_nodes: Mapping[str, str],
        slot_names: Mapping[str, str],
        background_nodes: Tuple[str, ...] = (),
        background_names: Tuple[str, ...] = (),
        *,
        scale: float = 1.0,
    ) -> TemplateLayout:
        """Return layout metadata for a frame and its text slots."""

        node_ids = [frame_id]
        node_ids += [node for node in slot_nodes.values() if node]
        node_ids += [node for node in background_nodes if node]
        payload = self._get_json(
            f"{FIGMA_BASE_URL}/files/{file_key}/nodes",
            params={"ids": ",".join(node_ids)},
        )

        nodes = payload.get("nodes")
        if not isinstance(nodes, Mapping):  # pragma: no cover - defensive
            raise FigmaAPIError("Figma 응답에서 노드 정보를 찾을 수 없습니다.")

        frame_data = nodes.get(frame_id)
        if not frame_data:
            raise FigmaAPIError(f"프레임 노드({frame_id}) 정보를 가져올 수 없습니다.")

        frame_node = _extract_node(frame_id, frame_data)
        frame_bounds = _bounds_from_node(frame_node)

        resolved_slots: Dict[str, NodeBounds] = {}
        resolved_backgrounds: List[NodeBounds] = []
        for slot_name in slot_nodes.keys() | slot_names.keys():
            node_id = slot_nodes.get(slot_name)
            slot_node_payload = None
            if node_id:
                node_payload = nodes.get(node_id)
                if not node_payload:
                    raise FigmaAPIError(f"슬롯 '{slot_name}'에 대한 노드({node_id}) 정보를 찾을 수 없습니다.")
                slot_node_payload = _extract_node(node_id, node_payload)
            else:
                lookup_name = slot_names.get(slot_name)
                if lookup_name:
                    slot_node_payload = _find_child_by_name(frame_node, lookup_name)
                    if slot_node_payload is None:
                        raise FigmaAPIError(
                            f"슬롯 '{slot_name}' 이름 '{lookup_name}'을(를) 프레임에서 찾을 수 없습니다."
                        )

            if slot_node_payload is None:
                continue

            resolved_slots[slot_name] = _bounds_from_node(slot_node_payload)

        for node_id in background_nodes:
            if not node_id:
                continue
            node_payload = nodes.get(node_id)
            if not node_payload:
                raise FigmaAPIError(f"배경 노드({node_id}) 정보를 찾을 수 없습니다.")
            resolved_backgrounds.append(_bounds_from_node(_extract_node(node_id, node_payload)))

        for lookup_name in background_names:
            if not lookup_name:
                continue
            background_payload = _find_child_by_name(frame_node, lookup_name, include_self=True)
            if background_payload is None:
                raise FigmaAPIError(f"배경 레이어 이름 '{lookup_name}'을(를) 프레임에서 찾을 수 없습니다.")
            resolved_backgrounds.append(_bounds_from_node(background_payload))

        frame_width = frame_bounds.width or 1
        render_width = frame_width * scale
        resolved_scale = render_width / frame_width

        return TemplateLayout(
            frame_bounds=frame_bounds,
            slots=resolved_slots,
            backgrounds=tuple(resolved_backgrounds),
            scale=resolved_scale,
        )

    def fetch_node_tree(self, file_key: str, node_id: str) -> Mapping[str, object]:
        """Return the hydrated node tree for the given node identifier."""

        payload = self._get_json(
            f"{FIGMA_BASE_URL}/files/{file_key}/nodes",
            params={"ids": node_id},
        )

        nodes = payload.get("nodes")
        if not isinstance(nodes, Mapping):
            raise FigmaAPIError("Figma 응답에서 노드 정보를 찾을 수 없습니다.")

        node_payload = nodes.get(node_id)
        if not node_payload:
            raise FigmaAPIError(f"노드({node_id}) 정보를 가져올 수 없습니다.")

        return _extract_node(node_id, node_payload)

    def render_frame(
        self,
        file_key: str,
        frame_id: str,
        *,
        format: str = "png",
        scale: float = 1.0,
        retry: int = 3,
    ) -> Image.Image:
        """Render the specified frame and return a Pillow image."""

        data = self._get_json(
            f"{FIGMA_BASE_URL}/images/{file_key}",
            params={"ids": frame_id, "format": format, "scale": scale},
        )
        images = data.get("images")
        if not isinstance(images, Mapping) or frame_id not in images:
            raise FigmaAPIError("Figma 응답에서 렌더링 URL을 찾을 수 없습니다.")

        image_url = images[frame_id]
        if not image_url:
            raise FigmaAPIError("Figma 이미지 URL이 비어 있습니다.")

        attempts = 0
        while True:
            attempts += 1
            response = self._session.get(image_url, timeout=30)
            if response.status_code == 200:
                image = Image.open(BytesIO(response.content))
                return image.convert("RGBA")
            if attempts >= retry:
                raise FigmaAPIError(f"Figma 이미지 다운로드 실패 (status={response.status_code}).")
            time.sleep(1.5)

    def fetch_file_document(self, file_key: str) -> Mapping[str, object]:
        """Return the full document tree for the given file."""

        payload = self._get_json(f"{FIGMA_BASE_URL}/files/{file_key}")
        document = payload.get("document")
        if not isinstance(document, Mapping):
            raise FigmaAPIError("Figma 응답에서 document 정보를 찾을 수 없습니다.")
        return document

    # Internal helpers ---------------------------------------------------

    def _get_json(self, url: str, params: Optional[Mapping[str, object]] = None) -> Mapping[str, object]:
        response = self._session.get(url, headers=build_headers(self._token), params=params, timeout=30)
        if response.status_code == 401:
            raise FigmaNotConfigured("Figma API 토큰이 유효하지 않습니다.")
        if response.status_code >= 400:
            raise FigmaAPIError(f"Figma API 호출 실패 (status={response.status_code}): {response.text}")
        return response.json()


def _extract_node(node_id: str, payload: Mapping[str, object]) -> Mapping[str, object]:
    document = payload.get("document")
    if not isinstance(document, Mapping):  # pragma: no cover - defensive
        raise FigmaAPIError(f"노드 {node_id}의 document 정보를 찾을 수 없습니다.")
    return document


def _bounds_from_node(node: Mapping[str, object]) -> NodeBounds:
    bbox = node.get("absoluteBoundingBox")
    if not isinstance(bbox, Mapping):
        raise FigmaAPIError(f"노드 {node.get('id', '<unknown>')}에 absoluteBoundingBox 정보가 없습니다.")

    name = str(node.get("name", ""))
    x = float(bbox.get("x", 0.0))
    y = float(bbox.get("y", 0.0))
    width = float(bbox.get("width", 0.0))
    height = float(bbox.get("height", 0.0))
    node_id = str(node.get("id", "")) or name

    return NodeBounds(node_id=node_id, name=name, x=x, y=y, width=width, height=height)


def _find_child_by_name(
    node: Mapping[str, object],
    target: str,
    *,
    include_self: bool = False,
) -> Optional[Mapping[str, object]]:
    if include_self:
        name = node.get("name")
        if isinstance(name, str) and name.strip() == target.strip():
            return node

    for child in node.get("children", []) or []:
        if not isinstance(child, Mapping):
            continue
        child_name = child.get("name")
        if isinstance(child_name, str) and child_name.strip() == target.strip():
            return child
        found = _find_child_by_name(child, target, include_self=False)
        if found is not None:
            return found
    return None

__all__ = [
    "FigmaAPIError",
    "FigmaClient",
    "FigmaNotConfigured",
    "FIGMA_TOKEN_ENV",
    "TemplateLayout",
    "get_token",
]
