import { describe, expect, it } from 'vitest';

import {
  ACTION_LABELS,
  CONTEXT_TAGS_HELP,
  CONTEXT_TAGS_NONE_LABEL,
  CONTEXT_TAGS_TITLE,
  HIGHLIGHT_LABELS,
  PRIMARY_HELP,
  TARGET_LABELS,
  TARGET_PROMPT_COMMON_NOTE,
  TARGET_TOOL_OBJECT_NOTE,
  UNKNOWN_LABEL,
  VERDICT_LABELS,
  describeSegment,
  dimensionLabel,
  formatActionLabel,
  formatActivityIntensity,
  formatDimensionValue,
  highlightSummaryClause,
  formatSeconds,
  formatTimeRange,
  formatVideoEndLabel,
  isVideoEnd,
  isVideoStart,
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

describe('formatTimeRange / isVideoStart / isVideoEnd (하드닝 §2)', () => {
  const DUR = 31.7999;

  it('video-end 판정은 반올림 표시값이 아니라 실제 duration 기준', () => {
    expect(isVideoEnd(31.7999, DUR)).toBe(true);
    expect(isVideoEnd(31.8, DUR)).toBe(true); // legacy 반올림 저장값도 끝으로 인정
    expect(isVideoEnd(24, DUR)).toBe(false);
    expect(isVideoEnd(31.7999, null)).toBe(false); // duration 모르면 끝 판정 불가
    expect(isVideoStart(0)).toBe(true);
    expect(isVideoStart(13)).toBe(false);
  });

  it('범위 밖 값은 시작/끝으로 보지 않는다 (경계 하드닝)', () => {
    // 음수 시작은 영상 시작 아님.
    expect(isVideoStart(-0.1)).toBe(false);
    // duration 을 크게 초과한 끝은 영상 끝 아님(상한 ±ε).
    expect(isVideoEnd(32.8, 31.7999)).toBe(false);
    // 31.7999·legacy 31.8 은 계속 영상 끝으로 인정.
    expect(isVideoEnd(31.8, 31.7999)).toBe(true);
    expect(isVideoEnd(31.7999, 31.7999)).toBe(true);
    // 음수 duration 은 끝 판정 불가.
    expect(isVideoEnd(0, -1)).toBe(false);
  });

  it('start=0·end=끝 → 영상 전체', () => {
    expect(formatTimeRange(0, 31.7999, DUR)).toBe('영상 전체');
  });
  it('start=0 → 영상 시작부터 …까지', () => {
    expect(formatTimeRange(0, 13, DUR)).toBe('영상 시작부터 13.0초까지');
  });
  it('end=끝 → …부터 영상 끝까지', () => {
    expect(formatTimeRange(13, 31.7999, DUR)).toBe('13.0초부터 영상 끝까지');
  });
  it('일반 구간 → 양쪽 소수점 첫째 자리', () => {
    expect(formatTimeRange(13, 24, DUR)).toBe('13.0초부터 24.0초까지');
  });
  it('duration 을 모르면 명시적 시간으로 폴백', () => {
    expect(formatTimeRange(13, 31.7999)).toBe('13.0초부터 31.8초까지');
  });
});

describe('describeSegment (하드닝 §2 — 라벨·구간 공유 formatter)', () => {
  const DUR = 31.7999;
  it('핥기 · 영상 전체 (0~duration)', () => {
    expect(describeSegment({ action: 'licking', start_sec: 0, end_sec: 31.7999 }, DUR)).toBe(
      '핥기 · 영상 전체',
    );
  });
  it('핥기 · 13.0초부터 영상 끝까지 (13~duration)', () => {
    expect(describeSegment({ action: 'licking', start_sec: 13, end_sec: 31.7999 }, DUR)).toBe(
      '핥기 · 13.0초부터 영상 끝까지',
    );
  });
  it('핥기 · 영상 시작부터 13.0초까지 (0~13)', () => {
    expect(describeSegment({ action: 'licking', start_sec: 0, end_sec: 13 }, DUR)).toBe(
      '핥기 · 영상 시작부터 13.0초까지',
    );
  });
  it('일반 이동 · 영상 시작부터 10.0초까지', () => {
    expect(describeSegment({ action: 'moving', start_sec: 0, end_sec: 10 }, DUR)).toBe(
      '위치 이동 · 영상 시작부터 10.0초까지',
    );
  });
  it('duration 없이도 안전하게 명시 시간으로', () => {
    expect(describeSegment({ action: 'licking', start_sec: 13, end_sec: 31.7999 })).toBe(
      '핥기 · 13.0초부터 31.8초까지',
    );
  });
  it('영상 끝 입력 라벨은 raw 31.7999 대신 반올림 표시', () => {
    expect(formatVideoEndLabel(31.7999)).toBe('영상 끝 (31.8초)');
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
    const out = formatDimensionValue(
      'segments',
      [{ action: 'licking', start_sec: 13, end_sec: 24 }],
      31.7999,
    );
    expect(out).toBe('핥기 · 13.0초부터 24.0초까지');
    expect(out).not.toContain('{');
    expect(out).not.toContain('start_sec');
  });

  it('segments 해설도 라벨링 화면과 같은 영상 전체/끝 formatter 를 쓴다 (하드닝 §2)', () => {
    expect(
      formatDimensionValue('segments', [{ action: 'licking', start_sec: 0, end_sec: 31.7999 }], 31.7999),
    ).toBe('핥기 · 영상 전체');
    const out = formatDimensionValue(
      'segments',
      [{ action: 'licking', start_sec: 13, end_sec: 31.7999 }],
      31.7999,
    );
    expect(out).toBe('핥기 · 13.0초부터 영상 끝까지');
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

  it('사람 급여 질문 설명은 급여 도구 용어로 맞춘다 (§6.3)', () => {
    expect(targetPromptFor('hand_feeding').description).toBe(
      '손을 사용해 직접 먹였는지, 급여 도구를 사용해 먹였는지 골라.',
    );
  });
});

describe('사람 판정 화면 명칭 (설계 §4.2 · §11.1)', () => {
  it('대표 행동 명칭이 운영 용어로 바뀐다', () => {
    expect(ACTION_LABELS.basking).toBe('휴식');
    expect(ACTION_LABELS.eating_paste).toBe('슈퍼푸드 자율급여');
    expect(ACTION_LABELS.eating_prey).toBe('곤충 사냥');
  });

  it('급여 도구·일반 사물을 사용 목적과 예시로 구분한다', () => {
    for (const token of ['급여 도구', '숟가락', '주사기', '핀셋']) {
      expect(TARGET_LABELS.tool).toContain(token);
    }
    expect(TARGET_LABELS.object).toContain('일반 사물');
    // 사육장 사물 예시가 하나 이상 보인다.
    expect(TARGET_LABELS.object).toMatch(/장식물|은신처|나뭇가지/);
  });
});

describe('휴식·일반 이동 도움말 (설계 §6.2)', () => {
  it('휴식은 그림자·조명 변화만 있는 정지 장면을 정의한다', () => {
    expect(PRIMARY_HELP.basking).toContain('그림자나 조명만 변하고');
    expect(PRIMARY_HELP.basking).toContain('휴식');
  });

  it('일반 이동은 실제 위치·자세 변화를 요구하고 휴식과 대비시킨다', () => {
    expect(PRIMARY_HELP.moving).toContain('실제로 위치를 옮기거나');
    expect(PRIMARY_HELP.moving).toContain('그림자나 조명만 변하고');
  });

  it('슈퍼푸드 자율급여·곤충 사냥 도움말이 운영 용어를 쓴다', () => {
    expect(PRIMARY_HELP.eating_paste).toContain('슈퍼푸드');
    expect(PRIMARY_HELP.eating_prey).toContain('곤충');
  });

  it('사람 급여 도움말도 급여 도구 용어로 통일한다', () => {
    expect(PRIMARY_HELP.hand_feeding).toContain('급여 도구');
  });
});

describe('촬영 환경 필수 문구 (설계 §6.1)', () => {
  it('제목이 필수 확인 항목임을 드러낸다', () => {
    expect(CONTEXT_TAGS_TITLE).toBe('촬영 환경 (필수)');
  });

  it('안내문이 해당 없음 직접 선택을 요구한다', () => {
    expect(CONTEXT_TAGS_HELP).toBe(
      '영상에 해당하는 환경을 모두 골라줘. 해당하는 항목이 없으면 ‘해당 없음’을 선택해.',
    );
    expect(CONTEXT_TAGS_NONE_LABEL).toBe('해당 없음');
  });

  it('사물/급여 도구 경계 안내문이 두 범주를 다시 보여준다 (§6.3)', () => {
    expect(TARGET_TOOL_OBJECT_NOTE).toContain('급여 도구');
    expect(TARGET_TOOL_OBJECT_NOTE).toContain('일반 사물');
    // 화면 문구에 backtick 을 노출하지 않는다(하드닝 §7).
    expect(TARGET_TOOL_OBJECT_NOTE).not.toContain('`');
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

describe('알 수 없는 값은 raw 노출 대신 확인 필요 (하드닝 §7)', () => {
  it('미지 enum action/visibility/verdict → 확인 필요', () => {
    expect(formatDimensionValue('primary_action', 'weird_internal_class')).toBe(UNKNOWN_LABEL);
    expect(formatDimensionValue('visibility', 'zzz')).toBe(UNKNOWN_LABEL);
    expect(formatDimensionValue('vlm_verdict', 'bogus')).toBe(UNKNOWN_LABEL);
  });

  it('미지 배열 항목 → 항목별 확인 필요', () => {
    expect(formatDimensionValue('observed_actions', ['licking', 'nope'])).toBe(`핥기, ${UNKNOWN_LABEL}`);
  });

  it('미지 dimension key → 확인 필요, raw key 노출 안 함', () => {
    expect(dimensionLabel('some_internal_key')).toBe(UNKNOWN_LABEL);
    expect(formatDimensionValue('some_internal_key', 'raw_english_value')).toBe(UNKNOWN_LABEL);
  });

  it('formatActionLabel 은 VLM 미지 action 을 확인 필요로', () => {
    expect(formatActionLabel('shedding')).toBe('탈피');
    expect(formatActionLabel('mystery')).toBe(UNKNOWN_LABEL);
    expect(formatActionLabel(undefined)).toBe(UNKNOWN_LABEL);
  });
});

describe('legacy activity_intensity 한국어 표시 (하드닝 §1)', () => {
  it('low/medium/high 를 한국어로, 미지값은 확인 필요', () => {
    expect(formatActivityIntensity('low')).toBe('낮음');
    expect(formatActivityIntensity('high')).toBe('높음');
    expect(formatActivityIntensity('weird')).toBe(UNKNOWN_LABEL);
  });
});

describe('highlightSummaryClause — GtSummary 하이라이트/활동강도 (하드닝 §1)', () => {
  it('신규 GT: 유효 highlight → 하이라이트 문구', () => {
    expect(highlightSummaryClause({ highlight_recommendation: 'include', activity_intensity: null })).toBe(
      '하이라이트 포함',
    );
    expect(highlightSummaryClause({ highlight_recommendation: 'exclude', activity_intensity: null })).toBe(
      '하이라이트 제외',
    );
  });

  it('legacy GT: highlight 없음 + activity 있음 → 활동 강도 한국어', () => {
    // v1 GT 는 highlight_recommendation 키 자체가 없다.
    expect(highlightSummaryClause({ activity_intensity: 'high' })).toBe('활동 강도 높음');
    expect(highlightSummaryClause({ activity_intensity: 'low' })).toBe('활동 강도 낮음');
  });

  it('legacy GT: 둘 다 없으면 null(항목 생략) — undefined 렌더 안 함', () => {
    expect(highlightSummaryClause({ activity_intensity: null })).toBeNull();
    expect(highlightSummaryClause({})).toBeNull();
    // 어떤 반환값도 문자열 'undefined' 를 포함하지 않는다.
    const clause = highlightSummaryClause({ highlight_recommendation: undefined, activity_intensity: undefined });
    expect(clause).toBeNull();
  });
});

describe('화면 문구에 backtick·과대추론 없음 (하드닝 §7)', () => {
  it('공통 보조 설명에 backtick 이 없다', () => {
    expect(TARGET_PROMPT_COMMON_NOTE).not.toContain('`');
    expect(TARGET_PROMPT_COMMON_NOTE).toContain('놀이 행동 근거');
  });

  it('drinking 설명은 과대 추론(물 안 보여도 단정) 문구를 쓰지 않는다', () => {
    expect(PRIMARY_HELP.drinking).toBe('물·물그릇·젖은 표면 등에 입이 실제로 닿아 반복해서 핥는 장면.');
    expect(PRIMARY_HELP.drinking).not.toContain('안 보여도');
  });
});
