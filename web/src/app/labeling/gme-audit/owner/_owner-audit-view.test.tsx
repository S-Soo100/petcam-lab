import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import * as ReactRuntime from 'react';

const browser = vi.hoisted(() => ({
  getSession: vi.fn(),
}));
vi.mock('@/lib/supabaseBrowser', () => ({
  getSupabaseBrowser: () => ({ auth: { getSession: browser.getSession } }),
}));

import { ApiError } from '@/lib/labelingApi';
import {
  getAuditOwnerOverview,
  type AuditOwnerOverview,
} from '@/lib/gmeNegativeAuditApi';
import OwnerAuditView from './_owner-audit-view';

const ITEM = '11111111-1111-4111-8111-111111111111';
const DIGEST = 'a'.repeat(64);

function overview(stratum: 'random_negative' | 'positive_control' = 'random_negative'): AuditOwnerOverview {
  return {
    batch_id: '22222222-2222-4222-8222-222222222222',
    completed: 90,
    total: 150,
    random_negative: { completed: 70, total: 120 },
    positive_control: { completed: 20, total: 30 },
    needs_adjudication: [{
      item_id: ITEM,
      ordinal: 17,
      duration_sec: 60,
      stratum,
      effective_verdict: 'gecko_present',
      effective_representative_sec: 12.5,
      effective_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
      expected_submission_digest: DIGEST,
    }],
  };
}

type ElementNode = { type: unknown; props: Record<string, unknown> };
type HookSlot = Record<string, unknown>;

class HookHarness {
  private cursor = 0;
  private slots: HookSlot[] = [];
  private pending: Array<{ index: number; effect: () => void | (() => void) }> = [];

  render<T>(callback: () => T): T {
    this.cursor = 0;
    this.pending = [];
    return callback();
  }

  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
    const index = this.cursor++;
    if (!this.slots[index]) this.slots[index] = { value: typeof initial === 'function' ? (initial as () => T)() : initial };
    return [this.slots[index].value as T, (next) => {
      const current = this.slots[index].value as T;
      this.slots[index].value = typeof next === 'function' ? (next as (value: T) => T)(current) : next;
    }];
  }

  useEffect(effect: () => void | (() => void), deps?: readonly unknown[]): void {
    const index = this.cursor++;
    const previous = this.slots[index];
    if (!previous || !sameDeps(previous.deps as readonly unknown[] | undefined, deps)) {
      this.pending.push({ index, effect });
      this.slots[index] = { deps, cleanup: previous?.cleanup };
    }
  }

  runEffects(): void {
    const pending = this.pending.splice(0);
    for (const entry of pending) {
      const cleanup = this.slots[entry.index].cleanup;
      if (typeof cleanup === 'function') (cleanup as () => void)();
      this.slots[entry.index].cleanup = entry.effect();
    }
  }
}

function sameDeps(left?: readonly unknown[], right?: readonly unknown[]): boolean {
  if (!left || !right || left.length !== right.length) return false;
  return left.every((value, index) => Object.is(value, right[index]));
}

function allElements(node: unknown, output: ElementNode[] = []): ElementNode[] {
  if (Array.isArray(node)) {
    for (const child of node) allElements(child, output);
    return output;
  }
  if (!node || typeof node !== 'object' || !('props' in node)) return output;
  const element = node as ElementNode;
  output.push(element);
  const children = typeof element.type === 'function'
    ? (element.type as (props: Record<string, unknown>) => unknown)(element.props)
    : element.props.children;
  allElements(children, output);
  return output;
}

function text(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('');
  if (!node || typeof node !== 'object' || !('props' in node)) return '';
  const element = node as ElementNode;
  return text(typeof element.type === 'function'
    ? (element.type as (props: Record<string, unknown>) => unknown)(element.props)
    : element.props.children);
}

function element(node: unknown, predicate: (entry: ElementNode) => boolean): ElementNode {
  const found = allElements(node).find(predicate);
  if (!found) throw new Error('interaction element not found');
  return found;
}

async function flushAsync(): Promise<void> {
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
}

