from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bettafish-single-e2e-runner.py"
spec = importlib.util.spec_from_file_location("bettafish_single_e2e_runner", SCRIPT)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_bridge_state_marks_previous_running_attempt_interrupted(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "attempts": [
                    {"attempt_id": "old", "pid": 123, "started_at": "2026-01-01T00:00:00Z", "status": "running"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    state = runner.BridgeState(state_path)
    state.mark_attempt("completed")
    state.finished = True

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["attempts"][0]["status"] == "interrupted_or_unknown"
    assert data["attempts"][-1]["status"] == "completed"
    assert data["current_attempt_id"].startswith("attempt_")


def test_audit_text_counts_hangul_and_cjk():
    audit = runner.audit_text("sample", "한국어 mixed 中文")

    assert audit["sample_chars"] == len("한국어 mixed 中文")
    assert audit["sample_hangul"] == 3
    assert audit["sample_cjk"] == 2


def test_arg_parser_keeps_graph_memory_on_by_default():
    args = runner.build_parser().parse_args(
        [
            "--bettafish-report",
            "/tmp/report.md",
            "--topic",
            "테스트 주제",
        ]
    )

    assert args.enable_graph_memory_update is True
    assert args.max_rounds == 1
    assert args.profile_count == 2
