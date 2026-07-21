import 'server-only';
import { Buffer } from 'node:buffer';

// 라벨링 큐 복합 cursor — `(started_at DESC, id DESC)` keyset 의 위치를 versioned
// opaque base64url 문자열로 인코딩한다(설계 §4.2). started_at 하나만으로는 같은 시각의
// 여러 clip 순서가 결정론적이지 않아 다음 페이지에서 누락이 생기므로 id 를 동률 해소키로
// 함께 담는다. decode 실패·필드 누락·미지 version 은 전부 InvalidQueueCursorError 로
// 접어서(원문/내부 오류 비노출) route 가 일반화된 400 invalid_cursor 로 응답한다.

// canonical 8-4-4-4-12 hex 만 확인한다. version(3번째 그룹 첫 nibble)·variant(4번째 그룹
// 첫 nibble) 를 제한하지 않는 이유: PostgreSQL uuid 타입은 UUIDv7 도 저장하므로, v1~5 로
// 좁히면 서버가 만든 cursor 를 다음 요청에서 스스로 400 처리한다(F2). 길이·hex·구분자 오류는
// 여전히 거부된다.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface QueuePosition {
  startedAt: string;
  id: string;
}

export class InvalidQueueCursorError extends Error {
  constructor() {
    super('invalid_queue_cursor');
    this.name = 'InvalidQueueCursorError';
  }
}

// strict RFC3339 — 날짜 + T + 시각, 선택적 소수 초 1~9자리, 끝은 Z 또는 ±HH:mm.
// Date.parse 의 관대한 파싱(date-only·timezone 누락·이상 offset 허용)을 막는다. 이유 둘:
// ① cursor.startedAt 은 route 에서 PostgREST filter 문자열(`started_at.lt.<값>` / `.eq.`)에
//    그대로 들어가므로, 쉼표·괄호 같은 filter 문법 문자가 timestamp 로 새면 안 된다.
// ② timezone 없는 값은 실제 instant 가 모호해 keyset 경계로 못 쓴다.
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;

function validTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length <= 64 &&
    RFC3339.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

export function encodeQueueCursor(position: QueuePosition): string {
  return Buffer.from(JSON.stringify({ v: 1, t: position.startedAt, id: position.id }), 'utf8')
    .toString('base64url');
}

export function decodeQueueCursor(raw: string | null): QueuePosition | null {
  // null/빈 문자열 = cursor 없음 = 첫 페이지. 오류가 아니다.
  if (raw === null || raw === '') return null;
  try {
    const value = JSON.parse(Buffer.from(raw, 'base64url').toString('utf8')) as Record<string, unknown>;
    if (value.v !== 1 || !validTimestamp(value.t) || typeof value.id !== 'string' || !UUID.test(value.id)) {
      throw new InvalidQueueCursorError();
    }
    // 검증된 timestamp 원문을 그대로 반환한다. new Date().toISOString() 로 재직렬화하면
    // 마이크로초가 밀리초로 잘려(.123456→.123) DESC keyset 경계가 .123000 으로 이동, 그 사이
    // 행을 건너뛴다(P2). id 는 소문자로 정규화한다.
    return { startedAt: value.t, id: value.id.toLowerCase() };
  } catch (error) {
    if (error instanceof InvalidQueueCursorError) throw error;
    // base64/JSON 파싱 실패도 동일하게 일반화된 invalid cursor 로만 노출한다.
    throw new InvalidQueueCursorError();
  }
}
