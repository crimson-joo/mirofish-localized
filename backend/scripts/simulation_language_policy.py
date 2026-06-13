"""Language-policy helpers for OASIS simulation subprocesses.

The Flask app already carries locale through request/thread-local context for
prepare/report tasks. OASIS simulation runners are separate Python processes,
so they need a deterministic policy copied into their config/profile inputs.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Dict

SUPPORTED_POLICIES = {
    "ko": {
        "label": "한국어",
        "instruction": (
            "사용자에게 보이는 모든 자연어 출력은 한국어를 기본으로 작성하세요. "
            "필요한 경우 고유명사나 짧은 기술 용어만 영어로 유지할 수 있지만, "
            "중국어 문장으로 토론/게시/댓글/인터뷰/요약을 생성하지 마세요."
        ),
        "profile_prefix": (
            "[언어 정책: 이 시뮬레이션의 게시글, 댓글, 토론, 인터뷰 답변, 중간 사고 요약은 한국어를 기본으로 작성한다. "
            "고유명사·코드값은 유지할 수 있으나 중국어 문장으로 응답하지 않는다.] "
        ),
    },
    "en": {
        "label": "English",
        "instruction": (
            "Write all user-visible natural-language simulation output in English. "
            "Translate or summarize Korean/Chinese context into English; keep proper nouns and code values unchanged."
        ),
        "profile_prefix": (
            "[Language policy: write posts, comments, discussions, interview answers, and summaries in English. "
            "Do not respond in Korean or Chinese except for proper nouns or quoted source snippets.] "
        ),
    },
    "zh": {
        "label": "中文",
        "instruction": "所有面向用户的自然语言模拟输出都应使用中文；字段名、枚举值、ID和代码值保持不变。",
        "profile_prefix": "[语言策略：帖子、评论、讨论、采访回答和摘要都使用中文；字段名、枚举值和ID保持不变。] ",
    },
}


def normalize_locale(raw: str | None) -> str:
    if not raw:
        return "ko"
    first = str(raw).split(",", 1)[0].split(";", 1)[0].strip().replace("_", "-").lower()
    primary = first.split("-", 1)[0]
    return primary if primary in SUPPORTED_POLICIES else "ko"


def get_language_policy(config: Dict[str, Any] | None = None) -> Dict[str, str]:
    config = config or {}
    locale = normalize_locale(
        config.get("locale")
        or config.get("simulation_locale")
        or os.environ.get("MIROFISH_SIMULATION_LOCALE")
        or os.environ.get("MIROFISH_LOCALE")
    )
    policy = dict(SUPPORTED_POLICIES[locale])
    policy["locale"] = locale
    config_instruction = config.get("language_instruction")
    if isinstance(config_instruction, str) and config_instruction.strip():
        policy["instruction"] = f"{config_instruction.strip()}\n{policy['instruction']}"
    return policy


def language_policy_block(config: Dict[str, Any] | None = None) -> str:
    policy = get_language_policy(config)
    return f"Selected simulation language: {policy['label']} ({policy['locale']}). {policy['instruction']}"


def _prefix_text(value: Any, prefix: str) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    if value.startswith(prefix) or "언어 정책:" in value[:120] or "Language policy:" in value[:120] or "语言策略：" in value[:120]:
        return value
    return prefix + value


def localized_profile_path(profile_path: str, config: Dict[str, Any], platform: str) -> str:
    """Return a temp profile path with language policy embedded in bio/persona.

    OASIS builds agent prompts from profile files. Prefixing profile natural-language
    fields is a stable way to make the selected locale survive inside the third-party
    simulation loop without changing JSON field names/enums.
    """
    policy = get_language_policy(config)
    prefix = policy["profile_prefix"]
    src = Path(profile_path)
    if not src.exists():
        return profile_path

    out_dir = src.parent / "localized_profiles"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{policy['locale']}_{src.name}"

    if platform == "twitter" or src.suffix.lower() == ".csv":
        with src.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            fieldnames = list(rows[0].keys()) if rows else []
        for row in rows:
            for field in ("bio", "persona"):
                if field in row:
                    row[field] = _prefix_text(row[field], prefix)
        with dst.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return str(dst)

    with src.open("r", encoding="utf-8") as f:
        data = json.load(f)
    records = data if isinstance(data, list) else data.get("users") or data.get("profiles") or []
    if isinstance(records, list):
        for row in records:
            if isinstance(row, dict):
                for field in ("bio", "persona", "description"):
                    if field in row:
                        row[field] = _prefix_text(row[field], prefix)
    with dst.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(dst)


def enforce_prompt_language(prompt: str, config: Dict[str, Any] | None = None) -> str:
    block = language_policy_block(config)
    if block in prompt:
        return prompt
    return f"{block}\n\n{prompt}"
