import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { vi } from 'vitest';
import * as ReactRuntime from 'react';

const clientMocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getAuditQueue: vi.fn(),
  getAuditItem: vi.fn(),
  getAuditMedia: vi.fn(),
  submitAudit: vi.fn(),
  correctAudit: vi.fn(),
}));

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: clientMocks.replace, refresh: vi.fn() }),
}));
vi.mock('@/lib/gmeNegativeAuditApi', () => ({
  getAuditQueue: clientMocks.getAuditQueue,
  getAuditItem: clientMocks.getAuditItem,
  getAuditMedia: clientMocks.getAuditMedia,
  submitAudit: clientMocks.submitAudit,
  correctAudit: clientMocks.correctAudit,
}));

import type { AuditDetailItem, AuditQueueResponse } from '@/lib/gmeNegativeAudit';
import { ApiError } from '@/lib/labelingApi';
import GmeAuditWorkspace, {
  auditErrorMessage,
  auditDraftKey,
  beginAuditMediaRequest,
  clearAuditDraft,
  isStaleCorrection,
  markAuditMediaLoaded,
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
    if (!this.slots[index]) {
      this.slots[index] = { kind: 'state', value: typeof initial === 'function' ? (initial as () => T)() : initial };
    }
    const set = (next: T | ((current: T) => T)) => {
      const current = this.slots[index].value as T;
      this.slots[index].value = typeof next === 'function' ? (next as (value: T) => T)(current) : next;
    };
    return [this.slots[index].value as T, set];
  }

  useRef<T>(initial: T): { current: T } {
    const index = this.cursor++;
    if (!this.slots[index]) this.slots[index] = { kind: 'ref', value: { current: initial } };
    return this.slots[index].value as { current: T };
  }

  useCallback<T extends (...args: never[]) => unknown>(callback: T, deps: readonly unknown[]): T {
    const index = this.cursor++;
    const previous = this.slots[index];
    if (!previous || !sameDeps(previous.deps as readonly unknown[] | undefined, deps)) {
      this.slots[index] = { kind: 'memo', value: callback, deps };
    }
    return this.slots[index].value as T;
  }

  useEffect(effect: () => void | (() => void), deps?: readonly unknown[]): void {
    const index = this.cursor++;
    const previous = this.slots[index];
    if (!previous || !sameDeps(previous.deps as readonly unknown[] | undefined, deps)) {
      this.pending.push({ index, effect });
      this.slots[index] = { kind: 'effect', deps, cleanup: previous?.cleanup };
    }
  }

  runEffects(): void {
    const pending = this.pending.splice(0);
    for (const entry of pending) {
      const slot = this.slots[entry.index];
      const cleanup = slot.cleanup;
      if (typeof cleanup === 'function') (cleanup as () => void)();
      slot.cleanup = entry.effect();
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
  allElements(element.props.children, output);
  return output;
}

function findElement(node: unknown, predicate: (element: ElementNode) => boolean): ElementNode {
  const found = allElements(node).find(predicate);
  if (!found) throw new Error('interaction element not found');
  return found;
}

function treeText(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(treeText).join('');
  if (!node || typeof node !== 'object' || !('props' in node)) return '';
  return treeText((node as ElementNode).props.children);
}

async function flushAsync(): Promise<void> {
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((onResolve) => {
    resolve = onResolve;
  });
  return { promise, resolve };
}

async function interactiveWorkspaceModule(harnessRef: { current: HookHarness }) {
  vi.resetModules();
  vi.doMock('react', () => ({
    ...ReactRuntime,
    useState: <T,>(initial: T | (() => T)) => harnessRef.current.useState(initial),
    useRef: <T,>(initial: T) => harnessRef.current.useRef(initial),
    useCallback: <T extends (...args: never[]) => unknown>(callback: T, deps: readonly unknown[]) => harnessRef.current.useCallback(callback, deps),
    useEffect: (effect: () => void | (() => void), deps?: readonly unknown[]) => harnessRef.current.useEffect(effect, deps),
  }));
  return import('./_gme-audit-workspace');
}

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    values,
    storage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    },
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

  it('keeps restored geometry on the initial media load but clears it before timer refresh', () => {
    const tracker = { hasLoadedSource: false };
    const present = {
      verdict: 'gecko_present' as const,
      representative_sec: 8,
      bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
    };
    expect(beginAuditMediaRequest(tracker, present)).toEqual({ draft: present, notice: null });
    markAuditMediaLoaded(tracker);
    expect(beginAuditMediaRequest(tracker, present)).toEqual({
      draft: { verdict: 'gecko_present', representative_sec: null, bbox: null },
      notice: '영상을 새로 불러왔어. 대표 시점과 bbox를 다시 선택해줘.',
    });
  });

  it('clears existing geometry before an error retry but stays silent when no geometry exists', () => {
    const tracker = { hasLoadedSource: true };
    const present = {
      verdict: 'gecko_present' as const,
      representative_sec: 3,
      bbox: { x: 0.2, y: 0.2, width: 0.2, height: 0.2 },
    };
    expect(beginAuditMediaRequest(tracker, present).draft).toEqual({
      verdict: 'gecko_present', representative_sec: null, bbox: null,
    });
    expect(beginAuditMediaRequest(tracker, { verdict: 'gecko_absent', representative_sec: null, bbox: null })).toEqual({
      draft: { verdict: 'gecko_absent', representative_sec: null, bbox: null },
      notice: null,
    });
  });
});

