import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  AutoExcludedView,
  formatRetentionRemaining,
  removeExclusion,
} from './_auto-excluded-list';
import type { MotionSystemExclusionItem } from '@/lib/labelingV3';

const NOW = new Date('2026-07-22T00:00:00Z');

function item(overrides: Partial<MotionSystemExclusionItem> = {}): MotionSystemExclusionItem {
  return {
    clip_id: '11111111-1111-4111-8111-111111111111',
    camera_name: 'P4 Cam 2(dev)',
    started_at: '2026-07-21T16:30:00+00:00',
    duration_sec: 4,
    displayed_duration_sec: 4,
    state: 'quarantined',
    rule_version: 'short-device-error-v1',
    quarantined_at: '2026-07-21T16:31:00+00:00',
    delete_after: '2026-07-28T16:31:00+00:00',
    media_deleted_at: null,
    media_ready: true,
    ...overrides,
  };
}

function render(items: MotionSystemExclusionItem[]): string {
  return renderToStaticMarkup(
    <AutoExcludedView items={items} now={NOW} onRestore={() => undefined} emptyLabel="자동 제외된 영상이 없어." />,
  );
}

describe('AutoExcludedView', () => {
  it('제목·장치 오류 후보·규칙·실제/표시 길이·보존 잔여를 보여준다', () => {
    const html = render([item()]);
    expect(html).toContain('자동 제외');
    expect(html).toContain('장치 오류 후보');
    expect(html).toContain('short-device-error-v1');
    expect(html).toContain('실제 4.0초');
    expect(html).toContain('표시 4초');
    expect(html).toContain('삭제까지'); // 보존 잔여 텍스트
    // 버튼 문구는 "시스템 해제" 의미로 교정 — 복구가 사람 판정을 바꾸지 않음을 명시(설계 §4·§5.1).
    expect(html).toContain('자동 제외만 해제');
    expect(html).toContain('기존 사람 판정은 유지돼.');
    expect(html).toContain('라벨 대상으로 바꾸려면 영상 상세에서 별도로 변경해.');
    // 옛 문구(라벨 대상으로 복구)는 더 이상 노출되지 않는다.
    expect(html).not.toContain('라벨 대상으로 복구');
  });

  it('media_deleted 카드는 원본 삭제됨·메타데이터 보존 + 재생 비활성 + 복구 버튼 없음', () => {
    const html = render([
      item({
        clip_id: '22222222-2222-4222-8222-222222222222',
        state: 'media_deleted',
        delete_after: null,
        media_deleted_at: '2026-07-28T16:31:00+00:00',
        media_ready: false,
      }),
    ]);
    expect(html).toContain('원본 삭제됨 · 메타데이터 보존');
    expect(html).toContain('재생 불가');
    expect(html).toContain('disabled');
    expect(html).not.toContain('자동 제외만 해제');
  });

  it('복구 버튼은 quarantined 카드에만 붙는다', () => {
    const html = render([
      item(),
      item({
        clip_id: '22222222-2222-4222-8222-222222222222',
        state: 'media_deleted',
        delete_after: null,
        media_deleted_at: '2026-07-28T16:31:00+00:00',
        media_ready: false,
      }),
    ]);
    expect(html.match(/자동 제외만 해제/g)).toHaveLength(1);
  });

  it('320px 대응: 1열 그리드 + 텍스트 줄바꿈(가로 스크롤 유발 없음)', () => {
    const html = render([item()]);
    expect(html).toContain('grid-cols-1');
    expect(html).toContain('break-words');
  });

  it('빈 목록이면 카드 없이 안내 문구만', () => {
    const html = render([]);
    expect(html).toContain('자동 제외된 영상이 없어.');
    // 카드 고유 토큰(규칙 라인)이 없어야 한다 — 설명 문구의 '장치 오류' 언급과 구분.
    expect(html).not.toContain('규칙 short-device-error');
    expect(html).not.toContain('자동 제외만 해제');
  });
});

describe('formatRetentionRemaining', () => {
  it('미래 delete_after 는 남은 시간을, null 은 null 을 준다', () => {
    expect(formatRetentionRemaining(null, NOW)).toBeNull();
    expect(formatRetentionRemaining('2026-07-28T16:31:00+00:00', NOW)).toContain('삭제까지');
    // 48시간 미만은 시간 단위.
    expect(formatRetentionRemaining('2026-07-22T12:00:00Z', NOW)).toContain('시간');
    // 지난 시점은 경과 안내.
    expect(formatRetentionRemaining('2026-07-21T00:00:00Z', NOW)).toContain('지났');
  });
});

describe('removeExclusion', () => {
  it('복구된 clip 카드만 활성 목록에서 제거한다(다른 탭 이동 없음)', () => {
    const a = item();
    const b = item({ clip_id: '22222222-2222-4222-8222-222222222222' });
    const next = removeExclusion([a, b], a.clip_id);
    expect(next).toHaveLength(1);
    expect(next[0].clip_id).toBe(b.clip_id);
  });
});
