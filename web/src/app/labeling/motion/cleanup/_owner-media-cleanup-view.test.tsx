import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('../../_review-video', () => ({ default: ({ src }: { src: string }) => <div data-video={src}>video</div> }));

import { OwnerMediaCleanupView } from './_owner-media-cleanup-view';

describe('OwnerMediaCleanupView', () => {
  it('유지/삭제/보류 결정을 서로 다른 영역에 배치한다', () => {
    const html = renderToStaticMarkup(
      <OwnerMediaCleanupView
        item={{ clip_id: '11111111-1111-4111-8111-111111111111', started_at: '2026-07-14T12:00:00Z', duration_sec: 30, camera_name: 'A' }}
        videoUrl="https://media.example/video.mp4"
        summary={{ available: 897, completed: 0, remaining: 897, source_missing: 7 }}
        busy={false}
        onDecision={() => {}}
        getDownload={async () => ({ url: 'https://download.example', filename: 'clip.mp4' })}
      />,
    );
    expect(html).toContain('정상 영상으로 남기기');
    expect(html).toContain('게코가 안 보임');
    expect(html).toContain('게코 활동이 없음');
    expect(html).toContain('판단 보류');
    expect(html).toContain('0 / 897 완료');
  });
});
