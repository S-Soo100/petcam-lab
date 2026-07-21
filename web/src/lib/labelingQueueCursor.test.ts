import { describe, expect, it } from 'vitest';
import {
  decodeQueueCursor,
  encodeQueueCursor,
  InvalidQueueCursorError,
} from './labelingQueueCursor';

const POSITION = {
  startedAt: '2026-07-22T01:02:03.456Z',
  id: '11111111-1111-4111-8111-111111111111',
};

describe('labelingQueueCursor', () => {
  it('round-trips a URL-safe version 1 cursor', () => {
    const encoded = encodeQueueCursor(POSITION);
    expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeQueueCursor(encoded)).toEqual(POSITION);
  });

  it.each([
    'not-base64!',
    Buffer.from(JSON.stringify({ v: 2, t: POSITION.startedAt, id: POSITION.id })).toString('base64url'),
    Buffer.from(JSON.stringify({ v: 1, t: 'bad', id: POSITION.id })).toString('base64url'),
    Buffer.from(JSON.stringify({ v: 1, t: POSITION.startedAt, id: 'bad' })).toString('base64url'),
  ])('rejects malformed cursor %s', (raw) => {
    expect(() => decodeQueueCursor(raw)).toThrow(InvalidQueueCursorError);
  });

  it('maps null to the first page', () => {
    expect(decodeQueueCursor(null)).toBeNull();
  });

  // F2 회귀 — PostgreSQL uuid 타입은 canonical UUIDv7 도 저장한다.
  // version nibble 을 1~5 로 제한하면 서버가 스스로 만든 cursor 를 다음 요청에서 400 처리한다.
  it('round-trips a canonical UUIDv7 cursor', () => {
    const position = {
      startedAt: '2026-07-22T01:02:03.456Z',
      // 13번째 hex = version 7, 17번째 hex = variant 8 → v1~5 제한 regex 는 이걸 거부한다.
      id: '018f8c1e-7c3a-7abc-8def-0123456789ab',
    };
    const encoded = encodeQueueCursor(position);
    expect(decodeQueueCursor(encoded)).toEqual(position);
  });

  // 형식만 완화하고 길이·hex·구분자 오류는 계속 거부해야 한다.
  it.each([
    '018f8c1e7c3a7abc8def0123456789ab', // 하이픈 없음
    '018f8c1e-7c3a-7abc-8def-0123456789a', // 마지막 그룹 11자(길이 부족)
    '018f8c1e-7c3a-7abc-8def-0123456789ag', // non-hex 'g'
    '018f8c1e-7c3a-7abc-8def0123456789ab', // 구분자 위치 오류
  ])('still rejects malformed uuid %s', (id) => {
    const raw = Buffer.from(
      JSON.stringify({ v: 1, t: POSITION.startedAt, id }),
    ).toString('base64url');
    expect(() => decodeQueueCursor(raw)).toThrow(InvalidQueueCursorError);
  });
});
