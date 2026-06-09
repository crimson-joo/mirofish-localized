#!/usr/bin/env python3
"""End-to-end validation for PDF embedded visual analysis.

Creates representative PDFs/images, uploads them through MiroFish, verifies that
visual PDF pages are converted into multimodal text, then builds Graphiti graphs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import fitz  # PyMuPDF
import requests

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:5001"
LOCALE = sys.argv[2] if len(sys.argv) > 2 else "ko"
PROJECTS_DIR = Path(__file__).resolve().parents[1] / "backend" / "uploads" / "projects"


def make_text_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(54, 54, 540, 360),
        "Company analysis case: Text-only PDF.\n"
        "A fictional manufacturer, CaseCorp, reports demand growth in enterprise accounts, "
        "higher input costs, and a management plan to protect operating margin through pricing and automation.\n"
        "Simulation question: how would investors, customers, suppliers, and employees react?",
        fontsize=12,
    )
    doc.save(path)
    doc.close()


def make_chart_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((54, 54), "Company analysis case: revenue vs margin chart", fontsize=14)
    page.insert_text((54, 86), "The chart shows revenue rising while operating margin dips in the final period.", fontsize=11)
    years = ["2022", "2023", "2024", "2025E"]
    values = [80, 110, 145, 170]
    margins = [22, 21, 18, 16]
    x0, y_base = 80, 430
    for i, (year, value, margin) in enumerate(zip(years, values, margins)):
        x = x0 + i * 90
        height = value
        page.draw_rect(fitz.Rect(x, y_base - height, x + 42, y_base), color=(0.1, 0.3, 0.9), fill=(0.35, 0.55, 1.0))
        page.insert_text((x, y_base + 18), year, fontsize=10)
        page.insert_text((x, y_base - height - 14), f"Rev {value}", fontsize=8)
        page.insert_text((x, y_base - height - 28), f"Margin {margin}%", fontsize=8)
    page.draw_line((70, y_base), (490, y_base), color=(0, 0, 0))
    doc.save(path)
    doc.close()


def make_embedded_image_pdf(path: Path, image_path: Path) -> None:
    img_doc = fitz.open()
    img_page = img_doc.new_page(width=620, height=360)
    img_page.draw_rect(fitz.Rect(30, 30, 590, 330), color=(0.2, 0.2, 0.2), fill=(0.95, 0.97, 1.0))
    img_page.insert_text((54, 70), "Policy/finance infographic", fontsize=20)
    boxes = [
        ("USD stablecoin demand", 60, 130),
        ("Tokenized Treasury collateral", 250, 130),
        ("Bank deposit pressure", 440, 130),
        ("On-chain settlement growth", 160, 250),
        ("Regulatory oversight risk", 360, 250),
    ]
    for label, x, y in boxes:
        img_page.draw_rect(fitz.Rect(x, y, x + 140, y + 46), color=(0.1, 0.45, 0.3), fill=(0.75, 0.93, 0.82))
        img_page.insert_textbox(fitz.Rect(x + 6, y + 8, x + 134, y + 42), label, fontsize=8)
    for start, end in [((200, 153), (250, 153)), ((390, 153), (440, 153)), ((320, 176), (230, 250)), ((390, 176), (430, 250))]:
        img_page.draw_line(start, end, color=(0.1, 0.1, 0.1), width=1.5)
    pix = img_page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    pix.save(image_path)
    img_doc.close()

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((54, 54), "Policy/finance case: PDF containing an embedded infographic image", fontsize=13)
    page.insert_image(fitz.Rect(54, 100, 560, 395), filename=str(image_path))
    page.insert_textbox(
        fitz.Rect(54, 420, 540, 520),
        "Simulation question: how would policymakers, banks, crypto exchanges, and treasury issuers respond?",
        fontsize=11,
    )
    doc.save(path)
    doc.close()


def create_cases(tmp: Path) -> list[dict]:
    text_pdf = tmp / "case_text_only_company.pdf"
    chart_pdf = tmp / "case_company_chart.pdf"
    embedded_pdf = tmp / "case_policy_embedded_infographic.pdf"
    standalone_image = tmp / "case_policy_infographic.png"
    make_text_pdf(text_pdf)
    make_chart_pdf(chart_pdf)
    make_embedded_image_pdf(embedded_pdf, standalone_image)
    return [
        {
            "name": "text_only_company_pdf",
            "files": [text_pdf],
            "requirement": "기업 분석 시뮬레이션: 투자자, 고객, 공급사, 직원의 반응을 예측한다.",
            "expect_visual": False,
        },
        {
            "name": "company_chart_pdf",
            "files": [chart_pdf],
            "requirement": "기업 분석 시뮬레이션: 매출 성장과 마진 하락 차트를 보고 이해관계자 반응을 예측한다.",
            "expect_visual": True,
        },
        {
            "name": "mixed_policy_pdf_and_image",
            "files": [embedded_pdf, standalone_image],
            "requirement": "금융/정책 시뮬레이션: 스테이블코인, 토큰화 국채, 은행 예금 압력, 규제 리스크에 대한 행위자 반응을 예측한다.",
            "expect_visual": True,
        },
    ]


def api_post(path: str, **kwargs):
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("Accept-Language", LOCALE)
    headers.setdefault("X-Locale", LOCALE)
    if "json" in kwargs and isinstance(kwargs["json"], dict):
        kwargs["json"].setdefault("locale", LOCALE)
    if "data" in kwargs and isinstance(kwargs["data"], dict):
        kwargs["data"].setdefault("locale", LOCALE)
    response = requests.post(BASE + path, timeout=600, headers=headers, **kwargs)
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    if response.status_code >= 400 or payload.get("success") is False:
        raise RuntimeError(f"POST {path} failed status={response.status_code} payload={json.dumps(payload, ensure_ascii=False)[:2000]}")
    return payload


def api_get(path: str):
    response = requests.get(BASE + path, timeout=60, headers={"Accept-Language": LOCALE, "X-Locale": LOCALE})
    payload = response.json()
    if response.status_code >= 400 or payload.get("success") is False:
        raise RuntimeError(f"GET {path} failed status={response.status_code} payload={json.dumps(payload, ensure_ascii=False)[:2000]}")
    return payload


def upload_case(case: dict) -> dict:
    handles = []
    try:
        files = []
        for p in case["files"]:
            fh = open(p, "rb")
            handles.append(fh)
            files.append(("files", (p.name, fh, "application/octet-stream")))
        payload = api_post(
            "/api/graph/ontology/generate",
            data={
                "project_name": f"PDF multimodal E2E - {case['name']}",
                "simulation_requirement": case["requirement"],
                "additional_context": "Synthetic E2E validation fixture; facts are intentionally fictional and controlled.",
            },
            files=files,
        )
    finally:
        for fh in handles:
            fh.close()
    return payload["data"]


def extracted_text(project_id: str) -> str:
    path = PROJECTS_DIR / project_id / "extracted_text.txt"
    if not path.exists():
        raise RuntimeError(f"extracted text missing for {project_id}: {path}")
    return path.read_text(encoding="utf-8")


def build_graph(project_id: str, name: str) -> dict:
    payload = api_post("/api/graph/build", json={"project_id": project_id, "graph_name": name, "chunk_size": 900, "chunk_overlap": 80, "force": True})
    task_id = payload["data"]["task_id"]
    deadline = time.time() + 900
    last = None
    while time.time() < deadline:
        task = api_get(f"/api/graph/task/{task_id}")["data"]
        last = task
        status = task.get("status")
        if status == "completed":
            return task
        if status == "failed":
            raise RuntimeError(f"graph build failed task={task_id} task={json.dumps(task, ensure_ascii=False)[:2000]}")
        time.sleep(5)
    raise TimeoutError(f"graph build timed out task={task_id} last={json.dumps(last, ensure_ascii=False)[:2000]}")


def main() -> int:
    health = requests.get(BASE + "/health", timeout=20, headers={"Accept-Language": LOCALE, "X-Locale": LOCALE})
    health.raise_for_status()
    results = []
    with tempfile.TemporaryDirectory(prefix="mirofish_pdf_mm_e2e_") as tmp_raw:
        tmp = Path(tmp_raw)
        cases = create_cases(tmp)
        case_filter = os.environ.get("MIROFISH_E2E_CASE")
        if case_filter:
            cases = [case for case in cases if case["name"] == case_filter]
            if not cases:
                raise ValueError(f"Unknown MIROFISH_E2E_CASE={case_filter}")
        for case in cases:
            uploaded = upload_case(case)
            project_id = uploaded["project_id"]
            text = extracted_text(project_id)
            visual_present = "[PDF visual analysis:" in text or "[Multimodal image analysis:" in text
            if case["expect_visual"] and not visual_present:
                raise AssertionError(f"{case['name']} expected visual analysis marker")
            if not case["expect_visual"] and visual_present:
                raise AssertionError(f"{case['name']} did not expect visual analysis marker")
            graph_task = build_graph(project_id, case["name"])
            result = graph_task.get("result") or {}
            if result.get("node_count", 0) <= 0 or result.get("edge_count", 0) <= 0:
                raise AssertionError(f"{case['name']} graph has no useful nodes/edges: {result}")
            results.append(
                {
                    "case": case["name"],
                    "project_id": project_id,
                    "graph_id": result.get("graph_id"),
                    "visual_analysis_detected": visual_present,
                    "text_length": uploaded.get("total_text_length"),
                    "node_count": result.get("node_count"),
                    "edge_count": result.get("edge_count"),
                    "chunk_count": result.get("chunk_count"),
                }
            )
            print("PASS", json.dumps(results[-1], ensure_ascii=False))
    print("SUMMARY", json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
