import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';

import DetectorPage from './page';

const originalVercelEnv = process.env.VERCEL_ENV;
const originalPreviewEnabled = process.env.YOLO_PREVIEW_ENABLED;
const originalAssistEnabled = process.env.YOLO_LABELING_ASSIST_ENABLED;
const originalWorkerUrl = process.env.YOLO_WORKER_URL;
const originalWorkerToken = process.env.YOLO_WORKER_TOKEN;

afterEach(() => {
  process.env.VERCEL_ENV = originalVercelEnv;
  process.env.YOLO_PREVIEW_ENABLED = originalPreviewEnabled;
  process.env.YOLO_LABELING_ASSIST_ENABLED = originalAssistEnabled;
  process.env.YOLO_WORKER_URL = originalWorkerUrl;
  process.env.YOLO_WORKER_TOKEN = originalWorkerToken;
});

describe('DetectorPage deployment copy', () => {
  it('enable된 Vercel Preview에서는 worker version을 미리 단정하지 않는다', () => {
    process.env.VERCEL_ENV = 'preview';
    process.env.YOLO_PREVIEW_ENABLED = 'true';
    process.env.YOLO_WORKER_URL = 'https://yolo-v23-preview.tera-ai.uk';
    process.env.YOLO_WORKER_TOKEN = 's'.repeat(43);

    const html = renderToStaticMarkup(<DetectorPage />);

    expect(html).toContain('Development-only 라벨링 보조');
    expect(html).toContain('게코 없음 판정이 아니야');
    expect(html).toContain('실제 모델 버전과 threshold는 처리 결과에서 확인해');
    expect(html).not.toContain('v2.3');
    expect(html).not.toContain('threshold 0.25');
  });

  it('production에서는 enable 값이 있어도 fake 설명을 유지한다', () => {
    process.env.VERCEL_ENV = 'production';
    process.env.YOLO_PREVIEW_ENABLED = 'true';

    const html = renderToStaticMarkup(<DetectorPage />);

    expect(html).not.toContain('Development-only 라벨링 보조 Preview');
    expect(html).toContain('지금 연결된 fake');
  });

  it('production 전용 assist 설정이 완성되면 공개 worker 설명을 표시한다', () => {
    process.env.VERCEL_ENV = 'production';
    process.env.YOLO_LABELING_ASSIST_ENABLED = 'true';
    process.env.YOLO_WORKER_URL = 'https://yolo-v23-preview.tera-ai.uk';
    process.env.YOLO_WORKER_TOKEN = 's'.repeat(43);

    const html = renderToStaticMarkup(<DetectorPage />);

    expect(html).toContain('Development-only 라벨링 보조');
    expect(html).toContain('게코 없음 판정이 아니야');
    expect(html).not.toContain('지금 연결된 fake');
    expect(html).not.toContain('라벨링 보조 Preview');
  });

  it.each([
    ['HTTP URL', 'http://yolo-v23-preview.tera-ai.uk', 's'.repeat(43)],
    ['다른 HTTPS origin', 'https://wrong-worker.example.test', 's'.repeat(43)],
    ['짧은 token', 'https://yolo-v23-preview.tera-ai.uk', 'short-token'],
  ])('production의 %s 설정은 assist 활성화로 표시하지 않는다', (_name, url, token) => {
    process.env.VERCEL_ENV = 'production';
    process.env.YOLO_LABELING_ASSIST_ENABLED = 'true';
    process.env.YOLO_WORKER_URL = url;
    process.env.YOLO_WORKER_TOKEN = token;

    const html = renderToStaticMarkup(<DetectorPage />);

    expect(html).toContain('지금 연결된 fake');
    expect(html).not.toContain('Development-only 라벨링 보조');
  });
});
