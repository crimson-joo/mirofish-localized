import json
import os
import tempfile
import unittest
from unittest.mock import patch


class RuntimeCycleHardeningTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        from app.config import Config
        from app.models.project import ProjectManager
        from app.services.multiverse_manager import MultiverseManager
        from app.services.simulation_manager import SimulationManager
        from app.services.simulation_runner import SimulationRunner
        from app.services.report_agent import ReportManager

        Config.UPLOAD_FOLDER = self.tmpdir.name
        Config.OASIS_SIMULATION_DATA_DIR = os.path.join(self.tmpdir.name, "simulations")
        Config.LOCAL_GRAPH_STORAGE_DIR = os.path.join(self.tmpdir.name, "local_graphs")
        ProjectManager.PROJECTS_DIR = os.path.join(self.tmpdir.name, "projects")
        SimulationManager.SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR
        SimulationRunner.RUN_STATE_DIR = Config.OASIS_SIMULATION_DATA_DIR
        ReportManager.REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, "reports")
        MultiverseManager.MULTIVERSE_DATA_DIR = os.path.join(self.tmpdir.name, "multiverses")
        SimulationRunner._run_states.clear()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_graphiti_duplicate_edge_warning_is_recorded_without_marking_ingest_failed(self):
        from app.services.graphiti_provider import GraphitiGraphBuilder
        from app.services.graphiti_projection_cache import _load_graph

        builder = GraphitiGraphBuilder()
        graph_id = builder.create_graph("warning smoke")

        with patch("app.services.graphiti_provider._json_request") as request:
            request.return_value = {
                "success": True,
                "message": "processed native=1 repaired=0 failed=0; EdgeDuplicate validation warning: duplicate edge ignored",
            }

            episodes = builder.add_text_batches(graph_id, ["Alice influences Bob."])

        graph = _load_graph(graph_id)
        status = graph["graphiti_status"]

        self.assertEqual(len(episodes), 1)
        self.assertEqual(status["native_ingest_state"], "pass")
        self.assertEqual(status["native_warning_state"], "warning")
        self.assertEqual(status["warnings"][-1]["category"], "duplicate_edge")
        self.assertIn("duplicate edge", status["warnings"][-1]["message"].lower())


    def test_graphiti_duplicate_edge_warning_is_deduped_across_batches(self):
        from app.services.graphiti_provider import GraphitiGraphBuilder
        from app.services.graphiti_projection_cache import _load_graph

        builder = GraphitiGraphBuilder()
        graph_id = builder.create_graph("warning dedupe")

        with patch("app.services.graphiti_provider._json_request") as request:
            request.return_value = {
                "success": True,
                "message": "processed native=1 repaired=0 failed=0; EdgeDuplicate validation warning: duplicate edge ignored",
            }

            builder.add_text_batches(graph_id, ["Alice influences Bob.", "Alice influences Bob again."])

        status = _load_graph(graph_id)["graphiti_status"]
        duplicate_warnings = [w for w in status["warnings"] if w["category"] == "duplicate_edge"]
        self.assertEqual(len(duplicate_warnings), 1)
        self.assertEqual(status["native_ingest_state"], "pass")

    def test_action_log_graph_memory_failure_fails_closed(self):
        from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner

        class FailingUpdater:
            def add_activity_from_dict(self, data, platform):
                raise RuntimeError("native action ingest failed")

        state = SimulationRunState(simulation_id="sim_graph_fail", runner_status=RunnerStatus.RUNNING)
        sim_dir = os.path.join(SimulationRunner.RUN_STATE_DIR, state.simulation_id, "twitter")
        os.makedirs(sim_dir, exist_ok=True)
        log_path = os.path.join(sim_dir, "actions.jsonl")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "round": 1,
                "agent_id": 1,
                "agent_name": "CanaryAgent",
                "action_type": "CREATE_POST",
                "action_args": {"content": "CANARY_ACTION_MEMORY_FAIL_CLOSED"},
            }) + "\n")

        SimulationRunner._graph_memory_enabled[state.simulation_id] = True
        with patch("app.services.simulation_runner.get_graph_memory_manager") as manager_factory:
            manager_factory.return_value.get_updater.return_value = FailingUpdater()
            with self.assertRaises(RuntimeError):
                SimulationRunner._read_action_log(log_path, 0, state, "twitter")

        self.assertEqual(state.runner_status, RunnerStatus.FAILED)
        self.assertIn("Graph memory action ingest failed", state.error)

    def test_invalid_persisted_runner_status_fails_closed(self):
        from app.services.simulation_runner import RunnerStatus, SimulationRunner

        sim_id = "sim_invalid_status"
        sim_dir = os.path.join(SimulationRunner.RUN_STATE_DIR, sim_id)
        os.makedirs(sim_dir, exist_ok=True)
        with open(os.path.join(sim_dir, "run_state.json"), "w", encoding="utf-8") as f:
            json.dump({"simulation_id": sim_id, "runner_status": "weird_future_status"}, f)

        state = SimulationRunner.get_run_state(sim_id)

        assert state is not None
        self.assertEqual(state.runner_status, RunnerStatus.FAILED)
        self.assertIn("Invalid persisted runner_status", state.error)

    def test_orphan_running_without_durable_completion_does_not_hold_running_slot(self):
        from app.services.simulation_runner import RunnerStatus, SimulationRunner

        sim_id = "sim_orphan_running"
        sim_dir = os.path.join(SimulationRunner.RUN_STATE_DIR, sim_id)
        os.makedirs(sim_dir, exist_ok=True)
        with open(os.path.join(sim_dir, "run_state.json"), "w", encoding="utf-8") as f:
            json.dump({"simulation_id": sim_id, "runner_status": "running", "process_pid": 99999999}, f)

        state = SimulationRunner.get_run_state(sim_id)

        assert state is not None
        self.assertEqual(state.runner_status, RunnerStatus.FAILED)
        self.assertIn("Orphaned persisted runner state", state.error)

    def test_multiverse_refresh_promotes_stopped_command_wait_run_when_actions_prove_completion(self):
        from app.services.multiverse_manager import MultiverseManager
        from app.services.simulation_manager import SimulationManager, SimulationStatus
        from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_demo",
            graph_id="graph_demo",
            base_requirement="장시간 OASIS 완료 상태 정규화",
            universe_count=1,
            rounds=24,
        )
        child = experiment.children[0]

        sim_manager = SimulationManager()
        state = sim_manager.get_simulation(child.simulation_id)
        assert state is not None
        state.status = SimulationStatus.STOPPED
        sim_manager._save_simulation_state(state)

        run_state = SimulationRunState(
            simulation_id=child.simulation_id,
            runner_status=RunnerStatus.STOPPED,
            total_rounds=24,
            current_round=24,
            twitter_current_round=24,
            reddit_current_round=24,
        )
        SimulationRunner._save_run_state(run_state)

        sim_dir = os.path.join(SimulationRunner.RUN_STATE_DIR, child.simulation_id)
        for platform in ["twitter", "reddit"]:
            platform_dir = os.path.join(sim_dir, platform)
            os.makedirs(platform_dir, exist_ok=True)
            with open(os.path.join(platform_dir, "actions.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps({"event_type": "round_end", "round": 24, "simulated_hours": 12}) + "\n")
                f.write(json.dumps({"agent_id": 1, "agent_name": "Agent", "action_type": "CREATE_POST", "round": 24}) + "\n")
                f.write(json.dumps({"event_type": "simulation_end", "total_rounds": 24, "total_actions": 1}) + "\n")

        refreshed = manager.refresh_status(experiment.multiverse_id)
        updated_state = SimulationManager().get_simulation(child.simulation_id)
        updated_run_state = SimulationRunner.get_run_state(child.simulation_id)
        assert updated_state is not None
        assert updated_run_state is not None

        self.assertEqual(refreshed["status"], "completed")
        self.assertEqual(refreshed["children"][0]["status"], "completed")
        self.assertEqual(updated_state.status, SimulationStatus.COMPLETED)
        self.assertEqual(updated_run_state.runner_status, RunnerStatus.COMPLETED)
        self.assertEqual(updated_run_state.twitter_actions_count, 1)
        self.assertEqual(updated_run_state.reddit_actions_count, 1)
    def test_report_manager_recovers_completed_status_from_durable_full_report(self):
        from app.services.report_agent import Report, ReportManager, ReportStatus

        report = Report(
            report_id="report_resume_demo",
            simulation_id="sim_demo",
            graph_id="graph_demo",
            simulation_requirement="resume smoke",
            status=ReportStatus.GENERATING,
            created_at="2026-06-19T00:00:00",
        )
        ReportManager.save_report(report)
        ReportManager.update_progress(
            report.report_id,
            "generating",
            95,
            "watcher timed out after assembling report",
            completed_sections=["section 1"],
        )
        report_folder = ReportManager._get_report_folder(report.report_id)
        with open(os.path.join(report_folder, "full_report.md"), "w", encoding="utf-8") as f:
            f.write("# 완료 리포트\n\n본문")

        recovered = ReportManager.reconcile_report_completion(report.report_id)

        assert recovered is not None
        self.assertEqual(recovered.status, ReportStatus.COMPLETED)
        self.assertIn("완료 리포트", recovered.markdown_content)
        self.assertEqual(ReportManager.get_report(report.report_id).status, ReportStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
