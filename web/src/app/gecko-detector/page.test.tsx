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
  it('enable된 Vercel Preview에서만 실제 v2.1 설명을 보인다', () => {
    process.env.VERCEL_ENV = 'preview';
    process.env.YOLO_PREVIEW_ENABLED = 'true';

    const html = renderToStaticMarkup(<DetectorPage />);

    expect(html).toContain('YOLO v2.1 보호 Preview');
    expect(html).toContain('고정된 v2.1 checkpoint');
  });

  it('production에서는 enable 값이 있어도 fake 설명을 유지한다', () => {
    process.env.VERCEL_ENV = 'production';
    process.env.YOLO_PREVIEW_ENABLED = 'true';

    const html = renderToStaticMarkup(<DetectorPage />);

    expect(html).not.toContain('YOLO v2.1 보호 Preview');
    expect(html).toContain('지금 연결된 fake');
  });
});
