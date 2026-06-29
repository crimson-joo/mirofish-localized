from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mirofish_aquarium_runner.py"
spec = importlib.util.spec_from_file_location("mirofish_aquarium_runner", SCRIPT)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def _write_report(tmp_path: Path, body: str = "# 한국어 보고서\n\n시장 반응과 리스크를 요약합니다.") -> Path:
    report = tmp_path / "final_report.md"
    report.write_text(body, encoding="utf-8")
    return report


def _write_manifest(tmp_path: Path, report: Path | None = None, **overrides: object) -> Path:
    manifest = {
        "handoff_version": "aquarium.v1",
        "source_product": "bettafish-localized",
        "target_product": "aquarium",
        "topic": "AI 검색엔진 시장 변화",
        "locale": "ko",
        "final_report_path": str(report or _write_report(tmp_path)),
        "intermediate_outputs": {},
        "sources": [],
        "provider": "bettafish_cli",
        "warnings": ["BettaFish source coverage was partial."],
        "data_gaps": ["sources[] was empty in the handoff manifest."],
    }
    manifest.update(overrides)
    path = tmp_path / "handoff_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def test_aquarium_runner_requires_valid_manifest(tmp_path):
    missing = tmp_path / "missing.json"

    try:
        runner.load_aquarium_manifest(missing)
    except runner.RunnerContractError as exc:
        assert "AQUARIUM_HANDOFF_MANIFEST" in str(exc)
    else:
        raise AssertionError("missing manifest should fail")

    bad = _write_manifest(tmp_path, handoff_version="wrong")
    try:
        runner.load_aquarium_manifest(bad)
    except runner.RunnerContractError as exc:
        assert "handoff_version" in str(exc)
    else:
        raise AssertionError("wrong handoff_version should fail")

    broken = _write_manifest(tmp_path, final_report_path=str(tmp_path / "no-report.md"))
    try:
        runner.load_aquarium_manifest(broken)
    except runner.RunnerContractError as exc:
        assert "final_report_path" in str(exc)
    else:
        raise AssertionError("unreadable report should fail")


