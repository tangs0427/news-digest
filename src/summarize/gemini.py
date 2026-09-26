"""Gemini 로 '오늘의 흐름'과 기사별 한 줄 요약을 만든다.

카테고리마다 한 번씩 부르고, 마지막에 흐름용으로 한 번 더 부른다(하루 6회쯤).
60건을 한 요청에 담으면 API 가 503 을 돌려주기 때문이다.

실패해도 다이제스트 발송은 막지 않는다 — 요약만 빠진 채로 나간다.
"""

from __future__ import annotations

import json
import logging
import time

import requests

from ..config import DeliveryConfig
from ..models import Digest
from .prompt import (
    OVERVIEW_SCHEMA,
    SUMMARY_SCHEMA,
    apply_overview,
    apply_summaries,
    build_overview_prompt,
    build_summary_prompt,
    flatten,
)

log = logging.getLogger(__name__)

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = 180

# 무료 티어는 "high demand" 503 을 자주 낸다. 하루 한 번 도는 작업이라
# 한 번 튕겼다고 요약을 포기하면 그날치가 통째로 빈다.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
BACKOFF_SECONDS = (5, 15)

# 재시도를 세게 돌리면 이번엔 429(분당 한도)를 맞는다. 실측으로 확인한 함정이라
# 모델당 시도와 시도할 모델 수를 모두 좁게 잡고, 호출 사이에 간격을 둔다.
MAX_MODELS_TRIED = 3
GAP_BETWEEN_CALLS = 2

# 무료 티어는 모델당 하루 20회. 정상 동작에 필요한 건 카테고리 5 + 흐름 1 = 6회다.
# 아침에 최대 4회차를 돌리므로 회차당 상한을 낮게 잡아야 하루치가 남는다.
MAX_TOTAL_CALLS = 12

# 전체 요약에 쓸 시간 예산. 넘기면 지금까지 만든 것만 들고 발송으로 넘어간다.
# GitHub Actions 작업 전체가 15분 제한이라 여기서 다 쓰면 안 된다.
TIME_BUDGET_SECONDS = 240

# 설정한 모델이 은퇴했거나(404) 계속 과부하면 차례로 시도할 대안.
# 구글이 모델을 자주 갈아치우므로 한 이름에만 기대지 않는다.
FALLBACK_MODELS = (
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
)

# Gemini 3.x 는 추론이 기본으로 켜져 있는데, 이 작업에는 도움이 안 되면서
# 용량만 잡아먹어 503 을 유발한다(실측 확인). 꺼서 보낸다.
THINKING_OFF = {"thinkingBudget": 0}


def summarize(digest: Digest, config: DeliveryConfig) -> bool:
    """성공하면 True. digest 는 제자리에서 수정된다."""
    if not config.gemini_api_key:
        log.warning("GEMINI_API_KEY 가 없어 요약을 건너뜁니다.")
        return False

    categories = digest.non_empty()
    if not categories:
        return False

    state = _ModelState(config)
    applied = 0
    skipped = 0

    for index, category in enumerate(categories):
        if state.expired():
            skipped += 1
            continue
        if index:
            time.sleep(GAP_BETWEEN_CALLS)
        result = _generate(
            build_summary_prompt(category, digest), SUMMARY_SCHEMA, state
        )
        if result is None:
            log.warning("[%s] 요약 실패", category.label)
            continue
        count = apply_summaries(category, result)
        applied += count
        log.info("[%s] 요약 %d/%d건", category.label, count, len(category.articles))

    if skipped:
        log.warning("시간 예산(%d초) 초과로 %d개 분야를 건너뜁니다.", TIME_BUDGET_SECONDS, skipped)

    lines = 0
    if not state.expired():
        time.sleep(GAP_BETWEEN_CALLS)
        overview_result = _generate(build_overview_prompt(digest), OVERVIEW_SCHEMA, state)
        lines = apply_overview(digest, overview_result) if overview_result else 0

    total = len(flatten(digest))
    log.info("요약 완료: 오늘의 흐름 %d줄, 기사 요약 %d/%d건", lines, applied, total)

    log.info("Gemini 호출 %d회 사용", state.calls)

    if applied == 0 and lines == 0:
        digest.summary_error = (
            "오늘 Gemini 무료 한도를 모두 써서 요약을 만들지 못했습니다."
            if state.daily_exhausted
            else "Gemini 호출에 실패해 요약을 만들지 못했습니다."
        )
        return False
    if applied < total:
        reason = " (무료 한도 소진)" if state.daily_exhausted else ""
        digest.summary_error = (
            f"일부 기사({total - applied}건)는 요약을 만들지 못했습니다{reason}."
        )
    return True