describe('GME audit client interactions without a DOM dependency', () => {
  it('restores the item draft, captures actual video time, clears geometry on error/timer refresh, submits, and navigates', async () => {
    vi.useFakeTimers();
    const { values, storage } = memoryStorage();
    vi.stubGlobal('window', {
      sessionStorage: storage,
      setTimeout,
      clearTimeout,
    });
    const itemId = '11111111-1111-4111-8111-111111111111';
    const nextId = '22222222-2222-4222-8222-222222222222';
    writeAuditDraft(storage, itemId, {
      verdict: 'gecko_present',
      representative_sec: 2,
      bbox: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
    });
    clientMocks.replace.mockReset();
    clientMocks.getAuditItem.mockReset().mockResolvedValue(publicItem({ item_id: itemId }));
    const errorRefresh = deferred<{ url: string; expires_in: number }>();
    clientMocks.getAuditMedia.mockReset()
      .mockResolvedValueOnce({ url: 'https://media.example/one', expires_in: 10 })
      .mockImplementationOnce(() => errorRefresh.promise)
      .mockResolvedValue({ url: 'https://media.example/timer', expires_in: 10 });
    clientMocks.getAuditQueue.mockReset().mockResolvedValue({
      completed: 1,
      total: 2,
      items: [
        { item_id: itemId, ordinal: 1, captured_at: 'x', duration_sec: 60, media_ready: true, submitted: true },
        { item_id: nextId, ordinal: 2, captured_at: 'x', duration_sec: 60, media_ready: true, submitted: false },
      ],
    });
    clientMocks.submitAudit.mockReset().mockResolvedValue({ status: 'submitted' });
    clientMocks.correctAudit.mockReset();
    const harnessRef = { current: new HookHarness() };

    try {
      const { default: InteractiveWorkspace } = await interactiveWorkspaceModule(harnessRef);
      const render = () => harnessRef.current.render(() => InteractiveWorkspace({ itemId }));
      let tree = render();
      harnessRef.current.runEffects();
      await flushAsync();
      tree = render();
      harnessRef.current.runEffects();

      expect(findElement(tree, (element) => element.type === 'input' && element.props.value === 'gecko_present').props.checked).toBe(true);
      expect(treeText(tree)).toContain('2.00초를 선택했어.');
      expect(findElement(tree, (element) => element.props.enabled === true && 'onChange' in element.props).props.value).toEqual(
        { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
      );
      const player = findElement(tree, (element) => typeof element.props.src === 'string' && 'videoRef' in element.props);
      (player.props.videoRef as { current: unknown }).current = { currentTime: 12.34 };
      const capture = findElement(tree, (element) => element.props.children === '현재 재생 위치를 대표 시점으로 사용');
      (capture.props.onClick as () => void)();
      const editor = findElement(tree, (element) => element.props.enabled === true && 'onChange' in element.props);
      (editor.props.onChange as (box: unknown) => void)({ x: 0.2, y: 0.2, width: 0.3, height: 0.3 });
      tree = render();
      expect(treeText(tree)).toContain('12.34초를 선택했어.');

      const erroringPlayer = findElement(tree, (element) => typeof element.props.src === 'string' && 'onError' in element.props);
      (erroringPlayer.props.onError as () => void)();
      // 이전 tree의 handler를 직접 호출해도 pending guard가 capture/bbox/save를 모두 막아야 한다.
      (player.props.videoRef as { current: unknown }).current = { currentTime: 55 };
      (capture.props.onClick as () => void)();
      (editor.props.onChange as (box: unknown) => void)({ x: 0.4, y: 0.4, width: 0.2, height: 0.2 });
      (findElement(tree, (element) => element.props.children === '저장').props.onClick as () => void)();
      await flushAsync();
      expect(clientMocks.submitAudit).not.toHaveBeenCalled();
      tree = render();
      harnessRef.current.runEffects();
      expect(treeText(tree)).toContain('영상을 새로 불러오는 중');
      expect(findElement(tree, (element) => element.props.children === '현재 재생 위치를 대표 시점으로 사용').props.disabled).toBe(true);
      expect(findElement(tree, (element) => element.props.children === '저장').props.disabled).toBe(true);
      expect(allElements(tree).some((element) => typeof element.props.src === 'string' && 'videoRef' in element.props)).toBe(false);
      expect(treeText(tree)).toContain('대표 시점과 bbox를 다시 선택해줘.');
      expect(treeText(tree)).toContain('대표 시점을 아직 선택하지 않았어.');

      // async pending 상태에서 재렌더된 저장 handler도 fail-closed여야 한다.
      (findElement(tree, (element) => element.props.children === '저장').props.onClick as () => void)();
      await flushAsync();
      expect(clientMocks.submitAudit).not.toHaveBeenCalled();

      errorRefresh.resolve({ url: 'https://media.example/refreshed', expires_in: 10 });
      await flushAsync();
      tree = render();
      harnessRef.current.runEffects();
      expect(findElement(tree, (element) => element.props.src === 'https://media.example/refreshed').props.src).toBe('https://media.example/refreshed');
      expect(findElement(tree, (element) => element.props.enabled === true && 'onChange' in element.props).props.value).toBeNull();

      const refreshedPlayer = findElement(tree, (element) => typeof element.props.src === 'string' && 'videoRef' in element.props);
      (refreshedPlayer.props.videoRef as { current: unknown }).current = { currentTime: 7.5 };
      (findElement(tree, (element) => element.props.children === '현재 재생 위치를 대표 시점으로 사용').props.onClick as () => void)();
      (findElement(tree, (element) => element.props.enabled === true && 'onChange' in element.props).props.onChange as (box: unknown) => void)(
        { x: 0.3, y: 0.3, width: 0.2, height: 0.2 },
      );
      tree = render();
      harnessRef.current.runEffects();
      expect(treeText(tree)).not.toContain('대표 시점과 bbox를 다시 선택해줘.');
      vi.advanceTimersByTime(5_000);
      await flushAsync();
      tree = render();
      expect(treeText(tree)).toContain('대표 시점을 아직 선택하지 않았어.');
      expect(findElement(tree, (element) => element.props.enabled === true && 'onChange' in element.props).props.value).toBeNull();

      (findElement(tree, (element) => element.type === 'input' && element.props.value === 'gecko_absent').props.onChange as () => void)();
      tree = render();
      harnessRef.current.runEffects();
      (findElement(tree, (element) => element.props.children === '저장').props.onClick as () => void)();
      await flushAsync();
      expect(clientMocks.submitAudit).toHaveBeenCalledWith(itemId, {
        verdict: 'gecko_absent', representative_sec: null, bbox: null,
      });
      expect(values.has(auditDraftKey(itemId))).toBe(false);
      vi.advanceTimersByTime(650);
      expect(clientMocks.replace).toHaveBeenCalledWith(`/labeling/gme-audit/${nextId}`);
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
      vi.unstubAllGlobals();
      vi.doUnmock('react');
      vi.resetModules();
    }
  });

  it('applies only the newest overlapping media response and never lets a stale response clear new geometry', async () => {
    vi.useFakeTimers();
    const { storage } = memoryStorage();
    vi.stubGlobal('window', { sessionStorage: storage, setTimeout, clearTimeout });
    const itemId = '44444444-4444-4444-8444-444444444444';
    const timerRefresh = deferred<{ url: string; expires_in: number }>();
    const errorRefresh = deferred<{ url: string; expires_in: number }>();
    clientMocks.getAuditItem.mockReset().mockResolvedValue(publicItem({ item_id: itemId }));
    clientMocks.getAuditMedia.mockReset()
      .mockResolvedValueOnce({ url: 'https://media.example/initial', expires_in: 10 })
      .mockImplementationOnce(() => timerRefresh.promise)
      .mockImplementationOnce(() => errorRefresh.promise);
    clientMocks.submitAudit.mockReset();
    const harnessRef = { current: new HookHarness() };

    try {
      const { default: InteractiveWorkspace } = await interactiveWorkspaceModule(harnessRef);
      const render = () => harnessRef.current.render(() => InteractiveWorkspace({ itemId }));
      let tree = render();
      harnessRef.current.runEffects();
      await flushAsync();
      tree = render();
      harnessRef.current.runEffects();
      (findElement(tree, (element) => element.type === 'input' && element.props.value === 'gecko_present').props.onChange as () => void)();
      tree = render();
      harnessRef.current.runEffects();
      const oldPlayer = findElement(tree, (element) => element.props.src === 'https://media.example/initial');

      vi.advanceTimersByTime(5_000);
      await flushAsync();
      (oldPlayer.props.onError as () => void)();
      await flushAsync();
      expect(clientMocks.getAuditMedia).toHaveBeenCalledTimes(3);

      errorRefresh.resolve({ url: 'https://media.example/newest', expires_in: 10 });
      await flushAsync();
      tree = render();
      harnessRef.current.runEffects();
      const newestPlayer = findElement(tree, (element) => element.props.src === 'https://media.example/newest');
      (newestPlayer.props.videoRef as { current: unknown }).current = { currentTime: 9 };
      (findElement(tree, (element) => element.props.children === '현재 재생 위치를 대표 시점으로 사용').props.onClick as () => void)();
      (findElement(tree, (element) => element.props.enabled === true && 'onChange' in element.props).props.onChange as (box: unknown) => void)(
        { x: 0.2, y: 0.2, width: 0.2, height: 0.2 },
      );
      tree = render();
      expect(treeText(tree)).toContain('9.00초를 선택했어.');
      expect(treeText(tree)).not.toContain('대표 시점과 bbox를 다시 선택해줘.');

      timerRefresh.resolve({ url: 'https://media.example/stale', expires_in: 10 });
      await flushAsync();
      tree = render();
      expect(findElement(tree, (element) => element.props.src === 'https://media.example/newest').props.src).toBe('https://media.example/newest');
      expect(treeText(tree)).toContain('9.00초를 선택했어.');
      expect(findElement(tree, (element) => element.props.enabled === true && 'onChange' in element.props).props.value).toEqual(
        { x: 0.2, y: 0.2, width: 0.2, height: 0.2 },
      );
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
      vi.unstubAllGlobals();
      vi.doUnmock('react');
      vi.resetModules();
    }
  });

  it('sends correction revision and turns stale 409 into a reload prompt without initial submit', async () => {
    vi.useFakeTimers();
    const { storage } = memoryStorage();
    vi.stubGlobal('window', { sessionStorage: storage, setTimeout, clearTimeout });
    const itemId = '33333333-3333-4333-8333-333333333333';
    const correctionItem = publicItem({
      item_id: itemId,
      initial_verdict: 'gecko_absent',
      effective_verdict: 'gecko_absent',
      revision: 'opaque-r1',
    });
    const harnessRef = { current: new HookHarness() };
    clientMocks.replace.mockReset();
    clientMocks.submitAudit.mockReset();
    clientMocks.getAuditQueue.mockReset().mockResolvedValue({ items: [], completed: 1, total: 1 });
    clientMocks.correctAudit.mockReset().mockResolvedValue({ status: 'corrected' });

    try {
      const { default: InteractiveWorkspace } = await interactiveWorkspaceModule(harnessRef);
      const { ApiError: InteractiveApiError } = await import('@/lib/labelingApi');
      const render = () => harnessRef.current.render(() => InteractiveWorkspace({ itemId, initialItem: correctionItem }));
      let tree = render();
      (findElement(tree, (element) => element.type === 'textarea').props.onChange as (event: { target: { value: string } }) => void)(
        { target: { value: '영상을 다시 확인함' } },
      );
      tree = render();
      (findElement(tree, (element) => element.props.children === '정정 저장').props.onClick as () => void)();
      await flushAsync();
      expect(clientMocks.correctAudit).toHaveBeenCalledWith(itemId, {
        verdict: 'gecko_absent',
        representative_sec: null,
        bbox: null,
        reason: '영상을 다시 확인함',
        revision: 'opaque-r1',
      });
      expect(clientMocks.submitAudit).not.toHaveBeenCalled();

      vi.clearAllTimers();
      harnessRef.current = new HookHarness();
      clientMocks.correctAudit.mockReset().mockRejectedValue(new InteractiveApiError(409, 'raw stale'));
      tree = render();
      (findElement(tree, (element) => element.type === 'textarea').props.onChange as (event: { target: { value: string } }) => void)(
        { target: { value: '다시 확인' } },
      );
      tree = render();
      (findElement(tree, (element) => element.props.children === '정정 저장').props.onClick as () => void)();
      await flushAsync();
      tree = render();
      expect(treeText(tree)).toContain('최신 판정을 다시 불러와 확인해줘.');
      expect(treeText(tree)).toContain('최신 판정 다시 불러오기');
      expect(clientMocks.submitAudit).not.toHaveBeenCalled();
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
      vi.unstubAllGlobals();
      vi.doUnmock('react');
      vi.resetModules();
    }
  });
});
