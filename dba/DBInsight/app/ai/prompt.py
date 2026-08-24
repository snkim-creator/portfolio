"""AI 프롬프트 구성. (PRD 섹션 21~22)

AI 는 이미 가공된 Finding 을 '설명/요약' 하는 계층으로만 사용한다.
Raw SQL 대신 정규화된 digest_text 를 전달한다. (PRD 섹션 30)
"""

from __future__ import annotations

import json
from typing import Any, Dict

_SYSTEM_BASE = """You are a senior MySQL/MariaDB DBA assistant.

Your role is to analyze already-processed database findings and create a concise
daily database health report.

Do not assume causality without sufficient evidence.

Clearly distinguish:
- observed facts
- possible causes
- recommended checks

Do not recommend destructive actions (no SQL execution, no parameter change,
no process kill, no restart, no index creation, no data change).

Prioritize issues that require DBA attention.

If metrics appear normal, explicitly state that no immediate action is required.

You are given structured JSON. Do NOT invent metrics or numbers that are not
present in the input. Output must be GitHub-flavored Markdown."""

_LANG = {
    "ko": "Write the report in Korean (한국어).",
    "en": "Write the report in English.",
}


def build_system_prompt(language: str = "ko") -> str:
    return _SYSTEM_BASE + "\n\n" + _LANG.get(language, _LANG["ko"])


def build_user_prompt(payload: Dict[str, Any]) -> str:
    """Finding payload(JSON) + 작성 지시를 담은 user 프롬프트."""
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    instructions = """다음 JSON 은 한 DB 서버의 분석 결과(이미 Rule Engine 이 판정 완료)다.
리포트의 수치/상태/개수/각 섹션은 이미 코드가 결정적으로 작성했다.
너는 그 위에 덧붙일 **간결한 DBA 코멘트(3~6문장)** 만 작성한다. 리포트 전체를 다시 쓰지 마라.

작성 원칙:
- summary/analysis_window 의 상태·개수·기간을 바꾸거나 반박하지 마라 (이미 확정된 사실).
- 이 데이터에 있는 수치만 사용하고 없는 값은 지어내지 마라. baseline_status=INSUFFICIENT_DATA 는 '기준선 부족'.
- `top_sql`·regression 수치는 분석 기간(basis=period) 동안의 값이다 (누적값 아님).
- 다음 3가지를 명확히 구분해 서술: 관찰된 사실 / 가능한 원인(단정 금지) / 권장 확인.
- category=sql_regression, lifecycle=NEW 를 우선 언급. 확정적 Root Cause 표현 금지.
- findings 가 비어 있으면 "즉시 조치가 필요한 이상 징후는 없다"고 짧게 밝혀라.

머리말/제목 없이 코멘트 본문만 출력하라 (섹션 제목은 코드가 붙인다)."""
    return f"{instructions}\n\n```json\n{payload_json}\n```"
