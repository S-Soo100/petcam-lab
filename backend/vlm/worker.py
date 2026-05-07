"""VLM 워커 — `camera_clips` 폴링 → R2 read → Gemini → `behavior_logs` INSERT.

`web/src/app/api/inference/route.ts` 의 라벨링 웹 inference handler 를 백그라운드
폴링 루프로 변환. PoC 와 핵심 차이:

- **트리거** — 사용자 클릭 (admin) → 시간 기반 폴링 (30s).
- **대상** — admin 이 클립 ID 골라 줌 → `has_motion=true AND r2_key NOT NULL AND
  NOT EXISTS (...)` 자동 선별.
- **idempotent** — UNIQUE(clip_id, source) 제약 + NOT EXISTS 폴링 (이중 방어).
- **에러 분기** — 폴백 raise 대신 일시/영구 분리. 영구 시 source='vlm_failed' INSERT
  로 같은 clip 무한 재시도 차단.

## 분해
- `poll_clips()` — DB 한 번 SELECT → list of rows. 호출별 LIMIT 적용.
- `process_clip(row)` — 1건 처리. R2 download → classify → INSERT. 예외는 로깅만.
- `run_once()` — poll + 결과 처리. 테스트가 1회 사이클만 돌릴 때 사용.
- `run()` — 무한 루프 (run_once + 30s sleep). stop_event.set() 으로 정지.

donts/python.md 룰 4 — boto3 / google-generativeai / supabase-py 모두 동기. 호출은
`asyncio.to_thread` 로 감싸서 이벤트 루프 안 막음.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from supabase import Client

from backend.vlm.gemini_client import (
    PERMANENT_ERRORS,
    TRANSIENT_ERRORS,
    VLM_MODEL_ID,
    VlmResponseInvalid,
    VlmResult,
    classify_clip,
    download_clip_bytes,
)
from backend.vlm.prompts import (
    SPECIES_CLASSES,
    build_system_prompt,
    map_db_species_to_code,
)

logger = logging.getLogger(__name__)

# spec §4-1 — LIMIT 10 + 30s. 카메라 2대 × 60s 세그먼트 = 2건/min 생성률 → 충분.
DEFAULT_POLL_INTERVAL_SEC = 30.0
DEFAULT_POLL_LIMIT = 10

# spec §4-1 SELECT — `camera_clips` LEFT JOIN `pets` LEFT JOIN `species` 등치를
# supabase-py PostgREST embedding 으로. NOT EXISTS 는 raw 쿼리 RPC 가 깔끔하지만
# 폴링 1건 쿼리에 RPC 만들기까진 과함 → SELECT 후 in-memory 필터.


@dataclass
class WorkerStats:
    """1 사이클 결과. 테스트 / 운영 로깅용."""

    polled: int = 0
    succeeded: int = 0
    failed_permanent: int = 0
    failed_transient: int = 0
    skipped_dup: int = 0  # 23505 — 동시 워커 race 의 패배자


@dataclass
class VlmWorker:
    """VLM 추론 워커.

    Args:
        sb: Supabase service_role client.
        poll_limit: 한 사이클 최대 처리 건수.
        poll_interval_sec: 사이클 간 대기.
    """

    sb: Client
    poll_limit: int = DEFAULT_POLL_LIMIT
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC

    # 누적 통계 (운영 디버깅용 — 24h 가동 후 logger.info).
    total_stats: WorkerStats = field(default_factory=WorkerStats)

    async def poll_clips(self) -> list[dict[str, Any]]:
        """미라벨 클립 N건 가져오기.

        spec §4-1: PostgreSQL RPC `fn_vlm_pending_clips(p_limit)` 호출 1번.
        DB 가 NOT EXISTS subquery 로 "has_motion + r2_key + behavior_logs 에 source IN
        (vlm, vlm_failed) row 없음" 클립을 oldest-first 로 N개 반환. 클라이언트 cutoff
        없음 → "159건 다 라벨됨 + 1건만 pending" 같은 임의 위치 케이스도 정확히 잡음.

        이전 2-step (done set 가져와서 in-memory diff) 은 limit*4 클라이언트 cutoff
        때문에 backlog 위치보다 작은 cutoff 면 신규/임의 pending 가 시야 밖이었음.
        """

        def _query() -> list[dict[str, Any]]:
            resp = self.sb.rpc(
                "fn_vlm_pending_clips", {"p_limit": self.poll_limit}
            ).execute()
            return list(resp.data or [])

        return await asyncio.to_thread(_query)

    @staticmethod
    def _resolve_species_id(clip_row: dict[str, Any]) -> Optional[str]:
        """RPC fn_vlm_pending_clips 응답에서 species_id 꺼내기. NULL pet → None.

        RPC 가 LEFT JOIN pets 로 species_id 를 flat 컬럼으로 반환 → row[species_id].
        """
        species_id = clip_row.get("species_id")
        return species_id if isinstance(species_id, str) else None

    async def process_clip(self, clip_row: dict[str, Any]) -> str:
        """1 클립 처리 → INSERT. 예외 분기 후 어떤 source 로 INSERT 됐는지 반환.

        Returns:
            'vlm' — 정상 INSERT
            'vlm_failed' — 영구 에러로 실패 row INSERT (같은 clip 재시도 차단)
            'transient' — 일시 에러, INSERT 안 함 (다음 사이클 재시도)
            'duplicate' — UNIQUE 제약 — 다른 워커가 먼저 INSERT (race)
        """
        clip_id = clip_row["id"]
        r2_key = clip_row.get("r2_key")
        if not r2_key:
            # poll_clips 가 NOT NULL 필터하지만 방어.
            logger.warning("clip %s r2_key 없음 — skip", clip_id)
            return "transient"

        species = map_db_species_to_code(self._resolve_species_id(clip_row))
        system_prompt = build_system_prompt(species)

        try:
            video_bytes = await asyncio.to_thread(download_clip_bytes, r2_key)
        except Exception as exc:  # noqa: BLE001 — botocore 다양
            logger.warning("clip %s R2 download 실패: %s — transient", clip_id, exc)
            return "transient"

        try:
            result: VlmResult = await asyncio.to_thread(
                classify_clip, video_bytes=video_bytes, system_prompt=system_prompt
            )
        except TRANSIENT_ERRORS as exc:
            logger.warning(
                "clip %s Gemini transient (%s): %s — 다음 사이클 재시도",
                clip_id,
                type(exc).__name__,
                exc,
            )
            return "transient"
        except (PERMANENT_ERRORS + (VlmResponseInvalid,)) as exc:
            logger.error(
                "clip %s Gemini permanent (%s): %s — vlm_failed INSERT",
                clip_id,
                type(exc).__name__,
                exc,
            )
            inserted = await self._insert_failed(clip_id, str(exc))
            return "vlm_failed" if inserted else "duplicate"

        # 종 가용성 검증 — eating_paste 가 leopard 응답일 때 confidence=0 (PoC §54-62).
        action = result.action
        confidence = result.confidence
        reasoning = result.reasoning
        if action not in SPECIES_CLASSES.get(species, []):
            logger.warning(
                "clip %s species mismatch — species=%s action=%s",
                clip_id,
                species,
                action,
            )
            confidence = 0.0
            reasoning = (
                f"[VALIDATION] species mismatch ({action} unavailable for {species}). "
                f"{reasoning}"
            )

        inserted = await self._insert_result(
            clip_id=clip_id,
            action=action,
            confidence=confidence,
            reasoning=reasoning,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )
        if not inserted:
            return "duplicate"
        logger.info(
            "clip %s → action=%s confidence=%.2f tokens=%s/%s",
            clip_id,
            action,
            confidence,
            result.tokens_input,
            result.tokens_output,
        )
        return "vlm"

    async def _insert_result(
        self,
        *,
        clip_id: str,
        action: str,
        confidence: float,
        reasoning: str,
        tokens_input: int | None,
        tokens_output: int | None,
    ) -> bool:
        """source='vlm' INSERT. 23505 (UNIQUE 위반) 시 False 반환.

        web PoC INSERT shape 동치 (`web/src/app/api/inference/route.ts:64`).
        cost_usd / tokens 컬럼 추가 시 여기에 같이 박을 것 (현재 spec §4-6 → 후속).
        """
        del tokens_input, tokens_output  # 현재 DB 컬럼 없음, logger 에서만 사용

        def _insert() -> bool:
            try:
                self.sb.table("behavior_logs").insert(
                    {
                        "clip_id": clip_id,
                        "frame_idx": 0,  # PoC 와 동일 — 클립 단위 단일 라벨
                        "action": action,
                        "confidence": confidence,
                        "source": "vlm",
                        "vlm_model": VLM_MODEL_ID,
                        "reasoning": reasoning,
                        "verified": False,
                    }
                ).execute()
                return True
            except Exception as exc:  # noqa: BLE001 — supabase-py PostgrestAPIError
                # PostgREST 23505 메시지 패턴 catch — supabase-py 가 별도 클래스
                # 안 줘서 문자열 매치. UNIQUE 위반 외엔 logger.exception + raise.
                msg = str(exc)
                if "23505" in msg or "duplicate key" in msg.lower():
                    logger.info(
                        "clip %s INSERT race 패배 (UNIQUE) — 다른 워커가 처리됨",
                        clip_id,
                    )
                    return False
                raise

        return await asyncio.to_thread(_insert)

    async def _insert_failed(self, clip_id: str, error_msg: str) -> bool:
        """source='vlm_failed' INSERT — 영구 에러 시 idempotency 보장."""

        def _insert() -> bool:
            try:
                self.sb.table("behavior_logs").insert(
                    {
                        "clip_id": clip_id,
                        "frame_idx": 0,
                        "action": "unseen",  # placeholder — UI 가 source 로 분기
                        "confidence": 0.0,
                        "source": "vlm_failed",
                        "vlm_model": VLM_MODEL_ID,
                        "reasoning": f"[PERMANENT_ERROR] {error_msg[:500]}",
                        "verified": False,
                    }
                ).execute()
                return True
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "23505" in msg or "duplicate key" in msg.lower():
                    return False
                logger.exception("vlm_failed INSERT 도 실패 — clip %s", clip_id)
                # 폴링 다음 사이클에 또 시도 — 같은 영구 에러 반복하면 비용 새지만
                # vlm_failed INSERT 자체가 망가진 거면 다른 alert 필요.
                return False

        return await asyncio.to_thread(_insert)

    async def run_once(self) -> WorkerStats:
        """한 사이클: poll → 직렬 처리. 테스트가 직접 호출.

        직렬 처리 이유 — Gemini Flash free tier 15 RPM. 동시 N 호출 시 429 폭주 가능.
        라운드 2~ 처리량 부족 시 chunk Promise.all 패턴 적용 (spec §3-PoC 참조).
        """
        stats = WorkerStats()
        clips = await self.poll_clips()
        stats.polled = len(clips)
        if not clips:
            return stats

        for clip in clips:
            try:
                outcome = await self.process_clip(clip)
            except Exception:  # noqa: BLE001 — 절대 워커 죽이지 않음
                logger.exception("clip %s 처리 중 예상치 못한 예외", clip["id"])
                stats.failed_transient += 1
                continue
            if outcome == "vlm":
                stats.succeeded += 1
            elif outcome == "vlm_failed":
                stats.failed_permanent += 1
            elif outcome == "transient":
                stats.failed_transient += 1
            elif outcome == "duplicate":
                stats.skipped_dup += 1

        # 누적
        for f in (
            "polled",
            "succeeded",
            "failed_permanent",
            "failed_transient",
            "skipped_dup",
        ):
            setattr(self.total_stats, f, getattr(self.total_stats, f) + getattr(stats, f))
        return stats

    async def run(self, stop_event: asyncio.Event) -> None:
        """무한 루프 — capture_main 의 amain 패턴.

        stop_event 가 set 되면 진행 중 사이클 완료 후 종료. 새 사이클 진입 차단.
        """
        logger.info(
            "vlm worker started — poll_interval=%.0fs limit=%d",
            self.poll_interval_sec,
            self.poll_limit,
        )
        while not stop_event.is_set():
            try:
                stats = await self.run_once()
                if stats.polled:
                    logger.info(
                        "cycle: polled=%d ok=%d failed=%d transient=%d dup=%d",
                        stats.polled,
                        stats.succeeded,
                        stats.failed_permanent,
                        stats.failed_transient,
                        stats.skipped_dup,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("run_once 자체 실패 — 다음 사이클 계속")

            # stop_event 또는 polling interval 중 먼저 발생.
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.poll_interval_sec
                )
            except asyncio.TimeoutError:
                continue

        logger.info(
            "vlm worker stopped — total: polled=%d ok=%d failed=%d transient=%d dup=%d",
            self.total_stats.polled,
            self.total_stats.succeeded,
            self.total_stats.failed_permanent,
            self.total_stats.failed_transient,
            self.total_stats.skipped_dup,
        )


__all__ = [
    "DEFAULT_POLL_INTERVAL_SEC",
    "DEFAULT_POLL_LIMIT",
    "VlmWorker",
    "WorkerStats",
]
