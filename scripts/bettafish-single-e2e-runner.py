#!/usr/bin/env python3
"""Resume-safe BettaFish → MiroFish single-simulation E2E runner.

This runner turns a gated BettaFish Markdown report into a MiroFish seed document,
builds a graph, runs one short simulation, generates a report, asks Report Agent,
and writes one machine-readable summary.  It is intentionally stateful so a long
Graphiti/report run can be resumed after a SIGTERM/timeout without losing ids.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REQUIREMENT = (
    "BettaFish가 생성한 한국어 조사 보고서를 현실 시드(seed) 문서로 사용한다. "
    "사용자가 제시한 주제를 기준으로 확정 사실, 시나리오 가정, 데이터 부족 신호, "
    "주요 이해관계자 반응, 리스크를 구분해 단일 시뮬레이션을 수행한다. "
    "최종 결과는 예측 확정이나 투자 권유가 아니라 시나리오 분석으로 작성한다. 한국어로 출력한다."
)


class RunnerError(RuntimeError):
    pass


class BridgeState:
    """Small JSON state file with attempt reconciliation for resume runs."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = self._load()
        self.attempt_id = f"attempt_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{os.getpid()}"
        self.finished = False
        self._mark_previous_running_attempts_interrupted()
        self.update(
            current_attempt_id=self.attempt_id,
            updated_at=utc_now(),
        )
        attempts = self.data.setdefault("attempts", [])
        attempts.append(
            {
                "attempt_id": self.attempt_id,
                "pid": os.getpid(),
                "started_at": utc_now(),
                "status": "running",
            }
        )
        self.save()
        atexit.register(self._atexit)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "attempts": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RunnerError(f"State file is not valid JSON: {self.path}") from exc

    def _mark_previous_running_attempts_interrupted(self) -> None:
        for attempt in self.data.get("attempts", []):
            if attempt.get("status") == "running":
                attempt["status"] = "interrupted_or_unknown"
                attempt.setdefault("ended_at", utc_now())
                attempt.setdefault("note", "A later resume run started before this attempt was marked completed.")

    def _current_attempt(self) -> dict[str, Any] | None:
        for attempt in reversed(self.data.get("attempts", [])):
            if attempt.get("attempt_id") == self.attempt_id:
                return attempt
        return None

    def _atexit(self) -> None:
        if not self.finished:
            self.mark_attempt("interrupted_or_failed", note="Process exited without normal completion marker.")

    def update(self, **kwargs: Any) -> None:
        self.data.update(kwargs)
        self.data["updated_at"] = utc_now()
        self.save()

    def set_stage(self, stage: str) -> None:
        self.update(stage=stage)

    def mark_attempt(self, status: str, **extra: Any) -> None:
        attempt = self._current_attempt()
        if attempt is not None:
            attempt.update(extra)
            attempt["status"] = status
            attempt["ended_at"] = utc_now()
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


class Logger:
    def __init__(self, log_file: Path | None):
        self.log_file = log_file
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        record = {"ts": utc_now(), "event": event, **(payload or {})}
        line = json.dumps(record, ensure_ascii=False)
        print(line, flush=True)
        if self.log_file:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def audit_text(label: str, text: str) -> dict[str, int]:
    return {
        f"{label}_chars": len(text),
        f"{label}_hangul": sum("가" <= c <= "힣" for c in text),
        f"{label}_cjk": sum("\u4e00" <= c <= "\u9fff" for c in text),
    }


def request_json(base_url: str, method: str, path: str, locale: str, payload: dict[str, Any] | None = None, timeout: int = 300) -> dict[str, Any]:
    body_payload = None
    if payload is not None:
        body_payload = dict(payload)
        body_payload.setdefault("locale", locale)
    data = json.dumps(body_payload).encode("utf-8") if body_payload is not None else None
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept-Language": locale, "X-Locale": locale},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            out = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        raise RunnerError(f"{method} {path} HTTP {exc.code}: {raw[:2000]}") from exc
    if out.get("success") is False:
        raise RunnerError(f"{method} {path} failed: {json.dumps(out, ensure_ascii=False)[:2000]}")
    return out


def upload_report(base_url: str, locale: str, report_path: Path, project_name: str, requirement: str, additional_context: str, timeout: int) -> dict[str, Any]:
    boundary = "----HermesBettaMiroBoundary7MA4YWxk"

    def field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
        ).encode("utf-8")

    file_bytes = report_path.read_bytes()
    body = b"".join(
        [
            field("project_name", project_name),
            field("simulation_requirement", requirement),
            field("additional_context", additional_context),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{report_path.name}\"\r\n"
                "Content-Type: text/markdown\r\n\r\n"
            ).encode("utf-8"),
            file_bytes,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/graph/ontology/generate",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept-Language": locale, "X-Locale": locale},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        raise RunnerError(f"POST /api/graph/ontology/generate HTTP {exc.code}: {raw[:2000]}") from exc
    if out.get("success") is False:
        raise RunnerError(json.dumps(out, ensure_ascii=False)[:2000])
    return out["data"]


