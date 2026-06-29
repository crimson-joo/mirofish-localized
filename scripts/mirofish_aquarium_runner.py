#!/usr/bin/env python3
"""Aquarium contract runner for BettaFish → MiroFish single simulations.

Reads Aquarium's file-based runner environment, validates the BettaFish handoff
manifest, delegates the real single-run bridge to bettafish-single-e2e-runner.py,
and writes $AQUARIUM_RUN_DIR/mirofish_result.json for Aquarium to validate.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


class RunnerContractError(RuntimeError):
    """Input/output contract violation visible to Aquarium as runner failure."""


LOCALES = {"ko", "zh", "en"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunnerContractError(f"AQUARIUM_HANDOFF_MANIFEST not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RunnerContractError(f"AQUARIUM_HANDOFF_MANIFEST is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise RunnerContractError("AQUARIUM_HANDOFF_MANIFEST must be a JSON object")
    return data


def load_aquarium_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    manifest = _read_json(manifest_path)
    if manifest.get("handoff_version") != "aquarium.v1":
        raise RunnerContractError("handoff_version must be aquarium.v1")
    locale = manifest.get("locale")
    if locale not in LOCALES:
        raise RunnerContractError("locale must be one of ko, zh, en")
    report_value = str(manifest.get("final_report_path") or "").strip()
    if not report_value:
        raise RunnerContractError("final_report_path is required")
    report_path = Path(report_value).expanduser()
    if not report_path.is_absolute():
        report_path = (manifest_path.parent / report_path).resolve()
    else:
        report_path = report_path.resolve()
    if not report_path.is_file():
        raise RunnerContractError(f"final_report_path is not readable: {report_path}")
    manifest["final_report_path"] = str(report_path)
    return manifest


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise RunnerContractError(f"{name} is required")
    return value


def _bridge_script_path() -> Path:
    return Path(__file__).resolve().parent / "bettafish-single-e2e-runner.py"


def build_bridge_command(env: Mapping[str, str], manifest: Mapping[str, Any], run_dir: Path) -> list[str]:
    configured = (env.get("MIROFISH_AQUARIUM_BRIDGE_COMMAND") or "").strip()
    command = shlex.split(configured) if configured else [sys.executable, str(_bridge_script_path())]
    topic = env.get("AQUARIUM_TOPIC") or str(manifest.get("topic") or "")
    locale = env.get("AQUARIUM_LOCALE") or str(manifest.get("locale") or "ko")
    command.extend(
        [
            "--base-url",
            env.get("MIROFISH_BASE_URL", "http://127.0.0.1:5001"),
            "--bettafish-report",
            str(manifest["final_report_path"]),
            "--topic",
            topic,
            "--locale",
            locale,
            "--state-path",
            str(run_dir / "mirofish_bridge_state.json"),
            "--log-file",
            str(run_dir / "mirofish_bridge_events.jsonl"),
            "--max-rounds",
            env.get("MIROFISH_AQUARIUM_MAX_ROUNDS", "1"),
            "--profile-count",
            env.get("MIROFISH_AQUARIUM_PROFILE_COUNT", "2"),
        ]
    )
    return command


def run_bridge_command(command: Sequence[str], cwd: Path | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip().splitlines()[-3:]
        raise RunnerContractError("MiroFish bridge runner failed: " + " | ".join(stderr or [f"exit={completed.returncode}"]))
    summary: dict[str, Any] | None = None
    for line in (completed.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "final_summary":
            summary = {k: v for k, v in event.items() if k not in {"event", "ts"}}
    return summary or {}


def _load_summary_from_state(run_dir: Path) -> dict[str, Any]:
    state_path = run_dir / "mirofish_bridge_state.json"
    if not state_path.exists():
        return {}
    state = _read_json(state_path)
    summary = state.get("final_summary")
    return summary if isinstance(summary, dict) else {}


def _entity_rows(summary: Mapping[str, Any], state: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_ontology = state.get("ontology")
    ontology: Mapping[str, Any] = raw_ontology if isinstance(raw_ontology, dict) else {}
    raw_entity_types = ontology.get("entity_types")
    entity_types: Mapping[str, Any] = raw_entity_types if isinstance(raw_entity_types, dict) else {}
    rows = [
        {
            "name": str(name),
            "type": "entity_type",
            "rationale": f"MiroFish graph/ontology prepared {count} extracted entities for this type.",
        }
        for name, count in sorted(entity_types.items())
    ]
    if rows:
        return rows
    graph_nodes = summary.get("graph_nodes") or summary.get("graph_node_count") or 0
    return [
        {
            "name": "MiroFish seeded graph",
            "type": "graph_summary",
            "rationale": f"Bridge runner completed with {graph_nodes} graph nodes; detailed entity names were not exported.",
        }
    ]


def _persona_rows(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_sample = summary.get("sample_action")
    sample: Mapping[str, Any] = raw_sample if isinstance(raw_sample, dict) else {}
    name = str(sample.get("agent_name") or "MiroFish simulation participant")
    action_type = str(sample.get("action_type") or "simulation")
    return [
        {
            "name": name,
            "role": "simulation_participant",
            "stance": f"Observed in bridge action type {action_type}.",
        }
    ]


def _simulation_events(summary: Mapping[str, Any]) -> list[str]:
    raw_sample = summary.get("sample_action")
    sample: Mapping[str, Any] = raw_sample if isinstance(raw_sample, dict) else {}
    content = str(sample.get("content") or "").strip()
    if content:
        return [content]
    actions = summary.get("actions", 0)
    return [f"MiroFish bridge recorded {actions} meaningful simulation actions."]


def _warnings(manifest: Mapping[str, Any], summary: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    for key in ("warnings", "data_gaps"):
        values = manifest.get(key)
        if isinstance(values, list):
            warnings.extend(str(value) for value in values if value)
    if isinstance(summary.get("warnings"), list):
        warnings.extend(str(value) for value in summary["warnings"] if value)
    if summary.get("graph_memory_update_enabled") is False:
        warnings.append("graph_memory_update_enabled=false; native action-memory success is not claimed.")
    if summary.get("report_cjk", 0):
        warnings.append(f"report_cjk={summary.get('report_cjk')}; Korean report may contain CJK template leakage.")
    if not summary.get("actions"):
        warnings.append("No meaningful simulation action count was exported by the bridge summary.")
    if not summary.get("graph_nodes") and not summary.get("graph_node_count"):
        warnings.append("No graph node count was exported by the bridge summary.")
    return list(dict.fromkeys(warnings))


def _report_body(run_dir: Path, summary: Mapping[str, Any]) -> tuple[Path, str]:
    report_path = run_dir / "mirofish_simulation_report.md"
    body = "\n".join(
        [
            "# MiroFish Aquarium Simulation Report",
            "",
            f"- simulation_id: {summary.get('simulation_id', 'unknown')}",
            f"- report_id: {summary.get('report_id', 'unknown')}",
            f"- actions: {summary.get('actions', 0)}",
            "",
            str(summary.get("chat_preview") or "Bridge runner completed; detailed report body was not exported through the summary."),
            "",
        ]
    )
    report_path.write_text(body, encoding="utf-8")
    return report_path, body


def build_mirofish_result(manifest: Mapping[str, Any], summary: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    state = _read_json(run_dir / "mirofish_bridge_state.json") if (run_dir / "mirofish_bridge_state.json").exists() else {}
    report_path, report_body = _report_body(run_dir, summary)
    return {
        "provider": "mirofish_cli",
        "ontology": {"entities": _entity_rows(summary, state), "relations": []},
        "personas": _persona_rows(summary),
        "simulation": {
            "mode": "single",
            "universes": [
                {
                    "name": "single_seeded_universe",
                    "variation": "BettaFish report seeded single MiroFish run",
                    "dominant_signal": str(summary.get("chat_preview") or "single seeded simulation completed")[:240],
                    "events": _simulation_events(summary),
                }
            ],
        },
        "simulation_report": {"path": str(report_path), "body": report_body},
        "warnings": _warnings(manifest, summary),
        "artifacts": {
            "bridge_state": str(run_dir / "mirofish_bridge_state.json"),
            "bridge_events": str(run_dir / "mirofish_bridge_events.jsonl"),
            "source_report": str(manifest.get("final_report_path")),
        },
    }


def run_from_env(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    mode = _required_env(env, "AQUARIUM_MODE")
    if mode != "single":
        raise RunnerContractError("AQUARIUM_MODE=multiverse is not supported by the seeded Aquarium runner yet; no unseeded multiverse fallback was run.")
    run_dir = Path(_required_env(env, "AQUARIUM_RUN_DIR")).expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_aquarium_manifest(_required_env(env, "AQUARIUM_HANDOFF_MANIFEST"))
    locale = env.get("AQUARIUM_LOCALE") or manifest.get("locale")
    if locale not in LOCALES:
        raise RunnerContractError("AQUARIUM_LOCALE must be one of ko, zh, en")
    command = build_bridge_command(env, manifest, run_dir)
    summary = run_bridge_command(command, cwd=Path(__file__).resolve().parents[1])
    if not summary:
        summary = _load_summary_from_state(run_dir)
    if not summary.get("success"):
        raise RunnerContractError("MiroFish bridge did not produce a successful final_summary.")
    result = build_mirofish_result(manifest, summary, run_dir)
    output = run_dir / "mirofish_result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"event": "mirofish_aquarium_result", "path": str(output), "provider": "mirofish_cli"}, ensure_ascii=False), flush=True)
    return result


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    # argv is accepted for testability; this runner is intentionally env-contract based.
    _ = argv
    try:
        run_from_env(env)
        return 0
    except RunnerContractError as exc:
        print(json.dumps({"event": "fatal", "success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"event": "fatal", "success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
