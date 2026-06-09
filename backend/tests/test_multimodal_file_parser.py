from pathlib import Path
from unittest.mock import patch

import fitz

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


def test_pdf_with_chart_page_adds_visual_analysis(tmp_path):
    from app.config import Config

    Config.MULTIMODAL_BASE_URL = "http://127.0.0.1:11434/v1"
    Config.MULTIMODAL_MODEL_NAME = "gemma4:12b-mlx"
    Config.PDF_MULTIMODAL_ANALYSIS = True
    Config.PDF_MULTIMODAL_MAX_PAGES = 6

    pdf_path = tmp_path / "company_chart.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Company analysis: revenue expanded while margin compressed.")
    for idx, height in enumerate([40, 80, 120, 60, 150, 110, 90, 130]):
        x0 = 72 + idx * 40
        page.draw_rect(fitz.Rect(x0, 260 - height, x0 + 24, 260), color=(0, 0, 1), fill=(0.3, 0.5, 1))
    doc.save(pdf_path)
    doc.close()

    with patch("app.utils.multimodal_client.MultimodalClient.describe_image", return_value="visual chart: revenue bars trend upward") as mocked:
        text = FileParser.extract_text(str(pdf_path))

    assert "Company analysis" in text
    assert "PDF visual analysis" in text
    assert "visual chart: revenue bars trend upward" in text
    mocked.assert_called_once()


def test_text_only_pdf_does_not_call_multimodal(tmp_path):
    from app.config import Config

    Config.MULTIMODAL_BASE_URL = "http://127.0.0.1:11434/v1"
    Config.MULTIMODAL_MODEL_NAME = "gemma4:12b-mlx"
    Config.PDF_MULTIMODAL_ANALYSIS = True

    pdf_path = tmp_path / "text_only.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Plain text policy memo without figures or charts.")
    doc.save(pdf_path)
    doc.close()

    with patch("app.utils.multimodal_client.MultimodalClient.describe_image") as mocked:
        text = FileParser.extract_text(str(pdf_path))

    assert "Plain text policy memo" in text
    assert "PDF visual analysis" not in text
    mocked.assert_not_called()
