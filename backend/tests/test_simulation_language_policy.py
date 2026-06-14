import csv
import json
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from simulation_language_policy import (  # noqa: E402
    enforce_prompt_language,
    get_language_policy,
    localized_profile_path,
)


def test_language_policy_defaults_to_korean_and_blocks_chinese_leakage():
    policy = get_language_policy({'locale': 'ko'})

    assert policy['locale'] == 'ko'
    assert '한국어' in policy['instruction']
    assert '중국어 문장' in policy['instruction']


def test_interview_prompt_is_wrapped_with_selected_language_policy():
    prompt = enforce_prompt_language('이 에이전트의 입장을 요약해줘', {'locale': 'ko'})

    assert prompt.startswith('Selected simulation language: 한국어 (ko).')
    assert '중국어 문장으로 토론' in prompt
    assert '이 에이전트의 입장을 요약해줘' in prompt


def test_twitter_profiles_are_prefixed_with_korean_policy(tmp_path):
    src = tmp_path / 'twitter_profiles.csv'
    with src.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['user_id', 'user_name', 'name', 'bio', 'persona'])
        writer.writeheader()
        writer.writerow({
            'user_id': '0',
            'user_name': 'agent0',
            'name': 'Agent Zero',
            'bio': '关注市场政策。',
            'persona': '该用户经常用中文讨论政策。',
        })

    localized = localized_profile_path(str(src), {'locale': 'ko'}, 'twitter')

    with open(localized, encoding='utf-8', newline='') as f:
        row = next(csv.DictReader(f))
    assert row['bio'].startswith('[언어 정책:')
    assert row['persona'].startswith('[언어 정책:')
    assert '중국어 문장으로 응답하지 않는다' in row['persona']


def test_reddit_profiles_are_prefixed_with_english_policy(tmp_path):
    src = tmp_path / 'reddit_profiles.json'
    src.write_text(json.dumps([
        {'username': 'agent0', 'bio': '한국어 설명', 'persona': '중국어로 토론하는 계정'}
    ], ensure_ascii=False), encoding='utf-8')

    localized = localized_profile_path(str(src), {'locale': 'en'}, 'reddit')

    data = json.loads(Path(localized).read_text(encoding='utf-8'))
    assert data[0]['bio'].startswith('[Language policy:')
    assert 'write posts, comments, discussions' in data[0]['persona']
