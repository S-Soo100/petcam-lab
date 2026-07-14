import { describe, expect, it } from 'vitest';

import {
  BLIND_QUEUE_CLIP_COLUMNS,
  GroundTruthValidationError,
  TARGETS,
  allowedTargetsFor,
  applyVisibilityChange,
  changedGroundTruthFields,
  clipDownloadFilename,
  collectGroundTruthIssues,
  firstIssueField,
  formatClipCapturedAt,
  isValidGroundTruthShape,
  isValidHighlight,
  isValidSelectedFields,
  isValidVlmReviewShape,
  nextStage,
  revealPrediction,
  thumbnailKeyForClip,
  validateGroundTruth,
  validateVlmReview,
  type GroundTruthField,
  type GroundTruthInput,
} from './labelingV2';

describe('clip header', () => {
  it('formats the capture time in Korea time with rounded duration', () => {
    expect(formatClipCapturedAt('2026-07-07T20:11:29Z', 31.9184)).toBe(
      '촬영 · 2026년 7월 8일 (수) 오전 5:11:29 · 32초',
    );
  });

  it('builds a stable original MP4 filename in Korea time', () => {
    expect(
      clipDownloadFilename(
        '2026-07-07T20:11:29Z',
        '29a74166-1024-4bdd-a497-b1133a86549b',
      ),
    ).toBe('petcam_2026-07-08_051129_29a74166.mp4');
  });
});

describe('blind queue projection', () => {
  it('matches the deployed camera_clips schema without ended_at', () => {
    const columns = BLIND_QUEUE_CLIP_COLUMNS.split(',');
    expect(columns).toContain('started_at');
    expect(columns).toContain('duration_sec');
    expect(columns).not.toContain('ended_at');
  });
});

function validGt(overrides: Partial<GroundTruthInput> = {}): GroundTruthInput {
  return {
    visibility: 'visible',
    primary_action: 'moving',
    observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: 0, end_sec: 4 }],
    target: 'none',
    human_confidence: 'certain',
    context_tags: ['ir'],
    // 신규 계약(§6.3): activity_intensity 는 null(legacy read 전용), highlight 를 직접 고른다.
    activity_intensity: null,
    highlight_recommendation: 'include',
    enrichment_object: 'none',
    interaction_types: [],
    note: null,
    ...overrides,
  };
}

function codes(input: GroundTruthInput, duration = 30, selected?: Set<GroundTruthField>) {
  return collectGroundTruthIssues(input, duration, selected).map((issue) => issue.code);
}

