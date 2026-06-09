"""Multimodal model client for image/chart extraction.

The default target is Ollama running on the macOS host with an OpenAI-compatible
endpoint, e.g. http://host.docker.internal:11434/v1 and gemma4:12b-mlx.
"""

import base64
import mimetypes
import re
from pathlib import Path
from typing import Optional

from openai import APITimeoutError, OpenAI

from ..config import Config


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class MultimodalClient:
    """OpenAI-compatible vision client used to turn image inputs into text."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        selected_base_url = base_url or Config.MULTIMODAL_BASE_URL
        selected_model = model or Config.MULTIMODAL_MODEL_NAME
        if not selected_base_url or not selected_model:
            raise ValueError("MULTIMODAL_BASE_URL and MULTIMODAL_MODEL_NAME must be configured for image analysis")

        self.api_key: str = api_key or Config.MULTIMODAL_API_KEY or "ollama"
        self.base_url: str = selected_base_url
        self.model: str = selected_model
        self.timeout = float(getattr(Config, "LLM_TIMEOUT_SECONDS", 180))

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    @staticmethod
    def is_image_path(file_path: str) -> bool:
        return Path(file_path).suffix.lower() in IMAGE_EXTENSIONS

    @staticmethod
    def _data_url(file_path: str) -> str:
        path = Path(file_path)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def describe_image(self, file_path: str, prompt: Optional[str] = None) -> str:
        """Analyze one image and return text suitable for ontology/GraphRAG input."""
        instruction = prompt or (
            "Analyze this image for a simulation/GraphRAG pipeline. "
            "Extract visible text, chart/table signals, entities, relationships, events, numbers, and uncertainties. "
            "Return concise but information-dense plain text. If text is unreadable, say so explicitly."
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                timeout=self.timeout,
                temperature=0.1,
                max_tokens=getattr(Config, "MULTIMODAL_MAX_TOKENS", 768),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": instruction},
                            {"type": "image_url", "image_url": {"url": self._data_url(file_path)}},
                        ],
                    }
                ],
            )
        except APITimeoutError as exc:
            raise TimeoutError(
                f"Multimodal request timed out after {self.timeout:.0f}s for model {self.model}"
            ) from exc

        content = response.choices[0].message.content or ""
        return re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
