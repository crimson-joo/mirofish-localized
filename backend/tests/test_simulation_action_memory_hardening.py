import json
import os
import tempfile
import unittest
from unittest.mock import patch


class _FailingGraphMemoryUpdater:
    def add_activity_from_dict(self, data, platform):
        raise RuntimeError("native action ingest timed out")


class _FailingGraphMemoryManager:
    def get_updater(self, simulation_id):
        return _FailingGraphMemoryUpdater()


class SimulationActionMemoryHardeningTest(unittest.TestCase):
    def test_action_ingest_failure_marks_warning_without_failing_simulation_log_reader(self):
        from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner

        state = SimulationRunState(simulation_id="sim_action_warning", runner_status=RunnerStatus.RUNNING)
        row = {
            "round": 1,
            "timestamp": "2026-06-29T00:00:00",
            "agent_id": 7,
            "agent_name": "CanaryAgent",
            "action_type": "CREATE_POST",
            "action_args": {"content": "CANARY_ACTION_MEMORY_TIMEOUT_SHOULD_NOT_FAIL_RUN"},
            "success": True,
        }
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            path = handle.name

        SimulationRunner._graph_memory_enabled[state.simulation_id] = True
        try:
            with patch(
                "app.services.simulation_runner.get_graph_memory_manager",
                return_value=_FailingGraphMemoryManager(),
            ):
                new_position = SimulationRunner._read_action_log(path, 0, state, "twitter")

            self.assertGreater(new_position, 0)
            self.assertEqual(state.runner_status, RunnerStatus.RUNNING)
            self.assertEqual(state.twitter_actions_count, 1)
            self.assertEqual(len(state.graph_memory_warnings), 1)
            self.assertEqual(state.graph_memory_warnings[0]["state"], "failed")
            self.assertIn("native action ingest timed out", state.graph_memory_warnings[0]["error"])
            self.assertIn("graph_memory_warnings", state.to_dict())
        finally:
            SimulationRunner._graph_memory_enabled.pop(state.simulation_id, None)
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
