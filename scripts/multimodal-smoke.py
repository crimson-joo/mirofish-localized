#!/usr/bin/env python3
"""Smoke-test the configured OpenAI-compatible multimodal endpoint.

Default target: Ollama on the macOS host with gemma4:12b-mlx.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.utils.multimodal_client import MultimodalClient  # noqa: E402


def _make_test_image(path: str) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 320), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((30, 30, 610, 290), outline="black", width=4)
    draw.text((70, 80), "BTC + USD", fill="black")
    draw.text((70, 150), "Stablecoin Treasury", fill="black")
    draw.line((80, 250, 560, 170), fill="blue", width=6)
    img.save(path)


def main() -> int:
    os.environ.setdefault("MULTIMODAL_BASE_URL", "http://127.0.0.1:11434/v1")
    os.environ.setdefault("MULTIMODAL_MODEL_NAME", "gemma4:12b-mlx")
    os.environ.setdefault("MULTIMODAL_API_KEY", "ollama")

    # Config is evaluated at import time, so mirror env into Config for direct script runs.
    from app.config import Config

    Config.MULTIMODAL_BASE_URL = os.environ["MULTIMODAL_BASE_URL"]
    Config.MULTIMODAL_MODEL_NAME = os.environ["MULTIMODAL_MODEL_NAME"]
    Config.MULTIMODAL_API_KEY = os.environ["MULTIMODAL_API_KEY"]

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fp:
        image_path = fp.name
    _make_test_image(image_path)

    try:
        text = MultimodalClient().describe_image(
            image_path,
            prompt=(
                "Read this chart-like image. Mention any visible text and the overall visual signal. "
                "Return one concise plain-text sentence."
            ),
        )
        if not text.strip():
            print("FAIL empty multimodal response")
            return 1
        lowered = text.lower()
        if not any(token in lowered for token in ["chart", "graph", "line", "text", "image", "visual"]):
            print(f"FAIL multimodal response did not look image-grounded: {text[:240]!r}")
            return 1
        print(f"PASS multimodal model={Config.MULTIMODAL_MODEL_NAME} response={text[:220]!r}")
        return 0
    finally:
        Path(image_path).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
