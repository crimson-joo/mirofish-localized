from pathlib import Path
from unittest.mock import patch

from app.utils.file_parser import FileParser


def test_image_file_uses_multimodal_extraction(tmp_path):
    from app.config import Config

    Config.MULTIMODAL_BASE_URL = "http://127.0.0.1:11434/v1"
    Config.MULTIMODAL_MODEL_NAME = "gemma4:12b-mlx"
    image = tmp_path / "chart.png"
    image.write_bytes(b"not-a-real-png-but-client-is-mocked")

    with patch("app.utils.multimodal_client.MultimodalClient.describe_image", return_value="chart shows BTC rising"):
        text = FileParser.extract_text(str(image))

    assert "Multimodal image analysis" in text
    assert "chart shows BTC rising" in text


def test_image_extensions_are_supported():
    for suffix in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
        assert FileParser.is_supported(str(Path("sample").with_suffix(suffix)))
