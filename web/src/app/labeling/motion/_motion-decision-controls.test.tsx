// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import MotionDecisionControls from './_motion-decision-controls';

describe('MotionDecisionControls', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function renderControls(overrides: Record<string, unknown> = {}) {
    const props = {
      clipId: '11111111-1111-4111-8111-111111111111',
      state: 'label' as const,
      stateUpdatedAt: '2026-08-25T09:00:00.000Z',
      onDecided: vi.fn(),
      ...overrides,
    };
    act(() => root.render(<MotionDecisionControls {...props} />));
  }

  it('사람 판정이 시작된 영상에는 실패할 제외 동작을 보여주지 않는다', () => {
    renderControls({ labelingStarted: true });

    const buttons = Array.from(container.querySelectorAll('button')).map((button) => button.textContent);
    expect(buttons).not.toContain('제외');
    expect(container.textContent).toContain('사람 판정이 저장되어 제외할 수 없어');
  });

  it('게코 없음 판정 완료 뒤에는 제외 대신 다음 영상으로 이어간다', () => {
    const onNext = vi.fn();
    renderControls({
      labelingStarted: true,
      absentGtSaved: true,
      canMoveNext: true,
      onNext,
    });

    expect(container.textContent).toContain('게코 없음 판정 저장 완료');
    expect(container.textContent).toContain('제외할 필요 없어');
    const buttons = Array.from(container.querySelectorAll('button'));
    expect(buttons.map((button) => button.textContent)).toEqual(['다음 미분류 영상']);

    act(() => buttons[0].click());
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it('게코 없음 판정 뒤 AI 검수가 남아 있으면 다음 이동 대신 검수 완료를 안내한다', () => {
    renderControls({
      labelingStarted: true,
      absentGtSaved: true,
      canMoveNext: false,
      onNext: vi.fn(),
    });

    expect(container.textContent).toContain('아래 AI 판정 확인을 마쳐줘');
    expect(Array.from(container.querySelectorAll('button')).map((button) => button.textContent))
      .not.toContain('다음 미분류 영상');
  });

  it('게코 없음 판정 완료 뒤 다음 영상 조회가 실패하면 재시도 안내를 보여준다', () => {
    const onNext = vi.fn();
    renderControls({
      labelingStarted: true,
      absentGtSaved: true,
      canMoveNext: true,
      nextFailed: true,
      onNext,
    });

    expect(container.textContent).toContain('다음 영상을 찾지 못했어');
    const retry = Array.from(container.querySelectorAll('button'))
      .find((button) => button.textContent === '다음 영상 다시 찾기');
    expect(retry).toBeDefined();
    act(() => retry!.click());
    expect(onNext).toHaveBeenCalledTimes(1);
  });
});