describe('collectGroundTruthIssues', () => {
  it('returns no issues for ordinary moving without enrichment evidence', () => {
    expect(collectGroundTruthIssues(validGt(), 30)).toEqual([]);
  });

  it('flags missing explicit selection of visibility and primary action (client only)', () => {
    // 빈 explicitlySelected → 기본값이 정답처럼 보이지 않도록 두 필드를 강제.
    expect(codes(validGt(), 30, new Set())).toEqual(
      expect.arrayContaining(['visibility_not_selected', 'primary_action_not_selected']),
    );
    // server 는 explicitlySelected 를 넘기지 않으므로 해당 규칙을 강제하지 않는다.
    expect(codes(validGt(), 30)).not.toContain('visibility_not_selected');
  });

  it('honors explicit selection once required fields are chosen', () => {
    // §4.1: visibility·primary_action·highlight 에 더해 context_tags(촬영 환경)도 직접 선택 대상.
    expect(
      codes(
        validGt(),
        30,
        new Set<GroundTruthField>([
          'visibility',
          'primary_action',
          'highlight_recommendation',
          'context_tags',
        ]),
      ),
    ).toEqual([]);
  });

  it('requires an explicit 촬영 환경 confirmation on the client (§4.1)', () => {
    // 촬영 환경을 한 번도 조작하지 않으면(직접 선택 없음) client 에서 막힌다.
    const selected = new Set<GroundTruthField>([
      'visibility',
      'primary_action',
      'highlight_recommendation',
    ]);
    expect(codes(validGt(), 30, selected)).toContain('context_tags_not_selected');
    // server(값 기반, explicitlySelected 없음)는 이 규칙을 강제하지 않는다.
    expect(codes(validGt(), 30)).not.toContain('context_tags_not_selected');
  });

  it('accepts an explicitly confirmed empty 촬영 환경 (해당 없음) (§4.1)', () => {
    // 라벨러가 '해당 없음'을 직접 골라 빈 배열을 확정하면 통과한다.
    const selected = new Set<GroundTruthField>([
      'visibility',
      'primary_action',
      'highlight_recommendation',
      'context_tags',
    ]);
    expect(collectGroundTruthIssues(validGt({ context_tags: [] }), 30, selected)).toEqual([]);
  });

  it('requires an explicit highlight selection when the gecko is visible (§6.3)', () => {
    // highlight 를 안 고르면 client 에서 막힌다.
    expect(
      codes(validGt(), 30, new Set<GroundTruthField>(['visibility', 'primary_action'])),
    ).toContain('highlight_not_selected');
    // server(값 기반, explicitlySelected 없음)는 이 규칙을 강제하지 않는다.
    expect(codes(validGt(), 30)).not.toContain('highlight_not_selected');
  });

  it('enforces the absent → unseen normalization contract', () => {
    expect(codes(validGt({ visibility: 'absent', primary_action: 'moving' }))).toContain(
      'absent_requires_unseen',
    );
    const dirtyAbsent = validGt({
      visibility: 'absent',
      primary_action: 'unseen',
      observed_actions: ['moving'],
      segments: [{ action: 'moving', start_sec: 0, end_sec: 4 }],
      target: 'water',
      enrichment_object: 'wheel',
      interaction_types: ['ride'],
    });
    expect(codes(dirtyAbsent)).toEqual(
      expect.arrayContaining([
        'absent_no_observed',
        'absent_no_segments',
        'absent_target_none',
        'absent_enrichment_none',
        'absent_no_interaction',
      ]),
    );
  });

  it('accepts a fully normalized absent answer', () => {
    const absent = validGt({
      visibility: 'absent',
      primary_action: 'unseen',
      observed_actions: [],
      segments: [],
      target: 'none',
      context_tags: [],
      highlight_recommendation: 'exclude',
    });
    expect(collectGroundTruthIssues(absent, 30)).toEqual([]);
  });

  it('requires explicit 촬영 환경 confirmation even when absent (§4.1)', () => {
    const absent = validGt({
      visibility: 'absent',
      primary_action: 'unseen',
      observed_actions: [],
      segments: [],
      target: 'none',
      context_tags: [],
      highlight_recommendation: 'exclude',
    });
    // absent 정규화 값이라도 촬영 환경을 직접 확인하지 않으면 client 에서 막힌다(예외 없음).
    const selected = new Set<GroundTruthField>(['visibility', 'primary_action']);
    expect(codes(absent, 30, selected)).toContain('context_tags_not_selected');
  });

  it('accepts absent once 촬영 환경 is explicitly confirmed (§4.1)', () => {
    const absent = validGt({
      visibility: 'absent',
      primary_action: 'unseen',
      observed_actions: [],
      segments: [],
      target: 'none',
      context_tags: [],
      highlight_recommendation: 'exclude',
    });
    const selected = new Set<GroundTruthField>(['visibility', 'primary_action', 'context_tags']);
    expect(collectGroundTruthIssues(absent, 30, selected)).toEqual([]);
  });

  it('server keeps allowing absent + empty 촬영 환경 [] (§4.1·§8)', () => {
    const absent = validGt({
      visibility: 'absent',
      primary_action: 'unseen',
      observed_actions: [],
      segments: [],
      target: 'none',
      context_tags: [],
      highlight_recommendation: 'exclude',
    });
    // server(explicitlySelected 없음)는 빈 배열을 계속 허용한다.
    expect(collectGroundTruthIssues(absent, 30)).toEqual([]);
    expect(validateGroundTruth(absent, 30)).toEqual(absent);
  });

  it('normalizes highlight to exclude when absent (§6.3)', () => {
    const absentInclude = validGt({
      visibility: 'absent',
      primary_action: 'unseen',
      observed_actions: [],
      segments: [],
      target: 'none',
      context_tags: [],
      highlight_recommendation: 'include',
    });
    expect(codes(absentInclude)).toContain('absent_highlight_exclude');
  });

  it('rejects unseen when the gecko is visible', () => {
    expect(codes(validGt({ primary_action: 'unseen' }))).toContain('unseen_requires_absent');
  });

  it('requires at least one observed action when visible', () => {
    expect(codes(validGt({ observed_actions: [], segments: [] }))).toContain('observed_required');
  });

  it('requires exactly one segment per observed action', () => {
    // 누락: licking 에 구간 없음.
    expect(codes(validGt({ observed_actions: ['moving', 'licking'] }))).toContain('segment_missing');
    // 중복: 같은 action 구간 2개.
    expect(
      codes(
        validGt({
          segments: [
            { action: 'moving', start_sec: 0, end_sec: 4 },
            { action: 'moving', start_sec: 5, end_sec: 6 },
          ],
        }),
      ),
    ).toContain('segment_duplicate');
    // orphan: observed 에 없는 action 구간.
    expect(
      codes(
        validGt({
          segments: [
            { action: 'moving', start_sec: 0, end_sec: 4 },
            { action: 'licking', start_sec: 1, end_sec: 2 },
          ],
        }),
      ),
    ).toContain('segment_orphan');
  });

  it('rejects segments outside 0 <= start < end <= duration', () => {
    expect(codes(validGt({ segments: [{ action: 'moving', start_sec: 10, end_sec: 31 }] }))).toContain(
      'segment_range',
    );
    expect(codes(validGt({ segments: [{ action: 'moving', start_sec: 4, end_sec: 2 }] }))).toContain(
      'segment_range',
    );
  });

  it('requires object and interaction type for wheel/object interaction', () => {
    const input = validGt({
      observed_actions: ['moving', 'wheel_interaction'],
      segments: [
        { action: 'moving', start_sec: 0, end_sec: 4 },
        { action: 'wheel_interaction', start_sec: 1, end_sec: 3 },
      ],
    });
    expect(codes(input)).toEqual(
      expect.arrayContaining(['enrichment_object_required', 'interaction_type_required']),
    );
  });

  it('accepts objective wheel evidence without a playing action', () => {
    const input = validGt({
      observed_actions: ['moving', 'wheel_interaction'],
      segments: [
        { action: 'moving', start_sec: 0, end_sec: 4 },
        { action: 'wheel_interaction', start_sec: 1, end_sec: 3 },
      ],
      enrichment_object: 'wheel',
      interaction_types: ['ride', 'rotate'],
      activity_intensity: 'high',
    });
    expect(collectGroundTruthIssues(input, 30)).toEqual([]);
  });

  it('restricts drinking target to the water whitelist', () => {
    for (const target of ['water', 'water_bowl', 'glass', 'floor', 'uncertain'] as const) {
      expect(codes(validGt({ primary_action: 'drinking', target }))).not.toContain(
        'drinking_target_invalid',
      );
    }
    // wheel 은 drinking 의 target 이 아니다 → 차단.
    expect(codes(validGt({ primary_action: 'drinking', target: 'tool' }))).toContain(
      'drinking_target_invalid',
    );
    expect(codes(validGt({ primary_action: 'drinking', target: 'object' }))).toContain(
      'drinking_target_invalid',
    );
  });

  it('requires all three hand feeding grounds', () => {
    // 근거 전무: licking/prey 없음 + target tool 은 OK지만 human 태그 없음.
    const bare = validGt({
      primary_action: 'hand_feeding',
      observed_actions: ['moving'],
      segments: [{ action: 'moving', start_sec: 0, end_sec: 4 }],
      target: 'tool',
      context_tags: ['ir'],
    });
    expect(codes(bare)).toEqual(
      expect.arrayContaining(['hand_feeding_action', 'hand_feeding_context']),
    );
    // 잘못된 target.
    expect(
      codes(
        validGt({
          primary_action: 'hand_feeding',
          observed_actions: ['licking'],
          segments: [{ action: 'licking', start_sec: 0, end_sec: 4 }],
          target: 'water',
          context_tags: ['human'],
        }),
      ),
    ).toContain('hand_feeding_target');
    // 세 근거 모두 충족.
    const ok = validGt({
      primary_action: 'hand_feeding',
      observed_actions: ['licking'],
      segments: [{ action: 'licking', start_sec: 0, end_sec: 4 }],
      target: 'hand',
      context_tags: ['human'],
    });
    expect(collectGroundTruthIssues(ok, 30)).toEqual([]);
  });

  it('keeps hand_feeding_context even when 해당 없음 is explicitly chosen (§7.3)', () => {
    // hand_feeding 에서 '해당 없음'(빈 배열)을 직접 골라도 human 태그 의미 검증은 실패한다.
    const selected = new Set<GroundTruthField>([
      'visibility',
      'primary_action',
      'observed_actions',
      'segments',
      'target',
      'highlight_recommendation',
      'context_tags',
    ]);
    const hf = validGt({
      primary_action: 'hand_feeding',
      observed_actions: ['licking'],
      segments: [{ action: 'licking', start_sec: 0, end_sec: 4 }],
      target: 'hand',
      context_tags: [],
    });
    const c = codes(hf, 30, selected);
    expect(c).toContain('hand_feeding_context');
    // 촬영 환경은 직접 확정했으므로 미확인 오류는 나지 않는다.
    expect(c).not.toContain('context_tags_not_selected');
  });

  it('server keeps allowing an empty 촬영 환경 [] (§4.1)', () => {
    // 서버는 explicitlySelected 를 넘기지 않으므로 빈 배열을 계속 허용한다.
    expect(collectGroundTruthIssues(validGt({ context_tags: [] }), 30)).toEqual([]);
    expect(validateGroundTruth(validGt({ context_tags: [] }), 30)).toEqual(
      validGt({ context_tags: [] }),
    );
  });

  it('사람 급여 대상 오류 문구는 급여 도구 용어로 통일한다', () => {
    const issues = collectGroundTruthIssues(
      validGt({
        primary_action: 'hand_feeding',
        observed_actions: ['licking'],
        segments: [{ action: 'licking', start_sec: 0, end_sec: 4 }],
        target: 'water',
        context_tags: ['human'],
      }),
      30,
    );
    const msg = issues.find((issue) => issue.code === 'hand_feeding_target')?.message;
    expect(msg).toContain('급여 도구');
  });

  it('rejects playing as a direct primary action', () => {
    expect(
      codes(validGt({ primary_action: 'playing' as GroundTruthInput['primary_action'] })),
    ).toContain('playing_not_primary');
  });

  it('sorts issues top-to-bottom so the first is the highest field', () => {
    // primary_action(위) + target(아래) 동시 오류 → 첫 issue 는 primary_action.
    const input = validGt({
      primary_action: 'drinking',
      target: 'tool',
      observed_actions: ['moving'],
      segments: [{ action: 'moving', start_sec: 0, end_sec: 4 }],
    });
    const issues = collectGroundTruthIssues(input, 30, new Set());
    expect(firstIssueField(issues)).toBe('visibility');
    // visibility 를 선택하면 다음은 primary_action(직접 선택 규칙).
    const issues2 = collectGroundTruthIssues(input, 30, new Set<GroundTruthField>(['visibility']));
    expect(firstIssueField(issues2)).toBe('primary_action');
  });
});