async function interactiveModule(harness: HookHarness) {
  vi.resetModules();
  vi.doMock('react', () => ({
    ...ReactRuntime,
    useState: <T,>(initial: T | (() => T)) => harness.useState(initial),
    useEffect: (effect: () => void | (() => void), deps?: readonly unknown[]) => harness.useEffect(effect, deps),
  }));
  return import('./_owner-audit-view');
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('GME audit Owner UI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    browser.getSession.mockResolvedValue({ data: { session: { access_token: 'owner-token' } } });
  });

  it('shows random/control progress and only pending Owner evidence without private identities', () => {
    const html = renderToStaticMarkup(<OwnerAuditView initialOverview={overview()} />);

    expect(html).toContain('완료 90 / 150');
    expect(html).toContain('무작위 negative 70 / 120');
    expect(html).toContain('양성 control 20 / 30');
    expect(html).toContain('Owner 판정 대기 1');
    expect(html).toContain('항목 17');
    expect(html).toContain('게코 있음');
    expect(html).toContain('min-w-0');
    expect(html).toContain('min-h-11');
    for (const forbidden of [ITEM, DIGEST, 'reviewer_id', 'assigned_reviewer', 'r2_key', 'source', 'gme_run', 'model']) {
      expect(html).not.toContain(forbidden);
    }
  });

  it('adjudicates append-only, then enables an eligible non-control Dataset decision', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ status: 'adjudicated', effective_digest: 'b'.repeat(64) }))
      .mockResolvedValueOnce(jsonResponse({ status: 'decided' }));
    vi.stubGlobal('fetch', fetchMock);
    const harness = new HookHarness();
    const { default: InteractiveView } = await interactiveModule(harness);
    let tree = harness.render(() => InteractiveView({ initialOverview: overview() }));

    expect(text(tree)).toContain('검토 열기');
    (element(tree, (entry) => typeof entry.props.onClick === 'function' && text(entry) === '검토 열기').props.onClick as () => void)();
    tree = harness.render(() => InteractiveView({ initialOverview: overview() }));
    expect(text(tree)).toContain('검수자 유효 판정: 게코 있음');
    expect(text(tree)).toContain('대표 시점 12.5초');

    (element(tree, (entry) => entry.type === 'textarea' && entry.props['aria-label'] === 'Owner 판정 이유').props.onChange as (event: unknown) => void)({ target: { value: 'Owner가 증거를 확인함' } });
    tree = harness.render(() => InteractiveView({ initialOverview: overview() }));
    await (element(tree, (entry) => entry.type === 'form' && entry.props['data-action'] === 'adjudicate').props.onSubmit as (event: unknown) => Promise<void>)({ preventDefault() {} });
    await flushAsync();
    tree = harness.render(() => InteractiveView({ initialOverview: overview() }));

    expect(text(tree)).toContain('Owner 판정을 append-only로 저장했어.');
    expect(text(tree)).toContain('Dataset 후보 결정');
    expect(text(tree)).toContain('후보 포함');
    expect(text(tree)).not.toContain('b'.repeat(64));

    (element(tree, (entry) => entry.type === 'textarea' && entry.props['aria-label'] === 'Dataset 결정 이유').props.onChange as (event: unknown) => void)({ target: { value: '중복과 holdout을 확인할 후보' } });
    tree = harness.render(() => InteractiveView({ initialOverview: overview() }));
    await (element(tree, (entry) => entry.type === 'form' && entry.props['data-action'] === 'dataset-decision').props.onSubmit as (event: unknown) => Promise<void>)({ preventDefault() {} });
    await flushAsync();
    tree = harness.render(() => InteractiveView({ initialOverview: overview() }));

    expect(text(tree)).toContain('Dataset 결정을 append-only로 저장했어.');
    const requests = fetchMock.mock.calls.map(([path, init]) => ({ path, body: JSON.parse(String(init.body)) }));
    expect(requests).toEqual([
      {
        path: `/api/labeling-v3/gme-audit/owner/${ITEM}/adjudicate`,
        body: {
          final_verdict: 'gecko_present', representative_sec: 12.5,
          bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
          reason: 'Owner가 증거를 확인함', expected_submission_digest: DIGEST,
        },
      },
      {
        path: `/api/labeling-v3/gme-audit/owner/${ITEM}/dataset-decision`,
        body: {
          decision: 'include_candidate', reason: '중복과 holdout을 확인할 후보',
          expected_effective_digest: 'b'.repeat(64),
        },
      },
    ]);
  });

  it('keeps Dataset controls hidden for positive controls after adjudication', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'adjudicated', effective_digest: 'b'.repeat(64) })));
    const harness = new HookHarness();
    const { default: InteractiveView } = await interactiveModule(harness);
    let tree = harness.render(() => InteractiveView({ initialOverview: overview('positive_control') }));
    (element(tree, (entry) => typeof entry.props.onClick === 'function' && text(entry) === '검토 열기').props.onClick as () => void)();
    tree = harness.render(() => InteractiveView({ initialOverview: overview('positive_control') }));
    (element(tree, (entry) => entry.type === 'textarea' && entry.props['aria-label'] === 'Owner 판정 이유').props.onChange as (event: unknown) => void)({ target: { value: 'control 확인 완료' } });
    tree = harness.render(() => InteractiveView({ initialOverview: overview('positive_control') }));
    await (element(tree, (entry) => entry.type === 'form' && entry.props['data-action'] === 'adjudicate').props.onSubmit as (event: unknown) => Promise<void>)({ preventDefault() {} });
    await flushAsync();
    tree = harness.render(() => InteractiveView({ initialOverview: overview('positive_control') }));

    expect(text(tree)).toContain('양성 control은 Dataset 후보 결정 대상이 아니야.');
    expect(allElements(tree).some((entry) => entry.type === 'form' && entry.props['data-action'] === 'dataset-decision')).toBe(false);
    expect(text(tree)).not.toContain('후보 포함');
  });

  it('reloads the pending overview on stale 409 instead of pretending to save', async () => {
    const refreshed = overview();
    refreshed.needs_adjudication[0].effective_verdict = 'uncertain';
    refreshed.needs_adjudication[0].effective_representative_sec = null;
    refreshed.needs_adjudication[0].effective_bbox = null;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: 'stale', code: 'stale_revision' }, 409))
      .mockResolvedValueOnce(jsonResponse(refreshed));
    vi.stubGlobal('fetch', fetchMock);
    const harness = new HookHarness();
    const { default: InteractiveView } = await interactiveModule(harness);
    let tree = harness.render(() => InteractiveView({ initialOverview: overview() }));
    (element(tree, (entry) => typeof entry.props.onClick === 'function' && text(entry) === '검토 열기').props.onClick as () => void)();
    tree = harness.render(() => InteractiveView({ initialOverview: overview() }));
    (element(tree, (entry) => entry.type === 'textarea' && entry.props['aria-label'] === 'Owner 판정 이유').props.onChange as (event: unknown) => void)({ target: { value: '확인' } });
    tree = harness.render(() => InteractiveView({ initialOverview: overview() }));
    await (element(tree, (entry) => entry.type === 'form' && entry.props['data-action'] === 'adjudicate').props.onSubmit as (event: unknown) => Promise<void>)({ preventDefault() {} });
    await flushAsync();
    tree = harness.render(() => InteractiveView({ initialOverview: overview() }));

    expect(text(tree)).toContain('판정이 바뀌어서 최신 대기 목록을 다시 불러왔어.');
    expect(text(tree)).not.toContain('append-only로 저장했어');
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      `/api/labeling-v3/gme-audit/owner/${ITEM}/adjudicate`,
      '/api/labeling-v3/gme-audit/owner/overview',
    ]);
  });

  it('browser overview wrapper rejects wrong MIME and extra private fields', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(overview()), {
      status: 200, headers: { 'content-type': 'text/plain' },
    })));
    await expect(getAuditOwnerOverview()).rejects.toMatchObject({ status: 502, code: 'invalid_response' });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ...overview(), reviewer_id: 'hidden' })));
    await expect(getAuditOwnerOverview()).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
  });
});
