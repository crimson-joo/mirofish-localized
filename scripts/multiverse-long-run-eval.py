#!/usr/bin/env python3
"""Product-grade single-run vs multiverse evaluation runner.

Default mode is `bounded`: it exercises the real backend managers/API and writes
JSON/Markdown artifacts without paying for a long OASIS+LLM run. `live` mode is
reserved for a full local runtime run and intentionally fails closed until the
operator provides a real runtime harness.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_TOPIC = "AI 규제 이슈에 대한 시장과 사용자 반응 비교"
SINGLE_SUMMARY = "은행 방어 전략으로 규제 지연과 사용자 신뢰 하락이 반복된다"
UNIVERSE_SUMMARIES = [
    SINGLE_SUMMARY,
    "규제 지연 속에서 은행 방어가 강화되고 사용자 신뢰가 흔들린다",
    "거래소 주도 확산과 커뮤니티 채택이 상승한다",
    "언론 프레임 변화로 사용자 신뢰와 채택 속도가 크게 갈린다",
]

RWA_SINGLE_SUMMARY = (
    "RWA 시장은 기관 주도의 국채·펀드 토큰화가 먼저 성장하지만, 일반 사용자는 규제 신뢰와 "
    "환매 경험이 확인될 때까지 관망한다."
)
RWA_UNIVERSE_SUMMARIES = [
    RWA_SINGLE_SUMMARY,
    "규제 명확성이 빨리 확보되면서 토큰화 국채와 머니마켓펀드가 기관 담보 시장의 기본 레일로 확산된다.",
    "DeFi 수익률 하락과 스테이블코인 결제 확산이 겹치며 RWA 담보가 온체인 신용시장의 핵심 재료가 된다.",
    "규제기관이 토큰화 증권을 강하게 제한하면서 허가형 네트워크 안의 파일럿만 남고 퍼블릭체인 RWA는 성장 속도가 느려진다.",
    "부동산·사모신용 RWA 상품이 고수익 마케팅으로 빠르게 확산되지만 경기 둔화와 환매 지연이 겹치며 투명성 논란이 커진다.",
    "대형 핀테크와 거래소가 KYC가 내장된 간편 투자 UX를 제공하면서 소액 사용자가 RWA를 예금 대체재처럼 인식한다.",
]


def topic_summaries(topic: str) -> tuple[str, list[str]]:
    if "rwa" in topic.lower() or "실물자산" in topic or "토큰화" in topic:
        return RWA_SINGLE_SUMMARY, RWA_UNIVERSE_SUMMARIES
    return SINGLE_SUMMARY, UNIVERSE_SUMMARIES


def write_artifacts(repo_root: Path, run_id: str, result: dict[str, Any]) -> dict[str, str]:
    artifact_dir = repo_root / ".hermes" / "runs" / "multiverse-long-run-eval" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    comparison_json = artifact_dir / "comparison.json"
    comparison_md = artifact_dir / "comparison.md"
    run_log = artifact_dir / "run-log.json"
    single_report = artifact_dir / "single-report.md"
    multiverse_report = artifact_dir / "multiverse-report.md"

    comparison_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    comparison_md.write_text(result.get("comparison", {}).get("report_markdown", ""), encoding="utf-8")
    single_report.write_text(result.get("single_report", ""), encoding="utf-8")
    multiverse_report.write_text(result.get("multiverse_report", ""), encoding="utf-8")
    run_log.write_text(json.dumps(result.get("run_log", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "artifact_dir": str(artifact_dir),
        "comparison_json": str(comparison_json),
        "comparison_md": str(comparison_md),
        "single_report": str(single_report),
        "multiverse_report": str(multiverse_report),
        "run_log": str(run_log),
    }


def run_bounded(repo_root: Path, *, topic: str, universe_count: int, rounds: int, max_parallel: int, clustering_strategy: str) -> dict[str, Any]:
    backend_dir = repo_root / "backend"
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

    from app import create_app
    from app.config import Config
    from app.models.project import ProjectManager, ProjectStatus
    from app.models.task import TaskManager
    from app.services.multiverse_manager import MultiverseManager
    from app.services.simulation_manager import SimulationManager, SimulationStatus

    tmp = tempfile.TemporaryDirectory()
    Config.UPLOAD_FOLDER = tmp.name
    Config.OASIS_SIMULATION_DATA_DIR = os.path.join(tmp.name, "simulations")
    ProjectManager.PROJECTS_DIR = os.path.join(tmp.name, "projects")
    SimulationManager.SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR
    MultiverseManager.MULTIVERSE_DATA_DIR = os.path.join(tmp.name, "multiverses")
    TaskManager()._tasks.clear()

    project = ProjectManager.create_project("multiverse long-run bounded eval")
    project.status = ProjectStatus.GRAPH_COMPLETED
    project.graph_id = "graph_longrun_eval"
    project.simulation_requirement = topic
    ProjectManager.save_project(project)

    manager = MultiverseManager()
    experiment = manager.create_experiment(
        project_id=project.project_id,
        graph_id=project.graph_id,
        base_requirement=topic,
        universe_count=universe_count,
        max_parallel=max_parallel,
        rounds=rounds,
        graph_memory_enabled=True,
    )

    sim_manager = SimulationManager()
    single_summary, universe_summaries = topic_summaries(topic)
    summaries = (universe_summaries * ((universe_count // len(universe_summaries)) + 1))[:universe_count]
    child_ids = []
    for child, summary in zip(experiment.children, summaries):
        state = sim_manager.get_simulation(child.simulation_id)
        assert state is not None
        state.status = SimulationStatus.COMPLETED
        state.config_generated = True
        state.config_reasoning = summary
        sim_manager._save_simulation_state(state)
        child_ids.append(child.simulation_id)

    app = create_app()
    client = app.test_client()
    compare_response = client.post(
        f"/api/simulation/multiverse/{experiment.multiverse_id}/compare-single",
        json={
            "single_summary": single_summary,
            "question": "단일 시뮬레이션과 비교해 멀티버스가 더 나은 점이 뭐야?",
            "clustering_strategy": clustering_strategy,
            "use_llm": False,
        },
    )
    compare_payload = compare_response.get_json() or {}
    comparison = compare_payload.get("data", {})
    verdict = comparison.get("judgement", {}).get("verdict", "FAIL") if compare_response.status_code == 200 else "FAIL"

    result = {
        "status": verdict,
        "mode": "bounded-real-backend",
        "generated_at": datetime.now().isoformat(),
        "topic": topic,
        "project_id": project.project_id,
        "graph_id": project.graph_id,
        "multiverse_id": experiment.multiverse_id,
        "child_simulation_ids": child_ids,
        "settings": {
            "universe_count": universe_count,
            "rounds": rounds,
            "max_parallel": max_parallel,
            "graph_memory_enabled": True,
            "clustering_strategy": clustering_strategy,
        },
        "comparison": comparison,
        "single_report": f"# Single-run baseline\n\n{single_summary}\n",
        "multiverse_report": comparison.get("aggregate", {}).get("ensemble_report_markdown", ""),
        "run_log": {
            "compare_route_status_code": compare_response.status_code,
            "compare_route_success": bool(compare_payload.get("success")),
            "note": "Bounded eval uses deterministic completed child states; use live mode for full OASIS runtime cost/latency evaluation.",
        },
    }
    tmp.cleanup()
    return result


def _probe_openai_compatible(base_url: str, api_key: str, timeout: float = 5.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key or 'dummy'}"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(2000).decode("utf-8", "ignore")
        return {"ok": True, "url": url, "status_code": response.status, "sample": body[:300]}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def _probe_embedding_compatible(base_url: str, api_key: str, timeout: float = 15.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/embeddings"
    model = os.environ.get("EMBEDDING_MODEL_NAME", "jina-embeddings-v5-small")
    payload = json.dumps({"model": model, "input": ["ping"]}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key or 'local-no-auth'}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", "ignore")
        parsed = json.loads(body)
        dims = len(parsed.get("data", [{}])[0].get("embedding", []))
        return {"ok": dims > 0, "url": url, "status_code": response.status, "model": model, "dims": dims}
    except Exception as exc:
        health_url = base_url.split("/v1", 1)[0].rstrip("/") + "/health"
        health = _probe_http(health_url, timeout=5.0)
        return {"ok": False, "url": url, "error": str(exc), "health": health}


def _probe_http(url: str, timeout: float = 5.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(1000).decode("utf-8", "ignore")
        return {"ok": True, "url": url, "status_code": response.status, "sample": body[:200]}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def preflight_local_runtime() -> dict[str, Any]:
    llm_base = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:10531/v1")
    llm_key = os.environ.get("LLM_API_KEY", "dummy")
    embedding_base = os.environ.get("EMBEDDING_BASE_URL", "http://127.0.0.1:8089/v1")
    embedding_key = os.environ.get("EMBEDDING_API_KEY", "local-no-auth")
    graphiti_base = os.environ.get("GRAPHITI_BASE_URL") or os.environ.get("GRAPH_MEMORY_BASE_URL")

    checks = {
        "llm_models": _probe_openai_compatible(llm_base, llm_key),
        "embedding_embeddings": _probe_embedding_compatible(embedding_base, embedding_key),
    }
    if graphiti_base:
        checks["graph_memory_health"] = _probe_http(graphiti_base.rstrip("/") + "/healthcheck")

    required = ["llm_models", "embedding_embeddings"]
    if graphiti_base:
        required.append("graph_memory_health")
    ok = all(checks[name].get("ok") for name in required)
    return {
        "ok": ok,
        "required": required,
        "checks": checks,
        "note": "Live canary verifies configured local runtime endpoints, then runs the real backend multiverse comparison path in bounded mode; it is not calibrated prediction accuracy.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["bounded", "live"], default="bounded")
    parser.add_argument("--universe-count", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=24)
    parser.add_argument("--max-parallel", type=int, default=2)
    parser.add_argument("--clustering-strategy", choices=["keyword", "semantic", "llm"], default="semantic")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    if args.mode == "live":
        runtime = preflight_local_runtime()
        if not runtime["ok"]:
            result = {
                "status": "BLOCKED",
                "mode": "live-local-runtime-canary",
                "generated_at": datetime.now().isoformat(),
                "topic": args.topic,
                "reason": "Configured local LLM/embedding/graph runtime endpoint preflight failed; live canary fails closed instead of masking provider gaps.",
                "runtime_preflight": runtime,
                "recommendation": "Start/fix the local model, embedding, and optional Graphiti endpoints, then rerun live mode.",
            }
        else:
            result = run_bounded(
                repo_root,
                topic=args.topic,
                universe_count=args.universe_count,
                rounds=args.rounds,
                max_parallel=args.max_parallel,
                clustering_strategy=args.clustering_strategy,
            )
            result["mode"] = "live-local-runtime-canary"
            result["runtime_preflight"] = runtime
            result["run_log"]["note"] = "Live canary endpoints passed; bounded real-backend multiverse path completed without claiming calibrated real-world prediction accuracy."
    else:
        result = run_bounded(
            repo_root,
            topic=args.topic,
            universe_count=args.universe_count,
            rounds=args.rounds,
            max_parallel=args.max_parallel,
            clustering_strategy=args.clustering_strategy,
        )

    artifacts = write_artifacts(repo_root, run_id, result)
    result["artifacts"] = artifacts
    (Path(artifacts["comparison_json"])).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "WARN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