def wait_task(base_url: str, locale: str, task_id: str, timeout_s: int, log: Logger, event: str) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        task = request_json(base_url, "GET", f"/api/graph/task/{task_id}", locale, timeout=60)["data"]
        last = task
        log.emit(event, {k: task.get(k) for k in ["task_id", "status", "progress", "message", "result", "error"]})
        if task.get("status") == "completed":
            return task
        if task.get("status") == "failed":
            raise RunnerError(f"Task failed: {json.dumps(task, ensure_ascii=False)[:2000]}")
        time.sleep(10)
    raise TimeoutError(f"Task timed out after {timeout_s}s: {json.dumps(last, ensure_ascii=False)[:2000]}")


def wait_prepare(base_url: str, locale: str, simulation_id: str, task_id: str | None, timeout_s: int, log: Logger) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        payload: dict[str, Any] = {"simulation_id": simulation_id}
        if task_id:
            payload["task_id"] = task_id
        data = request_json(base_url, "POST", "/api/simulation/prepare/status", locale, payload, timeout=60)["data"]
        last = data
        log.emit("prepare_status", {k: data.get(k) for k in ["status", "progress", "message", "already_prepared"]})
        if data.get("status") in {"ready", "completed"} or data.get("already_prepared"):
            return data
        if data.get("status") == "failed":
            raise RunnerError(f"Prepare failed: {json.dumps(data, ensure_ascii=False)[:2000]}")
        time.sleep(5)
    raise TimeoutError(f"Prepare timed out after {timeout_s}s: {json.dumps(last, ensure_ascii=False)[:2000]}")


def wait_actions(base_url: str, locale: str, simulation_id: str, timeout_s: int, log: Logger) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        data = request_json(base_url, "GET", f"/api/simulation/{simulation_id}/run-status/detail", locale, timeout=60)["data"]
        last = data
        log.emit("run_status", {k: data.get(k) for k in ["runner_status", "current_round", "total_rounds", "total_actions_count"]})
        if data.get("all_actions") or data.get("total_actions_count", 0) > 0:
            return data
        if data.get("runner_status") == "failed":
            raise RunnerError(f"Simulation failed: {json.dumps(data, ensure_ascii=False)[:2000]}")
        time.sleep(5)
    raise TimeoutError(f"Actions timed out after {timeout_s}s: {json.dumps(last, ensure_ascii=False)[:2000]}")


def wait_report(base_url: str, locale: str, simulation_id: str, task_id: str | None, timeout_s: int, log: Logger) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        payload: dict[str, Any] = {"simulation_id": simulation_id}
        if task_id:
            payload["task_id"] = task_id
        data = request_json(base_url, "POST", "/api/report/generate/status", locale, payload, timeout=60)["data"]
        last = data
        log.emit("report_status", {k: data.get(k) for k in ["status", "progress", "message", "report_id", "error"]})
        if data.get("status") == "completed":
            return data
        if data.get("status") == "failed":
            raise RunnerError(f"Report failed: {json.dumps(data, ensure_ascii=False)[:2000]}")
        time.sleep(10)
    raise TimeoutError(f"Report timed out after {timeout_s}s: {json.dumps(last, ensure_ascii=False)[:2000]}")


def meaningful_actions(status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in status.get("all_actions", [])
        if "event_type" not in row and row.get("action_type") != "DO_NOTHING"
    ]


