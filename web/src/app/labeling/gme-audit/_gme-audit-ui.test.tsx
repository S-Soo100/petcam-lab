import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { vi } from 'vitest';

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));

import type { AuditDetailItem, AuditQueueResponse } from '@/lib/gmeNegativeAudit';
import { ApiError } from '@/lib/labelingApi';
import GmeAuditWorkspace, {
  auditErrorMessage,
  auditDraftKey,
  clearAuditDraft,
  isStaleCorrection,
  parseAuditDraft,
  readAuditDraft,
  selectAuditVerdict,
  nextAuditHref,
  writeAuditDraft,
} from './_gme-audit-workspace';

function publicItem(overrides: Partial<AuditDetailItem> = {}): AuditDetailItem {
  return {
    item_id: 'item / 1',
    ordinal: 7,
    captured_at: '2026-08-23T01:02:03Z',
    duration_sec: 60,
    media_ready: true,
    initial_verdict: null,
    initial_representative_sec: null,
    initial_bbox: null,
    effective_verdict: null,
    effective_representative_sec: null,
    effective_bbox: null,
    revision: null,
    ...overrides,
  };
}

function queue(): AuditQueueResponse {
  return {
    completed: 1,
    total: 3,
    items: [
      { item_id: 'first / one', ordinal: 1, captured_at: 'x', duration_sec: 20, media_ready: true, submitted: false },
      { item_id: 'done ? two', ordinal: 2, captured_at: 'x', duration_sec: 20, media_ready: true, submitted: true },
      { item_id: 'third # three', ordinal: 3, captured_at: 'x', duration_sec: 20, media_ready: true, submitted: false },
    ],
  };
}

describe('GME audit blind UI', () => {
  it('shows exactly four Korean human verdicts and no model or internal hint', () => {
    const html = renderToStaticMarkup(<GmeAuditWorkspace itemId="item / 1" initialItem={publicItem()} />);
    for (const text of ['게코 있음', '게코 없음', '판단 어려움', '영상 오류']) {
      expect(html).toContain(text);
    }
    for (const forbidden of [
      'GME negative', 'control', 'detected=false', '활동량', 'confidence', 'stratum',
      'captured_at', 'source', 'hash', 'revision', 'item / 1',
    ]) {
      expect(html).not.toContain(forbidden);
    }
  });

  it('keeps 320px-safe controls and semantic labels in the detail markup', () => {
    const html = renderToStaticMarkup(<GmeAuditWorkspace itemId="x" initialItem={publicItem({ item_id: 'x' })} />);
    expect(html).toContain('min-w-0');
    expect(html).toContain('grid-cols-1');
    expect(html).toContain('sm:grid-cols-2');
    expect(html).toContain('min-h-11');
    expect(html).toContain('<fieldset');
    expect(html).toContain('<legend');
    expect(html).toContain('aria-live="polite"');
  });

  it('restores only the reviewer effective verdict for correction without exposing its token', () => {
    const html = renderToStaticMarkup(<GmeAuditWorkspace itemId="x" initialItem={publicItem({
      item_id: 'x',
      initial_verdict: 'gecko_absent',
      effective_verdict: 'uncertain',
      revision: 'opaque-private-token',
    })} />);
    expect(html).toContain('checked="" value="uncertain"');
    expect(html).toContain('정정 이유');
    expect(html).toContain('정정 저장');
    expect(html).not.toContain('opaque-private-token');
    expect(html).not.toContain('revision');
  });

  it('renders loading and empty queue states without internal details', () => {
    expect(renderToStaticMarkup(<GmeAuditWorkspace />)).toContain('점검 항목을 불러오는 중');
    const empty = renderToStaticMarkup(<GmeAuditWorkspace initialQueue={{ items: [], completed: 0, total: 0 }} />);
    expect(empty).toContain('배정된 점검 항목이 없어');
    expect(empty).not.toContain('source');
  });

  it('queue reveals only progress and ordinals, with safe encoded links', () => {
    const html = renderToStaticMarkup(<GmeAuditWorkspace initialQueue={queue()} />);
    expect(html).toContain('완료 1 / 3');
    expect(html).toContain('항목 1');
    expect(html).toContain('내가 완료한 항목');
    expect(html).toContain('항목 2 정정');
    expect(html).toContain('/labeling/gme-audit/first%20%2F%20one');
    expect(html).toContain('/labeling/gme-audit/done%20%3F%20two');
    for (const forbidden of ['captured_at', 'media_ready', 'GME', 'control', 'source', 'hash', 'revision']) {
      expect(html).not.toContain(forbidden);
    }
  });
});

