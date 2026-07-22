import { describe, expect, it } from 'vitest';

import { parseMotionQueueRequest } from './labelingV3QueueServer';

// motion_clips 큐/다음-영상 라우트가 공유하는 query 파서. 잘못된 값은 DB 접근 전에 error 문자열로
// 접어야 하므로 순수 함수로 고정한다(queue route 와 next route 가 같은 검증 계약을 쓴다).

const CAM = '22222222-2222-4222-8222-222222222222';

function ok(qs: string, isOwner = true) {
  const parsed = parseMotionQueueRequest(new URLSearchParams(qs), isOwner);
  if ('error' in parsed) throw new Error(`expected params, got error: ${parsed.error}`);
  return parsed.params;
}

describe('parseMotionQueueRequest', () => {
  it('유효 owner 필터를 그대로 통과시킨다', () => {
    expect(parseMotionQueueRequest(new URLSearchParams('state=unreviewed&media=ready'), true)).toMatchObject({
      params: { state: 'unreviewed', media: 'ready' },
    });
  });

  it('camera_id 가 UUID 가 아니면 error', () => {
    expect(parseMotionQueueRequest(new URLSearchParams('camera_id=bad'), true)).toEqual({
      error: '잘못된 camera_id',
    });
  });

  it('limit 기본 30, 상한 99 로 clamp', () => {
    expect(ok('').limit).toBe(30);
    expect(ok('limit=10').limit).toBe(10);
    expect(ok('limit=100').limit).toBe(99);
  });

  it('limit 이 양의 정수가 아니면 error', () => {
    for (const qs of ['limit=0', 'limit=-3', 'limit=abc']) {
      expect(parseMotionQueueRequest(new URLSearchParams(qs), true)).toEqual({ error: '잘못된 limit' });
    }
  });

  it('owner state=all 은 null 로 접는다', () => {
    expect(ok('state=all').state).toBeNull();
  });

  it('owner 의 미지 state 는 error', () => {
    expect(parseMotionQueueRequest(new URLSearchParams('state=quarantine'), true)).toEqual({
      error: '잘못된 state',
    });
  });

  it('labeler 는 state 를 무시한다(항상 null)', () => {
    expect(ok('state=skip', false).state).toBeNull();
  });

  it('offset 없는 RFC3339 date 는 error', () => {
    expect(parseMotionQueueRequest(new URLSearchParams('date_from=2026-07-21'), true)).toEqual({
      error: '잘못된 date_from',
    });
    expect(parseMotionQueueRequest(new URLSearchParams('date_to=nope'), true)).toEqual({
      error: '잘못된 date_to',
    });
  });

  it('유효 필터를 정규화한다', () => {
    // 쿼리 안의 + 는 URLSearchParams 에서 공백으로 디코드되므로 offset 은 %2B 로 인코드한다.
    const params = ok(
      `camera_id=${CAM}&date_from=2026-07-21T00:00:00%2B09:00&date_to=2026-07-22T00:00:00%2B09:00&media=ready`,
    );
    expect(params.cameraIds).toEqual([CAM]);
    expect(params.dateFrom).toBe('2026-07-21T00:00:00+09:00');
    expect(params.dateTo).toBe('2026-07-22T00:00:00+09:00');
    expect(params.media).toBe('ready');
  });

  it('잘못된 media 는 error', () => {
    expect(parseMotionQueueRequest(new URLSearchParams('media=maybe'), true)).toEqual({
      error: '잘못된 media',
    });
  });
});
