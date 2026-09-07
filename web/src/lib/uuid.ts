// 라벨링 API 공용 UUID 판정. 느슨한 8-4-4-4-12 hex(대소문자 무관) — Postgres uuid 텍스트 형식과 동일.
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(v: unknown): v is string {
  return typeof v === 'string' && UUID_RE.test(v);
}
