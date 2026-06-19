import unittest


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages_seen = []

    def chat(self, messages, **kwargs):
        self.messages_seen.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return "Final Answer: fallback"


class _CountingZepTools:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def quick_search(self, graph_id, query, limit=10):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Graphiti native search failed")
        from app.services.zep_tools import SearchResult
        return SearchResult(
            facts=["CANARY_ACTION_MEMORY_GRAPHITI_EVIDENCE_619 koi market panic signal"],
            edges=[],
            nodes=[],
            query=query,
            total_count=1,
        )

    def insight_forge(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("not expected")

    def panorama_search(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("not expected")

    def interview_agents(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("not expected")


class ReportAgentProtocolTest(unittest.TestCase):
    def test_section_conflict_retries_do_not_execute_tool_and_fail_closed(self):
        from app.services.report_agent import ReportAgent, ReportAgentProtocolError, ReportOutline, ReportSection

        conflict = '<tool_call>{"name":"quick_search","parameters":{"query":"canary"}}</tool_call>\nFinal Answer: bad'
        zep = _CountingZepTools()
        llm = _FakeLLM([conflict, conflict, conflict])
        agent = ReportAgent(
            graph_id="graph_demo",
            simulation_id="sim_demo",
            simulation_requirement="protocol canary",
            llm_client=llm,  # type: ignore[arg-type]
            zep_tools=zep,  # type: ignore[arg-type]
        )

        with self.assertRaises(ReportAgentProtocolError):
            agent._generate_section_react(
                ReportSection(title="증거"),
                ReportOutline(title="보고서", summary="요약", sections=[]),
                [],
            )

        self.assertEqual(zep.calls, 0)
        flattened_messages = [message for call in llm.messages_seen for message in call]
        self.assertFalse(any(message.get("role") == "assistant" and "Final Answer: bad" in message.get("content", "") for message in flattened_messages))

    def test_chat_conflict_does_not_execute_tool(self):
        from app.services.report_agent import ReportAgent, ReportAgentProtocolError

        conflict = '<tool_call>{"name":"quick_search","parameters":{"query":"canary"}}</tool_call>\nFinal Answer: bad'
        zep = _CountingZepTools()
        agent = ReportAgent(
            graph_id="graph_demo",
            simulation_id="sim_demo",
            simulation_requirement="protocol canary",
            llm_client=_FakeLLM([conflict]),  # type: ignore[arg-type]
            zep_tools=zep,  # type: ignore[arg-type]
        )

        with self.assertRaises(ReportAgentProtocolError):
            agent.chat("canary?")

        self.assertEqual(zep.calls, 0)

    def test_quick_search_tool_returns_action_memory_evidence(self):
        from app.services.report_agent import ReportAgent

        agent = ReportAgent(
            graph_id="graph_demo",
            simulation_id="sim_demo",
            simulation_requirement="evidence canary",
            llm_client=_FakeLLM([]),  # type: ignore[arg-type]
            zep_tools=_CountingZepTools(),  # type: ignore[arg-type]
        )

        text = agent._execute_tool("quick_search", {"query": "CANARY_ACTION_MEMORY_GRAPHITI_EVIDENCE_619", "limit": 5})

        self.assertIn("CANARY_ACTION_MEMORY_GRAPHITI_EVIDENCE_619", text)
        self.assertNotIn("工具执行失败", text)

    def test_quick_search_failure_is_not_returned_as_evidence(self):
        from app.services.report_agent import ReportAgent

        agent = ReportAgent(
            graph_id="graph_demo",
            simulation_id="sim_demo",
            simulation_requirement="evidence canary",
            llm_client=_FakeLLM([]),  # type: ignore[arg-type]
            zep_tools=_CountingZepTools(fail=True),  # type: ignore[arg-type]
        )

        with self.assertRaises(RuntimeError):
            agent._execute_tool("quick_search", {"query": "CANARY_ACTION_MEMORY_GRAPHITI_EVIDENCE_619", "limit": 5})


if __name__ == "__main__":
    unittest.main()