def run(args: argparse.Namespace) -> dict[str, Any]:
    report_path = Path(args.bettafish_report).expanduser().resolve()
    if not report_path.exists():
        raise RunnerError(f"BettaFish report not found: {report_path}")

    state = BridgeState(Path(args.state_path).expanduser().resolve())
    log = Logger(Path(args.log_file).expanduser().resolve() if args.log_file else None)
    base = args.base_url.rstrip("/")
    requirement = args.requirement or DEFAULT_REQUIREMENT
    context = args.additional_context or (
        "Source is a BettaFish localized final report. Treat uncertain IPO/valuation/theme information as "
        "scenario assumptions unless explicitly official. Preserve data-shortage and caution signals."
    )

    try:
        state.set_stage("health")
        health = request_json(base, "GET", "/health", args.locale, timeout=20)
        log.emit("health", health)

        if not state.data.get("project_id"):
            state.set_stage("upload_ontology")
            uploaded = upload_report(
                base,
                args.locale,
                report_path,
                args.project_name or f"BettaFish seed - {args.topic}",
                requirement,
                context,
                args.upload_timeout,
            )
            state.update(
                project_id=uploaded.get("project_id"),
                project_name=uploaded.get("project_name"),
                ontology=uploaded.get("ontology"),
                total_text_length=uploaded.get("total_text_length"),
            )
            log.emit("uploaded", {k: uploaded.get(k) for k in ["project_id", "project_name", "total_text_length"]})

        project_id = state.data["project_id"]

        if not state.data.get("graph_id"):
            if not state.data.get("graph_task_id"):
                state.set_stage("graph_build_start")
                started = request_json(
                    base,
                    "POST",
                    "/api/graph/build",
                    args.locale,
                    {
                        "project_id": project_id,
                        "graph_name": args.graph_name or f"BettaFish seed graph - {args.topic}",
                        "chunk_size": args.chunk_size,
                        "chunk_overlap": args.chunk_overlap,
                        "force": args.force_graph,
                    },
                    timeout=60,
                )["data"]
                state.update(graph_task_id=started.get("task_id"), graph_build_started=started)
            state.set_stage("graph_build_wait")
            graph_task = wait_task(base, args.locale, state.data["graph_task_id"], args.graph_timeout, log, "graph_status")
            result = graph_task.get("result") or {}
            graph_id = result.get("graph_id") or state.data.get("graph_build_started", {}).get("graph_id")
            if not graph_id:
                raise RunnerError(f"Graph task completed without graph_id: {json.dumps(graph_task, ensure_ascii=False)[:2000]}")
            state.update(
                graph_id=graph_id,
                graph_task_status=graph_task.get("status"),
                graph_chunk_count=result.get("chunk_count"),
                graph_node_count=result.get("node_count"),
                graph_edge_count=result.get("edge_count"),
            )

        graph_id = state.data["graph_id"]
        graph_data = request_json(base, "GET", f"/api/graph/data/{graph_id}", args.locale, timeout=120)["data"]
        nodes = graph_data.get("nodes") or []
        edges = graph_data.get("edges") or []
        state.update(graph_node_count=len(nodes), graph_edge_count=len(edges))

        if not state.data.get("simulation_id"):
            state.set_stage("simulation_create")
            created = request_json(
                base,
                "POST",
                "/api/simulation/create",
                args.locale,
                {"project_id": project_id, "graph_id": graph_id, "enable_twitter": True, "enable_reddit": True},
                timeout=60,
            )["data"]
            state.update(simulation_id=created["simulation_id"])
            log.emit("simulation_created", {"simulation_id": created["simulation_id"], "project_id": project_id, "graph_id": graph_id})

        simulation_id = state.data["simulation_id"]

        state.set_stage("simulation_prepare")
        prepared_start = request_json(
            base,
            "POST",
            "/api/simulation/prepare",
            args.locale,
            {
                "simulation_id": simulation_id,
                "use_llm_for_profiles": args.use_llm_for_profiles,
                "parallel_profile_count": args.profile_count,
                "force_regenerate": args.force_prepare,
            },
            timeout=60,
        )["data"]
        state.update(prepare_task_id=prepared_start.get("task_id"))
        prepared = wait_prepare(base, args.locale, simulation_id, prepared_start.get("task_id"), args.prepare_timeout, log)
        state.update(prepare_status=prepared.get("status"), prepare_info=prepared.get("prepare_info"))

        state.set_stage("simulation_start")
        started = request_json(
            base,
            "POST",
            "/api/simulation/start",
            args.locale,
            {
                "simulation_id": simulation_id,
                "platform": "parallel",
                "max_rounds": args.max_rounds,
                "enable_graph_memory_update": args.enable_graph_memory_update,
                "force": args.force_start,
            },
            timeout=60,
        )["data"]
        state.update(graph_memory_update_enabled=bool(started.get("graph_memory_update_enabled")))

        state.set_stage("simulation_wait_actions")
        run_status = wait_actions(base, args.locale, simulation_id, args.actions_timeout, log)
        try:
            request_json(base, "POST", "/api/simulation/stop", args.locale, {"simulation_id": simulation_id}, timeout=60)
        except Exception as exc:  # best effort: report generation can proceed from recorded actions
            log.emit("stop_warning", {"error": str(exc)})
        final_status = request_json(base, "GET", f"/api/simulation/{simulation_id}/run-status/detail", args.locale, timeout=60)["data"]
        actions = meaningful_actions(final_status)
        state.update(action_count=len(actions), runner_status=run_status.get("runner_status"))
        if not actions:
            raise RunnerError("Simulation produced no meaningful actions.")

        state.set_stage("report_generate")
        if not state.data.get("report_id") or args.force_report:
            generated = request_json(
                base,
                "POST",
                "/api/report/generate",
                args.locale,
                {"simulation_id": simulation_id, "force_regenerate": args.force_report},
                timeout=60,
            )["data"]
            state.update(report_task_id=generated.get("task_id"), report_id=generated.get("report_id"))
        report_status = wait_report(base, args.locale, simulation_id, state.data.get("report_task_id"), args.report_timeout, log)
        report_id = report_status.get("report_id") or state.data.get("report_id")
        state.update(report_id=report_id, report_status=report_status.get("status"))
        report_payload = request_json(base, "GET", f"/api/report/{report_id}", args.locale, timeout=60)["data"]
        markdown = report_payload.get("markdown_content") or report_payload.get("content") or ""

        state.set_stage("report_agent_chat")
        chat = request_json(
            base,
            "POST",
            "/api/report/chat",
            args.locale,
            {"simulation_id": simulation_id, "message": args.chat_question},
            timeout=args.chat_timeout,
        )["data"]
        answer = chat.get("response") or ""

        summary = {
            "success": True,
            "source_report": str(report_path),
            "state_path": str(state.path),
            "project_id": project_id,
            "graph_id": graph_id,
            "simulation_id": simulation_id,
            "report_id": report_id,
            "graph_nodes": len(nodes),
            "graph_edges": len(edges),
            "graph_chunk_count": state.data.get("graph_chunk_count"),
            "prepare_status": state.data.get("prepare_status"),
            "runner_status": run_status.get("runner_status"),
            "current_round": run_status.get("current_round"),
            "total_rounds": run_status.get("total_rounds"),
            "actions": len(actions),
            "graph_memory_update_enabled": state.data.get("graph_memory_update_enabled"),
            **audit_text("report", markdown),
            **audit_text("chat", answer),
            "chat_preview": answer[:900],
            "sample_action": {
                "platform": actions[0].get("platform"),
                "agent_name": actions[0].get("agent_name"),
                "action_type": actions[0].get("action_type"),
                "round": actions[0].get("round") or actions[0].get("round_num"),
                "content": (actions[0].get("action_args") or {}).get("content") or actions[0].get("content") or actions[0].get("text"),
            },
            "attempts": state.data.get("attempts", []),
        }
        state.update(stage="completed", final_summary=summary)
        state.mark_attempt("completed")
        state.finished = True
        log.emit("final_summary", summary)
        return summary
    except Exception as exc:
        state.update(stage="failed", last_error=str(exc))
        state.mark_attempt("failed", error=str(exc))
        state.finished = True
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run/resume BettaFish report → MiroFish single simulation E2E.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument("--bettafish-report", required=True, help="Path to gated BettaFish final Markdown report")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--state-path", default=".hermes/runs/bettafish-mirofish-single-e2e/state.json")
    parser.add_argument("--log-file", default=".hermes/runs/bettafish-mirofish-single-e2e/events.jsonl")
    parser.add_argument("--locale", default="ko")
    parser.add_argument("--project-name")
    parser.add_argument("--graph-name")
    parser.add_argument("--requirement")
    parser.add_argument("--additional-context")
    parser.add_argument("--chat-question", default="이 단일 시뮬레이션 기준으로 핵심 테마를 확정 사실, 시나리오 가정, 리스크로 나눠 한국어로 7줄 이내 요약해줘.")
    parser.add_argument("--chunk-size", type=int, default=3000)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    parser.add_argument("--profile-count", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument("--upload-timeout", type=int, default=600)
    parser.add_argument("--graph-timeout", type=int, default=1800)
    parser.add_argument("--prepare-timeout", type=int, default=1800)
    parser.add_argument("--actions-timeout", type=int, default=900)
    parser.add_argument("--report-timeout", type=int, default=2400)
    parser.add_argument("--chat-timeout", type=int, default=600)
    parser.add_argument("--force-graph", action="store_true")
    parser.add_argument("--force-prepare", action="store_true")
    parser.add_argument("--force-start", action="store_true")
    parser.add_argument("--force-report", action="store_true")
    parser.add_argument("--use-llm-for-profiles", action="store_true")
    parser.add_argument("--disable-graph-memory-update", dest="enable_graph_memory_update", action="store_false")
    parser.set_defaults(enable_graph_memory_update=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run(args)
        return 0
    except Exception as exc:
        print(json.dumps({"ts": utc_now(), "event": "fatal", "success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