describe('changedGroundTruthFields', () => {
  it('returns an empty list when nothing changed', () => {
    expect(changedGroundTruthFields(validGt(), validGt())).toEqual([]);
  });

  it('lists exactly the changed fields including note and arrays', () => {
    const before = validGt();
    const after = validGt({ target: 'water', context_tags: ['ir', 'human'], note: '메모' });
    expect(changedGroundTruthFields(before, after).sort()).toEqual(
      ['context_tags', 'note', 'target'].sort(),
    );
  });
});

describe('allowedTargetsFor', () => {
  it('narrows drinking and hand feeding, leaves others full', () => {
    expect(allowedTargetsFor('drinking')).toEqual(['water', 'water_bowl', 'glass', 'floor', 'uncertain']);
    expect(allowedTargetsFor('hand_feeding')).toEqual(['hand', 'tool']);
    expect(allowedTargetsFor('moving')).toBe(TARGETS);
    // wheel 은 어떤 대표 행동의 target 목록에도 없다.
    expect(allowedTargetsFor('drinking')).not.toContain('tool');
  });
});

describe('validateGroundTruth', () => {
  it('accepts ordinary moving without enrichment evidence', () => {
    expect(validateGroundTruth(validGt(), 30)).toEqual(validGt());
  });

  it('throws a typed error carrying every issue', () => {
    try {
      validateGroundTruth(validGt({ primary_action: 'drinking', target: 'tool' }), 30);
      throw new Error('should have thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(GroundTruthValidationError);
      const typed = error as GroundTruthValidationError;
      expect(typed.issues.map((issue) => issue.code)).toContain('drinking_target_invalid');
      expect(typed.message).toBe(typed.issues[0].message);
    }
  });

  it('still rejects malformed enum payloads with a plain 400-style error', () => {
    expect(() =>
      validateGroundTruth(validGt({ visibility: 'bogus' as GroundTruthInput['visibility'] }), 30),
    ).toThrow('가시성');
  });

  it('rejects playing with a friendly typed error', () => {
    expect(() =>
      validateGroundTruth(
        validGt({ primary_action: 'playing' as GroundTruthInput['primary_action'] }),
        30,
      ),
    ).toThrow('playing');
  });

  it('accepts a null activity_intensity for new GT (legacy read only, §6.3)', () => {
    expect(validateGroundTruth(validGt({ activity_intensity: null }), 30)).toEqual(
      validGt({ activity_intensity: null }),
    );
    // legacy 값도 계속 읽힌다.
    expect(validateGroundTruth(validGt({ activity_intensity: 'high' }), 30).activity_intensity).toBe(
      'high',
    );
  });

  it('rejects a malformed highlight_recommendation', () => {
    expect(() =>
      validateGroundTruth(
        validGt({
          highlight_recommendation: 'maybe' as GroundTruthInput['highlight_recommendation'],
        }),
        30,
      ),
    ).toThrow('하이라이트');
  });
});

describe('workflow helpers', () => {
  const prediction = { id: 'vlm-1', action: 'drinking', confidence: 0.65 };

  it('redacts prediction until an initial GT exists', () => {
    expect(revealPrediction(null, prediction)).toBeNull();
    expect(revealPrediction({ initial_gt: null }, prediction)).toBeNull();
  });

  it('reveals the exact prediction after GT lock', () => {
    expect(revealPrediction({ initial_gt: validGt() }, prediction)).toEqual(
      prediction,
    );
  });

  it('only permits draft to gt_locked to completed transitions', () => {
    expect(nextStage('draft', 'lock_gt')).toBe('gt_locked');
    expect(nextStage('gt_locked', 'complete_vlm_review')).toBe('completed');
    expect(() => nextStage('draft', 'complete_vlm_review')).toThrow('단계');
  });

  it('requires error tags for incorrect VLM reviews', () => {
    expect(() =>
      validateVlmReview({ verdict: 'incorrect', error_tags: [], note: null }),
    ).toThrow('오류 유형');
  });
});

describe('thumbnailKeyForClip', () => {
  it('prefers the explicit thumbnail key', () => {
    expect(
      thumbnailKeyForClip({
        thumbnail_r2_key: 'thumbs/a.jpg',
        r2_key: 'clips/a.mp4',
      }),
    ).toBe('thumbs/a.jpg');
  });

  it('derives jpg next to an mp4 when the DB key is missing', () => {
    expect(
      thumbnailKeyForClip({ thumbnail_r2_key: null, r2_key: 'clips/a.mp4' }),
    ).toBe('clips/a.jpg');
  });

  it('rejects a clip without any R2 key', () => {
    expect(() =>
      thumbnailKeyForClip({ thumbnail_r2_key: null, r2_key: null }),
    ).toThrow('썸네일');
  });
});

describe('applyVisibilityChange (하드닝 §6 — absent 취소 후 highlight 재선택)', () => {
  it('absent 로 바꾸면 highlight 를 exclude 로 정규화하되 직접선택으로 치지 않는다', () => {
    const start = validGt({ highlight_recommendation: 'include' });
    const { gt, selected } = applyVisibilityChange(start, new Set<GroundTruthField>(['visibility', 'primary_action']), 'absent');
    expect(gt.visibility).toBe('absent');
    expect(gt.primary_action).toBe('unseen');
    expect(gt.observed_actions).toEqual([]);
    expect(gt.segments).toEqual([]);
    expect(gt.target).toBe('none');
    expect(gt.highlight_recommendation).toBe('exclude');
    // 자동 정규화된 highlight 는 직접 선택이 아니다.
    expect(selected.has('highlight_recommendation')).toBe(false);
    // absent 라도 촬영 환경을 직접 확인(§4.1)하면 정규화 값을 통과한다.
    const confirmed = new Set(selected).add('context_tags');
    expect(collectGroundTruthIssues(gt, 30, confirmed)).toEqual([]);
  });

  it('absent → visible 로 되돌리면 highlight 직접선택 상태를 해제한다 (값은 유지)', () => {
    const absent = applyVisibilityChange(validGt(), new Set<GroundTruthField>(['visibility', 'primary_action']), 'absent');
    // absent 상태(highlight=exclude, 미선택)에서 다시 visible 로.
    const back = applyVisibilityChange(absent.gt, absent.selected, 'visible');
    expect(back.gt.visibility).toBe('visible');
    // 값은 자동 변경하지 않는다(exclude 유지).
    expect(back.gt.highlight_recommendation).toBe('exclude');
    // 하지만 직접선택은 해제 → 저장 시 재선택 요구.
    expect(back.selected.has('highlight_recommendation')).toBe(false);
    const issues = collectGroundTruthIssues(back.gt, 30, back.selected).map((i) => i.code);
    expect(issues).toContain('highlight_not_selected');
  });

  it('직접 고른 뒤에는 저장 가능 (재선택하면 통과)', () => {
    const back = applyVisibilityChange(
      applyVisibilityChange(validGt(), new Set<GroundTruthField>(['visibility', 'primary_action']), 'absent').gt,
      applyVisibilityChange(validGt(), new Set<GroundTruthField>(['visibility', 'primary_action']), 'absent').selected,
      'visible',
    );
    // 라벨러가 highlight 를 직접 고름(값+직접선택).
    const chosen = new Set(back.selected);
    chosen.add('highlight_recommendation');
    const gt: GroundTruthInput = { ...back.gt, highlight_recommendation: 'include' };
    expect(
      collectGroundTruthIssues(gt, 30, chosen).map((i) => i.code),
    ).not.toContain('highlight_not_selected');
  });

  it('visible → partial 같은 전이는 highlight 선택을 건드리지 않는다', () => {
    const selected = new Set<GroundTruthField>(['visibility', 'primary_action', 'highlight_recommendation']);
    const { selected: next } = applyVisibilityChange(validGt(), selected, 'partial');
    expect(next.has('highlight_recommendation')).toBe(true);
  });
});

describe('isValidHighlight (하드닝 §1)', () => {
  it('유효한 highlight 값만 true', () => {
    expect(isValidHighlight('include')).toBe(true);
    expect(isValidHighlight('exclude')).toBe(true);
    expect(isValidHighlight('uncertain')).toBe(true);
    expect(isValidHighlight(undefined)).toBe(false); // legacy: 필드 없음
    expect(isValidHighlight('high')).toBe(false); // legacy activity_intensity 오인 금지
    expect(isValidHighlight(null)).toBe(false);
  });
});

describe('브라우저 임시본 구조 검증 (하드닝 §5)', () => {
  it('정상(미완성 포함) draft 는 통과한다', () => {
    expect(isValidGroundTruthShape(validGt())).toBe(true);
    // 미완성: 관찰 없음·segment 없음 — 구조는 유효.
    expect(isValidGroundTruthShape(validGt({ observed_actions: [], segments: [] }))).toBe(true);
    // legacy activity_intensity 값도 구조상 허용.
    expect(isValidGroundTruthShape(validGt({ activity_intensity: 'high' }))).toBe(true);
  });

  it('잘못된 enum 은 거른다', () => {
    expect(isValidGroundTruthShape(validGt({ visibility: 'zzz' as never }))).toBe(false);
    expect(isValidGroundTruthShape(validGt({ highlight_recommendation: 'nope' as never }))).toBe(false);
    expect(isValidGroundTruthShape(validGt({ observed_actions: ['licking', 'bogus'] as never }))).toBe(false);
  });

  it('segments 가 배열이 아니면(문자열 등) 거른다', () => {
    expect(isValidGroundTruthShape({ ...validGt(), segments: 'not-an-array' })).toBe(false);
  });

  it('NaN/Infinity 같은 잘못된 숫자는 거른다', () => {
    expect(isValidGroundTruthShape({ ...validGt(), segments: [{ action: 'moving', start_sec: NaN, end_sec: 4 }] })).toBe(false);
    expect(isValidGroundTruthShape({ ...validGt(), segments: [{ action: 'moving', start_sec: 0, end_sec: Infinity }] })).toBe(false);
    expect(isValidGroundTruthShape({ ...validGt(), segments: [{ action: 'moving', start_sec: '0', end_sec: 4 }] })).toBe(false);
  });

  it('review 형식 오류를 거른다', () => {
    expect(isValidVlmReviewShape({ verdict: 'correct', error_tags: [], note: null })).toBe(true);
    expect(isValidVlmReviewShape({ verdict: 'bogus', error_tags: [], note: null })).toBe(false);
    expect(isValidVlmReviewShape({ verdict: 'incorrect', error_tags: ['nope'], note: null })).toBe(false);
    expect(isValidVlmReviewShape({ verdict: 'correct', error_tags: [], note: 42 })).toBe(false);
  });

  it('selected 필드 목록 구조 검증', () => {
    expect(isValidSelectedFields(['visibility', 'primary_action'])).toBe(true);
    expect(isValidSelectedFields(['visibility', 'bogus_field'])).toBe(false);
    expect(isValidSelectedFields('not-array')).toBe(false);
  });
});
