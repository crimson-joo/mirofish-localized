import argparse
import importlib.util
import json
from pathlib import Path


def _load_runner_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "bettafish-single-e2e-runner.py"
    spec = importlib.util.spec_from_file_location("bettafish_single_e2e_runner_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner_module()


def test_apply_handoff_manifest_defaults_report_topic_and_locale(tmp_path):
    report = tmp_path / "seed.md"
    report.write_text("# 한국어 보고서", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "topic": "AI 검색엔진 시장",
        "language": "Korean",
        "seed_document": {"path": str(report)},
    }, ensure_ascii=False), encoding="utf-8")
    args = argparse.Namespace(
        bettafish_manifest=str(manifest),
        bettafish_report=None,
        topic=None,
        locale=None,
    )

    runner.apply_handoff_manifest_defaults(args)

    assert args.bettafish_report == str(report)
    assert args.topic == "AI 검색엔진 시장"
    assert args.locale == "ko"


def test_apply_handoff_manifest_does_not_override_explicit_args(tmp_path):
    report = tmp_path / "seed.md"
    report.write_text("# 한국어 보고서", encoding="utf-8")
    other_report = tmp_path / "explicit.md"
    other_report.write_text("# 명시 보고서", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "topic": "manifest topic",
        "language": "English",
        "seed_document": {"path": str(report)},
    }), encoding="utf-8")
    args = argparse.Namespace(
        bettafish_manifest=str(manifest),
        bettafish_report=str(other_report),
        topic="explicit topic",
        locale="ko",
    )

    runner.apply_handoff_manifest_defaults(args)

    assert args.bettafish_report == str(other_report)
    assert args.topic == "explicit topic"
    assert args.locale == "ko"
