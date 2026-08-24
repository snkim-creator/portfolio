"""LLM 클라이언트. OpenAI 호환 API(KIMI/Moonshot, OpenAI 등)를 사용한다.

DB 비밀번호/접속 문자열은 절대 전달하지 않는다. (PRD 섹션 30)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 호출 실패."""


class LLMClient:
    def __init__(self, ai_cfg: Dict[str, Any]):
        api_key_env = ai_cfg.get("api_key_env", "AI_API_KEY")
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise LLMError(f"환경변수 {api_key_env} 에 API Key 가 없습니다.")

        self.model = ai_cfg.get("model", "moonshot-v1-8k")
        self.temperature = float(ai_cfg.get("temperature", 0.3))
        self._client = OpenAI(
            api_key=api_key,
            base_url=ai_cfg.get("base_url") or None,
            timeout=float(ai_cfg.get("timeout_seconds", 60)),
            max_retries=2,
        )

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """system/user 프롬프트로 텍스트를 생성한다. 실패 시 LLMError."""
        logger.info("AI API Request (model=%s)", self.model)
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:  # noqa: BLE001 - SDK 예외 종류 다양
            logger.error("AI API Error: %s", exc)
            raise LLMError(str(exc)) from exc

        content = resp.choices[0].message.content if resp.choices else None
        if not content:
            raise LLMError("AI 응답이 비어 있습니다.")
        return content.strip()