class _ModelState:
    """한 번 성공한 모델을 기억해 이후 호출에서 먼저 쓴다."""

    def __init__(self, config: DeliveryConfig) -> None:
        self.config = config
        self.preferred = config.gemini_model
        # 이 실행에서 못 쓴다고 판명된 모델(은퇴 등)은 다시 시도하지 않는다.
        self.dead: set[str] = set()
        self.deadline = time.monotonic() + TIME_BUDGET_SECONDS
        self.calls = 0
        self.daily_exhausted = False

    def expired(self) -> bool:
        return time.monotonic() >= self.deadline or self.calls >= MAX_TOTAL_CALLS

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def order(self) -> list[str]:
        names = [self.preferred] + [m for m in FALLBACK_MODELS if m != self.preferred]
        alive = [name for name in names if name not in self.dead]
        return alive[:MAX_MODELS_TRIED]


def _generate(prompt: str, schema: dict, state: _ModelState) -> dict | None:
    """모델을 차례로, 각 모델은 백오프하며 재시도. 전부 실패하면 None."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "thinkingConfig": THINKING_OFF,
        },
    }

    for model in state.order():
        if state.expired():
            return None
        payload = _try_model(model, body, state)
        if payload is None:
            continue
        try:
            return _extract_json(payload)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            log.warning("Gemini %s 응답 해석 실패: %s", model, exc)
            continue
    return None


def _try_model(model: str, body: dict, state: _ModelState) -> dict | None:
    for attempt in range(len(BACKOFF_SECONDS) + 1):
        if state.expired():
            return None
        state.calls += 1
        try:
            response = requests.post(
                ENDPOINT.format(model=model),
                params={"key": state.config.gemini_api_key},
                json=body,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            log.warning("Gemini 연결 실패 (%s): %s", model, exc)
            return None

        if response.ok:
            if model != state.preferred:
                log.warning("'%s' 대신 '%s' 로 요약합니다.", state.preferred, model)
                state.preferred = model
            return response.json()

        status = response.status_code
        message = _error_message(response)

        # thinkingConfig 를 모르는 모델이면 그것만 빼고 한 번 더.
        if status == 400 and "thinking" in message.lower():
            body["generationConfig"].pop("thinkingConfig", None)
            log.info("Gemini %s: thinkingConfig 미지원, 빼고 재시도", model)
            continue

        # 무료 티어는 모델당 하루 20회다. 일일 한도는 기다려도 오늘 안에는
        # 풀리지 않으므로 재시도하지 말고 다른 모델로 넘어간다(한도가 모델별이다).
        if status == 429 and _is_daily_quota(response):
            log.warning("Gemini %s: 오늘 무료 한도(20회) 소진. 다른 모델로 넘어갑니다.", model)
            state.dead.add(model)
            state.daily_exhausted = True
            return None

        if status not in RETRYABLE_STATUS:
            log.warning("Gemini %s 사용 불가: %s", model, message)
            state.dead.add(model)
            return None

        if attempt < len(BACKOFF_SECONDS):
            # API 가 대기 시간을 알려주면 그걸 따른다. 임의로 더 빨리 두드리면
            # 429(분당 한도)를 맞아 상황이 나빠진다.
            wait = _retry_delay(response) or BACKOFF_SECONDS[attempt]
            if wait >= state.remaining():
                log.info("Gemini %s: 남은 시간보다 대기가 길어 중단", model)
                return None
            log.info("Gemini %s 혼잡(HTTP %d). %.0f초 후 재시도", model, status, wait)
            time.sleep(wait)

    return None


def _is_daily_quota(response: requests.Response) -> bool:
    """429 가 '분당' 한도인지 '하루' 한도인지 가른다.

    분당이면 잠깐 기다리면 풀리지만, 하루 한도는 자정(태평양 시간)까지 안 풀린다.
    """
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return False
    for detail in details:
        if not str(detail.get("@type", "")).endswith("QuotaFailure"):
            continue
        for violation in detail.get("violations", []):
            if "perday" in str(violation.get("quotaId", "")).lower():
                return True
    return False


def _retry_delay(response: requests.Response) -> float | None:
    """오류 본문의 RetryInfo('23s')를 초로 바꾼다. 없으면 None."""
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return None
    for detail in details:
        if not str(detail.get("@type", "")).endswith("RetryInfo"):
            continue
        raw = str(detail.get("retryDelay", "")).rstrip("s")
        try:
            return max(1.0, float(raw))
        except ValueError:
            return None
    return None


def _error_message(response: requests.Response) -> str:
    """오류 본문에서 메시지만 뽑는다. 키 값은 절대 로그에 남기지 않는다."""
    try:
        return str(response.json().get("error", {}).get("message", ""))[:200]
    except ValueError:
        return response.text[:200]


def _extract_json(payload: dict) -> dict:
    """응답 본문에서 모델이 낸 JSON 을 꺼낸다."""
    candidates = payload.get("candidates") or []
    if not candidates:
        feedback = payload.get("promptFeedback", {})
        raise ValueError(f"후보 응답 없음 (promptFeedback={feedback})")

    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise ValueError(f"빈 응답 (finishReason={candidates[0].get('finishReason')})")

    return json.loads(text)
