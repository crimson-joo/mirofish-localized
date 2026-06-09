#!/usr/bin/env python3
"""Live Report Agent locale E2E.

Runs the same simulation Q&A as ko/en/zh users and verifies the visible answer language.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:5001'
SIMULATION_ID = sys.argv[2] if len(sys.argv) > 2 else 'sim_5bb6a79b6fc5'
GRAPH_ID = sys.argv[3] if len(sys.argv) > 3 else 'local_mirofish_725a524065d34168'

PROMPTS = {
    'ko': '이번 시뮬레이션에서 기록된 에이전트 행동을 근거로, 주요 이해관계자의 입장을 5줄 이내 한국어로 요약해줘.',
    'en': 'Using the recorded agent actions from this simulation, summarize the key stakeholder positions in English in no more than five lines.',
    'zh': '请根据本次模拟中记录的智能体行为，用中文在五行以内总结主要利益相关方的立场。',
}

HAN = re.compile(r'[\u4e00-\u9fff]')
HANGUL = re.compile(r'[\uac00-\ud7a3]')
LATIN_WORD = re.compile(r'\b(the|and|agent|stakeholder|stablecoin|policy|bank|regulator|summary|simulation)\b', re.I)


def post(locale: str) -> dict:
    payload = {
        'simulation_id': SIMULATION_ID,
        'graph_id': GRAPH_ID,
        'message': PROMPTS[locale],
        'chat_history': [],
        'locale': locale,
    }
    req = urllib.request.Request(
        BASE + '/api/report/chat',
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={'Content-Type': 'application/json', 'Accept-Language': locale, 'X-Locale': locale},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            out = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode('utf-8', errors='ignore')) from exc
    if out.get('success') is False:
        raise RuntimeError(json.dumps(out, ensure_ascii=False)[:2000])
    return out['data']


def validate(locale: str, text: str) -> None:
    han_count = len(HAN.findall(text))
    hangul_count = len(HANGUL.findall(text))
    if locale == 'ko':
        if hangul_count < 15:
            raise AssertionError(f'ko answer has too little Korean: {text}')
        if han_count > 5:
            raise AssertionError(f'ko answer leaked too much Chinese: han={han_count} text={text}')
    elif locale == 'en':
        if not LATIN_WORD.search(text):
            raise AssertionError(f'en answer does not look English: {text}')
        if han_count > 5 or hangul_count > 5:
            raise AssertionError(f'en answer leaked CJK text: han={han_count} hangul={hangul_count} text={text}')
    elif locale == 'zh':
        if han_count < 15:
            raise AssertionError(f'zh answer has too little Chinese: {text}')
        if hangul_count > 5:
            raise AssertionError(f'zh answer leaked Korean: hangul={hangul_count} text={text}')


def main() -> int:
    results = []
    for locale in ['ko', 'en', 'zh']:
        data = post(locale)
        response = data.get('response', '').strip()
        validate(locale, response)
        result = {
            'locale': locale,
            'chars': len(response),
            'tool_calls': [call.get('name') for call in data.get('tool_calls', [])],
            'preview': response[:220],
        }
        print('PASS', json.dumps(result, ensure_ascii=False))
        results.append(result)
    print('SUMMARY', json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
