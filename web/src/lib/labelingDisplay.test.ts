import { describe, expect, it } from 'vitest';

import {
  ACTION_LABELS,
  HIGHLIGHT_LABELS,
  VERDICT_LABELS,
  describeSegment,
  dimensionLabel,
  formatDimensionValue,
  formatSeconds,
  targetPromptFor,
} from './labelingDisplay';

describe('formatSeconds (§5.2)', () => {
  it('rounds to one decimal place', () => {
    expect(formatSeconds(31.7999)).toBe('31.8');
    expect(formatSeconds(0)).toBe('0.0');
    expect(formatSeconds(13)).toBe('13.0');
  });

  it('is defensive against non-finite input', () => {
    expect(formatSeconds(NaN)).toBe('0.0');
  });
});

describe('describeSegment (§4.5)', () => {
  it('renders a segment as a Korean sentence with one-decimal times', () => {
    expect(describeSegment({ action: 'licking', start_sec: 13.0, end_sec: 31.7999 })).toBe(
      '핥기 13.0초~31.8초',
    );
  });
});

describe('formatDimensionValue (§4.5 — no raw enum/JSON)', () => {
  it('maps scalar enums to Korean', () => {
    expect(formatDimensionValue('primary_action', 'hand_feeding')).toBe('사람이 직접 먹임');
    expect(formatDimensionValue('primary_action', 'moving')).toBe('일반 이동');
    expect(formatDimensionValue('highlight_recommendation', 'include')).toBe('포함');
    expect(formatDimensionValue('vlm_verdict', 'partially_correct')).toBe('일부만 맞음');
    expect(formatDimensionValue('human_confidence', 'likely')).toBe('아마 맞음');
  });

  it('joins arrays with Korean labels', () => {
    expect(formatDimensionValue('observed_actions', ['moving', 'wheel_interaction'])).toBe(
      '위치 이동, 쳇바퀴 상호작용',
    );
    expect(formatDimensionValue('interaction_types', ['ride', 'rotate'])).toBe('올라타기, 회전시키기');
  });

  it('renders segment arrays as sentences, never JSON', () => {
    const out = formatDimensionValue('segments', [
      { action: 'licking', start_sec: 13, end_sec: 31.7999 },
    ]);
    expect(out).toBe('핥기 13.0초~31.8초');
    expect(out).not.toContain('{');
    expect(out).not.toContain('start_sec');
  });

  it('shows none/null/empty as 없음', () => {
    expect(formatDimensionValue('target', 'none')).toBe('대상 없음');
    expect(formatDimensionValue('note', null)).toBe('없음');
    expect(formatDimensionValue('observed_actions', [])).toBe('없음');
    expect(formatDimensionValue('enrichment_object', 'none')).toBe('없음');
  });

  it('never leaks a raw wheel/target/enrichment key', () => {
    const rendered = [
      formatDimensionValue('observed_actions', ['wheel_interaction']),
      formatDimensionValue('enrichment_object', 'wheel'),
      formatDimensionValue('target', 'water_bowl'),
    ].join(' ');
    expect(rendered).not.toMatch(/wheel|enrichment|water_bowl|_interaction/);
  });
});

describe('targetPromptFor (§5.3 dynamic question)', () => {
  it('asks a different question per representative action', () => {
    expect(targetPromptFor('drinking').title).toBe('무엇을 핥거나 마셨나?');
    expect(targetPromptFor('hand_feeding').title).toBe('무엇으로 직접 먹였나?');
    expect(targetPromptFor('moving').title).toBe('이 행동은 무엇을 향했나?');
  });
});

describe('label maps stay in Korean', () => {
  it('has no leftover english labels in the highlight/verdict/action maps', () => {
    for (const map of [HIGHLIGHT_LABELS, VERDICT_LABELS, ACTION_LABELS]) {
      for (const label of Object.values(map)) {
        expect(label).toMatch(/[가-힣]/);
      }
    }
  });

  it('renders dimension titles without internal english terms', () => {
    expect(dimensionLabel('highlight_recommendation')).toBe('하이라이트 여부');
    expect(dimensionLabel('primary_action')).toBe('대표 행동');
  });
});