def test_aquarium_runner_writes_valid_mirofish_result_from_bridge_summary(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path)
    run_dir = tmp_path / "aquarium-run"
    run_dir.mkdir()

    bridge_summary = {
        "success": True,
        "source_report": json.loads(manifest.read_text(encoding="utf-8"))["final_report_path"],
        "state_path": str(run_dir / "mirofish_bridge_state.json"),
        "project_id": "proj_1",
        "graph_id": "graph_1",
        "simulation_id": "sim_1",
        "report_id": "report_1",
        "graph_nodes": 2,
        "graph_edges": 1,
        "graph_chunk_count": 1,
        "prepare_status": "ready",
        "runner_status": "running",
        "current_round": 1,
        "total_rounds": 1,
        "actions": 1,
        "graph_memory_update_enabled": True,
        "report_chars": 20,
        "report_hangul": 8,
        "report_cjk": 0,
        "chat_preview": "핵심 테마 요약",
        "sample_action": {"agent_name": "Agent A", "action_type": "POST", "content": "시장 신호를 토론"},
    }
    (run_dir / "mirofish_bridge_state.json").write_text(
        json.dumps({"final_summary": bridge_summary, "ontology": {"entity_types": {"Company": 1}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    def fake_bridge(command, cwd=None):
        assert "--bettafish-report" in command
        assert "--topic" in command
        assert "--locale" in command
        return bridge_summary

    monkeypatch.setattr(runner, "run_bridge_command", fake_bridge)
    env = {
        "AQUARIUM_TOPIC": "AI 검색엔진 시장 변화",
        "AQUARIUM_LOCALE": "ko",
        "AQUARIUM_MODE": "single",
        "AQUARIUM_RUN_DIR": str(run_dir),
        "AQUARIUM_HANDOFF_MANIFEST": str(manifest),
    }

    result = runner.run_from_env(env)

    output = run_dir / "mirofish_result.json"
    assert output.exists()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert result == written
    assert written["provider"] == "mirofish_cli"
    assert written["ontology"]["entities"][0]["name"] == "Company"
    assert written["personas"][0]["name"] == "Agent A"
    assert written["simulation"]["mode"] == "single"
    assert written["simulation"]["universes"][0]["events"] == ["시장 신호를 토론"]
    assert Path(written["simulation_report"]["path"]).exists()
    assert "BettaFish source coverage was partial." in written["warnings"]


def test_aquarium_runner_preserves_graph_memory_warnings(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path)
    run_dir = tmp_path / "aquarium-run"
    run_dir.mkdir()
    summary = {
        "success": True,
        "simulation_id": "sim_1",
        "graph_id": "graph_1",
        "graph_nodes": 0,
        "graph_edges": 0,
        "actions": 0,
        "graph_memory_update_enabled": False,
        "report_chars": 0,
        "report_cjk": 2,
        "chat_preview": "",
        "sample_action": {},
        "warnings": ["native_action_ingest_state=failed"],
    }
    monkeypatch.setattr(runner, "run_bridge_command", lambda command, cwd=None: summary)
    env = {
        "AQUARIUM_TOPIC": "AI 검색엔진 시장 변화",
        "AQUARIUM_LOCALE": "ko",
        "AQUARIUM_MODE": "single",
        "AQUARIUM_RUN_DIR": str(run_dir),
        "AQUARIUM_HANDOFF_MANIFEST": str(manifest),
    }

    result = runner.run_from_env(env)

    assert any("graph_memory_update_enabled=false" in warning for warning in result["warnings"])
    assert "native_action_ingest_state=failed" in result["warnings"]
    assert any("report_cjk" in warning for warning in result["warnings"])


def test_aquarium_runner_rejects_unseeded_multiverse(tmp_path):
    manifest = _write_manifest(tmp_path)
    run_dir = tmp_path / "aquarium-run"
    run_dir.mkdir()
    env = {
        "AQUARIUM_TOPIC": "AI 검색엔진 시장 변화",
        "AQUARIUM_LOCALE": "ko",
        "AQUARIUM_MODE": "multiverse",
        "AQUARIUM_RUN_DIR": str(run_dir),
        "AQUARIUM_HANDOFF_MANIFEST": str(manifest),
    }

    code = runner.main([], env=env)

    assert code == 2
    assert not (run_dir / "mirofish_result.json").exists()


def test_aquarium_runner_cli_contract_smoke_with_fake_bridge(tmp_path):
    manifest = _write_manifest(tmp_path)
    run_dir = tmp_path / "aquarium-run"
    run_dir.mkdir()
    fake_bridge = tmp_path / "fake_bridge.py"
    fake_bridge.write_text(
        """
import json
import sys
from pathlib import Path
args = sys.argv
state_path = Path(args[args.index('--state-path') + 1])
report_path = Path(args[args.index('--bettafish-report') + 1])
state_path.parent.mkdir(parents=True, exist_ok=True)
summary = {
    'success': True,
    'source_report': str(report_path),
    'state_path': str(state_path),
    'project_id': 'proj_cli',
    'graph_id': 'graph_cli',
    'simulation_id': 'sim_cli',
    'report_id': 'report_cli',
    'graph_nodes': 1,
    'graph_edges': 0,
    'actions': 1,
    'graph_memory_update_enabled': True,
    'report_chars': 12,
    'report_hangul': 5,
    'report_cjk': 0,
    'chat_preview': 'CLI 요약',
    'sample_action': {'agent_name': 'CLI Agent', 'action_type': 'POST', 'content': 'CLI 이벤트'},
}
state_path.write_text(json.dumps({'final_summary': summary}, ensure_ascii=False), encoding='utf-8')
print(json.dumps({'event': 'final_summary', **summary}, ensure_ascii=False))
""".strip(),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "AQUARIUM_TOPIC": "AI 검색엔진 시장 변화",
            "AQUARIUM_LOCALE": "ko",
            "AQUARIUM_MODE": "single",
            "AQUARIUM_RUN_DIR": str(run_dir),
            "AQUARIUM_HANDOFF_MANIFEST": str(manifest),
            "MIROFISH_AQUARIUM_BRIDGE_COMMAND": f"{sys.executable} {fake_bridge}",
        }
    )

    completed = subprocess.run([sys.executable, str(SCRIPT)], env=env, text=True, capture_output=True, check=False)

    assert completed.returncode == 0, completed.stderr
    output = json.loads((run_dir / "mirofish_result.json").read_text(encoding="utf-8"))
    assert output["provider"] == "mirofish_cli"
    assert output["simulation_report"]["body"]
    assert output["personas"][0]["role"] == "simulation_participant"
