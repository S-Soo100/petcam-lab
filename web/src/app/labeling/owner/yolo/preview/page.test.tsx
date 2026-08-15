import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));
vi.mock('next/navigation', () => ({ notFound }));

import OwnerYoloV25PreviewPage from './page';

const original = {
  VERCEL_ENV: process.env.VERCEL_ENV,
  enabled: process.env.YOLO_V25_OWNER_PREVIEW_ENABLED,
  url: process.env.YOLO_V25_OWNER_WORKER_URL,
  token: process.env.YOLO_V25_OWNER_WORKER_TOKEN,
};

afterEach(() => {
  for (const [key, value] of Object.entries({
    VERCEL_ENV: original.VERCEL_ENV,
    YOLO_V25_OWNER_PREVIEW_ENABLED: original.enabled,
    YOLO_V25_OWNER_WORKER_URL: original.url,
    YOLO_V25_OWNER_WORKER_TOKEN: original.token,
  })) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  vi.clearAllMocks();
});

describe('OwnerYoloV25PreviewPage', () => {
  it('Preview exact config가 아니면 page 자체를 404로 닫는다', () => {
    process.env.VERCEL_ENV = 'production';
    process.env.YOLO_V25_OWNER_PREVIEW_ENABLED = 'true';
    process.env.YOLO_V25_OWNER_WORKER_URL = 'https://yolo-v25-preview.tera-ai.uk';
    process.env.YOLO_V25_OWNER_WORKER_TOKEN = 's'.repeat(43);

    expect(() => OwnerYoloV25PreviewPage()).toThrow('NEXT_NOT_FOUND');
    expect(notFound).toHaveBeenCalledOnce();
  });

  it('Preview exact config에서만 화면을 렌더한다', () => {
    process.env.VERCEL_ENV = 'preview';
    process.env.YOLO_V25_OWNER_PREVIEW_ENABLED = 'true';
    process.env.YOLO_V25_OWNER_WORKER_URL = 'https://yolo-v25-preview.tera-ai.uk';
    process.env.YOLO_V25_OWNER_WORKER_TOKEN = 's'.repeat(43);

    const html = renderToStaticMarkup(OwnerYoloV25PreviewPage());

    expect(html).toContain('YOLO v2.5 Owner Preview');
    expect(notFound).not.toHaveBeenCalled();
  });
});
