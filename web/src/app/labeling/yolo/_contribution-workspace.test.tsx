import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ContributionWorkspace } from './_contribution-workspace';
import type { BlindWorkspace, RevealResult } from '@/lib/yoloContribution';

const taskId = '11111111-1111-4111-8111-111111111111';
const blind: BlindWorkspace = {
  enabled: true,
  total: 1,
  completed: 0,
  next_task: {
    task_id: taskId,
    media_kind: 'image',
    media_url: 'https://example.test/gecko.jpg',
    frame_manifest: [{ frame_index: 0, timestamp_ms: 0 }],
    stage: 'blind',
  },
};
const submitted: BlindWorkspace = {
  ...blind,
  next_task: blind.next_task ? { ...blind.next_task, stage: 'submitted' } : null,
};
const revealed: RevealResult = {
  task_id: taskId,
  revealed_at: '2026-08-10T08:00:00Z',
  prediction: {
    request_id: 'req-1', media_kind: 'image', model_version: 'yolo-v1', provider_mode: 'worker',
    processed_at: '2026-08-10T07:59:00Z', warning: '연구용 결과이며 오류 가능',
    contribution_status: 'not_requested',
    frames: [{ frame_index: 0, timestamp_ms: 0, detections: [] }],
  },
  blind_annotation: { boxes: [], no_gecko: true },
  working_annotation: { boxes: [], no_gecko: true },
  owner_feedback: '꼬리 끝 경계를 다시 확인해',
  stage: 'revealed',
};

describe('ContributionWorkspace', () => {
  it('blind 단계 DOM에는 모델 정보가 없고 잠금 행동만 있다', () => {
    const html = renderToStaticMarkup(<ContributionWorkspace initial={blind} />);
    expect(html).toContain('내 박스 잠그고 모델 결과 보기');
    expect(html).not.toContain('yolo-v1');
    expect(html).not.toContain('confidence');
    expect(html).not.toContain('모델 박스');
  });

  it('reveal 뒤에만 사람/모델 비교와 revision 사유가 보인다', () => {
    const html = renderToStaticMarkup(<ContributionWorkspace initial={blind} initialReveal={revealed} />);
    expect(html).toContain('사람 박스');
    expect(html).toContain('모델 박스');
    expect(html).toContain('yolo-v1');
    expect(html).toContain('변경 사유');
    expect(html).toContain('꼬리 끝 경계를 다시 확인해');
  });

  it('잠긴 blind 작업은 다시 제출하지 않고 reveal 재개 상태로 연다', () => {
    const html = renderToStaticMarkup(<ContributionWorkspace initial={submitted} />);
    expect(html).toContain('잠긴 사람 박스를 불러오는 중');
    expect(html).not.toContain('내 박스 잠그고 모델 결과 보기');
    expect(html).not.toContain('모델 박스');
  });
});