describe('GME audit interaction state', () => {
  it('clears timestamp and bbox when the user changes away from gecko present', () => {
    const present = {
      verdict: 'gecko_present' as const,
      representative_sec: 3.5,
      bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
    };
    expect(selectAuditVerdict(present, 'gecko_absent')).toEqual({
      verdict: 'gecko_absent',
      representative_sec: null,
      bbox: null,
    });
    expect(selectAuditVerdict(present, 'gecko_present')).toEqual(present);
  });

  it('binds a strict draft to one item, rejects corrupted/internal fields, and preserves no internals', () => {
    expect(auditDraftKey('batch-a:item-1')).not.toBe(auditDraftKey('batch-a:item-2'));
    const raw = JSON.stringify({
      v: 1,
      item_id: 'item-1',
      verdict: 'gecko_present',
      representative_sec: 4,
      bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
    });
    expect(parseAuditDraft(raw, 'item-1', 60)).toEqual({
      verdict: 'gecko_present',
      representative_sec: 4,
      bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
    });
    expect(parseAuditDraft(raw, 'item-2', 60)).toBeNull();
    expect(parseAuditDraft(raw.replace('"v":1', '"v":2'), 'item-1', 60)).toBeNull();
    expect(parseAuditDraft(raw.slice(0, -1) + ',"confidence":0.9}', 'item-1', 60)).toBeNull();
    expect(raw).not.toContain('GME');
    expect(raw).not.toContain('source');
    expect(raw).not.toContain('revision');
  });

  it('uses storage helpers to remove invalid drafts and clear a successful item only', () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const state = { verdict: 'gecko_absent' as const, representative_sec: null, bbox: null };
    expect(writeAuditDraft(storage, 'item-a', state)).toBe(true);
    expect(readAuditDraft(storage, 'item-a', 60)).toEqual(state);
    const stored = values.get(auditDraftKey('item-a')) ?? '';
    for (const forbidden of ['GME', 'source', 'hash', 'revision', 'confidence']) expect(stored).not.toContain(forbidden);

    values.set(auditDraftKey('item-b'), '{"v":1,"item_id":"wrong"}');
    expect(readAuditDraft(storage, 'item-b', 60)).toBeNull();
    expect(values.has(auditDraftKey('item-b'))).toBe(false);
    clearAuditDraft(storage, 'item-a');
    expect(values.has(auditDraftKey('item-a'))).toBe(false);
  });

  it('folds 404/410/502/network errors and stale correction into understandable retry states', () => {
    expect(auditErrorMessage(new ApiError(404, 'raw secret'), 'item')).toContain('열 수 없어');
    expect(auditErrorMessage(new ApiError(410, 'raw secret'), 'item')).toContain('마감');
    expect(auditErrorMessage(new ApiError(502, 'raw secret'), 'media')).toContain('다시 시도');
    expect(auditErrorMessage(new ApiError(0, 'raw secret'), 'queue')).toContain('다시 시도');
    expect(auditErrorMessage(new Error('raw secret'), 'save')).not.toContain('raw secret');
    expect(isStaleCorrection(new ApiError(409, 'raw secret'), true)).toBe(true);
    expect(isStaleCorrection(new ApiError(409, 'raw secret'), false)).toBe(false);
  });

  it('uses API order for the next unfinished item and safely encodes its id', () => {
    expect(nextAuditHref(queue(), 'first / one')).toBe('/labeling/gme-audit/third%20%23%20three');
    expect(nextAuditHref({ ...queue(), items: queue().items.map((item) => ({ ...item, submitted: true })) }, 'x'))
      .toBe('/labeling/gme-audit');
  });
});
