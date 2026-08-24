"""AI 호출 실패 시에도 결정적 리포트가 완성되는지 검증 (네트워크 미사용).

P5 이후: AI 실패 시 'fallback 리포트'가 아니라 완전한 결정적 본문에서 AI 코멘트만 생략된다.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai import client as client_mod  # noqa: E402
from app.ai import reporter  # noqa: E402
from app.config import load_config  # noqa: E402
from app.storage import sqlite  # noqa: E402


def test_fallback(monkeypatch_broken=True):
    cfg = load_config()

    # AI 클라이언트가 무조건 실패하도록 강제
    class BrokenClient:
        def __init__(self, ai_cfg):
            pass

        def generate(self, system, user):
            raise client_mod.LLMError("강제 실패 (테스트)")

    reporter.LLMClient = BrokenClient  # type: ignore[assignment]

    # 실제 리포트를 덮어쓰지 않도록 임시 출력 디렉터리 사용
    tmp = tempfile.mkdtemp()
    cfg["report"]["output_directory"] = tmp

    store = sqlite.init_db(cfg["storage"]["db_path"])
    result = reporter.generate(store, cfg)
    store.close()

    assert result is not None, "결과 없음"
    assert result["used_ai"] is False, "AI 실패인데 used_ai=True"
    with open(result["report_path"], encoding="utf-8") as f:
        content = f.read()
    # 결정적 본문은 정상 생성되어야 하고, AI 코멘트만 생략된다.
    assert "Overall Status" in content, "결정적 본문 누락"
    assert "AI 코멘트 생략" in content, "AI 실패 표기 누락"
    assert "## AI 코멘트" not in content, "AI 실패인데 코멘트 섹션이 있음"
    print("report path:", result["report_path"])
    print("used_ai:", result["used_ai"])
    print("FALLBACK OK")


if __name__ == "__main__":
    test_fallback()
