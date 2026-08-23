import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import ReviewVideo, { formatReviewVideoTime } from './_review-video';

describe('ReviewVideo', () => {
  it('formats invalid and minute-scale media times', () => {
    expect(formatReviewVideoTime(Number.NaN)).toBe('0:00');
    expect(formatReviewVideoTime(-1)).toBe('0:00');
    expect(formatReviewVideoTime(65.9)).toBe('1:05');
  });

  it('starts muted autoplay without native overlay controls', () => {
    const html = renderToStaticMarkup(
      <ReviewVideo src="https://media.example/test.mp4" getDownload={async () => ({ url: 'https://download.example/x', filename: 'x.mp4' })} />,
    );

    expect(html).toContain('autoplay=""');
    expect(html).toContain('muted=""');
    expect(html).toContain('playsinline=""');
    expect(html).toContain('preload="auto"');
    expect(html).not.toContain(' controls=""');
  });

  it('renders accessible controls outside the video element', () => {
    const html = renderToStaticMarkup(
      <ReviewVideo src="https://media.example/test.mp4" getDownload={async () => ({ url: 'https://download.example/x', filename: 'x.mp4' })} />,
    );

    expect(html).toContain('aria-label="영상 재생 위치"');
    expect(html).toContain('aria-label="영상 재생"');
    expect(html).toContain('aria-label="소리 켜기"');
    expect(html).toContain('aria-label="전체화면"');
    expect(html).toContain('aria-label="영상 다운로드"');
    expect(html.indexOf('</video>')).toBeLessThan(html.indexOf('aria-label="영상 재생"'));
    expect(html).toContain('flex-wrap');
  });

  it('gives every playback action a 44px keyboard and touch target', () => {
    const html = renderToStaticMarkup(
      <ReviewVideo src="https://media.example/test.mp4" getDownload={async () => ({ url: 'https://download.example/x', filename: 'x.mp4' })} />,
    );

    expect(html.match(/min-h-11 min-w-11/g)).toHaveLength(4);
  });

  it('uses a separately authorized attachment URL without buffering the video', () => {
    const source = readFileSync(
      fileURLToPath(new URL('./_review-video.tsx', import.meta.url)),
      'utf8',
    );

    expect(source).toContain('await getDownload()');
    expect(source).toContain('anchor.download =');
    expect(source).not.toContain('await fetch(src)');
    expect(source).not.toContain('URL.createObjectURL');
  });

  it('remounts playback state when the source changes', () => {
    const source = readFileSync(
      fileURLToPath(new URL('./_review-video.tsx', import.meta.url)),
      'utf8',
    );

    expect(source).toContain('<ReviewVideoInstance key={src}');
  });
});
