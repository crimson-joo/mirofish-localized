import json
import os
import threading
from flask import request, has_request_context

_thread_local = threading.local()

_locales_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'locales')
DEFAULT_LOCALE = os.environ.get('MIROFISH_DEFAULT_LOCALE', 'ko')

# Load language registry
with open(os.path.join(_locales_dir, 'languages.json'), 'r', encoding='utf-8') as f:
    _languages = json.load(f)

# Load translation files
_translations = {}
for filename in os.listdir(_locales_dir):
    if filename.endswith('.json') and filename != 'languages.json':
        locale_name = filename[:-5]
        with open(os.path.join(_locales_dir, filename), 'r', encoding='utf-8') as f:
            _translations[locale_name] = json.load(f)


def _normalize_locale(locale: str | None) -> str:
    """Normalize locale strings such as ko-KR or 'ko,en;q=0.9'."""
    if not locale:
        return DEFAULT_LOCALE if DEFAULT_LOCALE in _translations else 'ko'

    for part in str(locale).split(','):
        code = part.split(';', 1)[0].strip().replace('_', '-').lower()
        if not code:
            continue
        primary = code.split('-', 1)[0]
        if code in _translations:
            return code
        if primary in _translations:
            return primary

    return DEFAULT_LOCALE if DEFAULT_LOCALE in _translations else 'ko'


def set_locale(locale: str):
    """Set locale for current thread. Call at the start of background threads."""
    _thread_local.locale = _normalize_locale(locale)


def get_locale() -> str:
    if has_request_context():
        # Explicit body locale wins when present; otherwise use frontend Accept-Language / X-Locale.
        body_locale = None
        if request.content_type and 'json' in request.content_type:
            payload = request.get_json(silent=True) or {}
            body_locale = payload.get('locale') or payload.get('language')
        raw = body_locale or request.headers.get('X-Locale') or request.headers.get('Accept-Language')
        return _normalize_locale(raw)
    return getattr(_thread_local, 'locale', _normalize_locale(None))


def t(key: str, **kwargs) -> str:
    locale = get_locale()
    messages = _translations.get(locale, _translations.get(DEFAULT_LOCALE, _translations.get('ko', {})))

    value = messages
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if value is None:
        value = _translations.get(DEFAULT_LOCALE, _translations.get('ko', {}))
        for part in key.split('.'):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break

    if value is None:
        return key

    if kwargs:
        for k, v in kwargs.items():
            value = value.replace(f'{{{k}}}', str(v))

    return value


def get_language_label() -> str:
    locale = get_locale()
    return _languages.get(locale, _languages.get(DEFAULT_LOCALE, {})).get('label', locale)


def get_language_instruction() -> str:
    locale = get_locale()
    lang_config = _languages.get(locale, _languages.get(DEFAULT_LOCALE, _languages.get('ko', {})))
    base = lang_config.get('llmInstruction', '한국어로 답변하세요.')
    if locale == 'ko':
        return (
            f"{base}\n"
            "중요: 사용자에게 보이는 모든 자연어 텍스트는 반드시 한국어로 작성하세요. "
            "검색 결과, 기존 보고서, Graphiti 기록, 시뮬레이션 행동, 내부 템플릿이 중국어/영어여도 "
            "최종 응답과 생성되는 bio/persona/content/reasoning/summary/report 문장은 한국어로 번역·요약하세요. "
            "JSON 필드명, enum 값, ID, 코드값만 원래 형식을 유지하세요."
        )
    if locale == 'en':
        return (
            f"{base}\n"
            "Important: all user-visible natural-language text must be in English. "
            "Translate or summarize Chinese/Korean internal context into English; keep JSON field names, enum values, IDs, and code values unchanged."
        )
    if locale == 'zh':
        return f"{base}\n重要：所有面向用户的自然语言文本必须使用中文。JSON字段名、枚举值、ID和代码值保持不变。"
    return (
        f"{base}\n"
        f"Important: all user-visible natural-language text must use {get_language_label()}. "
        "Translate or summarize internal context into the selected language; keep JSON field names, enum values, IDs, and code values unchanged."
    )
