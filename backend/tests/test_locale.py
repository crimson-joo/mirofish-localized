from typing import cast, Any

from app import create_app
from app.services.report_agent import ReportAgent
from app.utils.locale import get_language_instruction, get_locale, set_locale


class CapturingLLM:
    def __init__(self):
        self.messages = None

    def chat(self, messages, temperature=0.5, **kwargs):
        self.messages = messages
        return '한국어 답변입니다.'


def test_locale_defaults_to_korean_without_header():
    app = create_app()
    with app.test_request_context('/api/report/chat', method='POST', json={}):
        assert get_locale() == 'ko'
        assert '한국어' in get_language_instruction()


def test_locale_parses_accept_language_primary_tag():
    app = create_app()
    with app.test_request_context('/api/report/chat', method='POST', headers={'Accept-Language': 'ko-KR,en;q=0.9'}):
        assert get_locale() == 'ko'


def test_body_locale_overrides_header_for_background_capture():
    app = create_app()
    with app.test_request_context('/api/report/chat', method='POST', json={'locale': 'en'}, headers={'Accept-Language': 'zh'}):
        assert get_locale() == 'en'
        assert 'English' in get_language_instruction()


def test_set_locale_normalizes_thread_locale():
    set_locale('ko-KR')
    assert get_locale() == 'ko'


def test_report_agent_chat_system_prompt_for_ko_forces_korean_output():
    set_locale('ko')
    llm = CapturingLLM()
    agent = ReportAgent(
        graph_id='graph_test',
        simulation_id='sim_test',
        simulation_requirement='스테이블코인 정책 시뮬레이션',
        llm_client=cast(Any, llm),
        zep_tools=cast(Any, object()),
    )

    result = agent.chat('에이전트 행동을 요약해줘')

    assert result['response'] == '한국어 답변입니다.'
    assert llm.messages is not None
    system_prompt = llm.messages[0]['content']
    assert '모든 자연어 텍스트는 반드시 한국어' in system_prompt
    assert 'translate/summarize' in system_prompt.lower() or '번역' in system_prompt
    assert '你是一个简洁高效的模拟预测助手' not in system_prompt
