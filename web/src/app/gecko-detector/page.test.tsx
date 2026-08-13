import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';

import DetectorPage from './page';

const originalVercelEnv = process.env.VERCEL_ENV;
const originalPreviewEnabled = process.env.YOLO_PREVIEW_ENABLED;

afterEach(() => {
  process.env.VERCEL_ENV = originalVercelEnv;
  process.env.YOLO_PREVIEW_ENABLED = originalPreviewEnabled;
});

describe('DetectorPage deployment copy', () => {
  it('enable된 Vercel Preview에서만 v2.3 라벨링 보조 설명을 보인다', () => {
    process.env.VERCEL_ENV = 'preview';
    process.env.YOLO_PREVIEW_ENABLED = 'true';

    const html = renderToStaticMarkup(<DetectorPage />);

    expect(html).toContain('Dataset v2.3 라벨링 보조');
    expect(html).toContain('threshold 0.25');
    expect(html).toContain('게코 없음 판정이 아니야');
  });

  it('production에서는 enable 값이 있어도 fake 설명을 유지한다', () => {
    process.env.VERCEL_ENV = 'production';
    process.env.YOLO_PREVIEW_ENABLED = 'true';

    const html = renderToStaticMarkup(<DetectorPage />);

    expect(html).not.toContain('Dataset v2.3 라벨링 보조');
    expect(html).toContain('지금 연결된 fake');
  });
});
