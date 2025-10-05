"""Helpers for interacting with the Figma API."""

from __future__ import annotations

import os
import time
from io import BytesIO
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

import requests
from PIL import Image


FIGMA_TOKEN_ENV = "FIGMA_ACCESS_TOKEN"
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
    scale: float

    def box_for(self, slot: str) -> Optional[Tuple[int, int, int, int]]:
        node = self.slots.get(slot)
        if not node:
            return None
        frame = self.frame_bounds
        return node.to_box(self.scale, frame.x, frame.y)


def get_token() -> Optional[str]:
    """Return the configured Figma personal access token, if available."""

    token = os.environ.get(FIGMA_TOKEN_ENV)
    if token:
        return token.strip()
    return None


def build_headers(token: str) -> Mapping[str, str]:
    return {"Authorization": f"Bearer {token}"}


class FigmaClient:
    """Simple wrapper around the Figma REST API."""

    def __init__(self, token: str, session: Optional[requests.Session] = None) -> None:
        if not token:
            raise FigmaNotConfigured("Figma API 토큰이 설정되지 않았습니다. FIGMA_ACCESS_TOKEN 환경 변수를 확인하세요.")
        self._token = token
        self._session = session or requests.Session()

    # Public API ---------------------------------------------------------

    def fetch_layout(
        self,
        file_key: str,
        frame_id: str,
        slot_nodes: Mapping[str, str],
        *,
        scale: float = 1.0,
    ) -> TemplateLayout:
        """Return layout metadata for a frame and its text slots."""

        node_ids = [frame_id] + [node for node in slot_nodes.values() if node]
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
        for slot_name, node_id in slot_nodes.items():
            if not node_id:
                continue
            node_payload = nodes.get(node_id)
            if not node_payload:
                raise FigmaAPIError(f"슬롯 '{slot_name}'에 대한 노드({node_id}) 정보를 찾을 수 없습니다.")
            slot_node = _extract_node(node_id, node_payload)
            resolved_slots[slot_name] = _bounds_from_node(slot_node)

        frame_width = frame_bounds.width or 1
        render_width = frame_width * scale
        resolved_scale = render_width / frame_width

        return TemplateLayout(frame_bounds=frame_bounds, slots=resolved_slots, scale=resolved_scale)

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

__all__ = [
    "FigmaAPIError",
    "FigmaClient",
    "FigmaNotConfigured",
    "FIGMA_TOKEN_ENV",
    "TemplateLayout",
    "get_token",
]
