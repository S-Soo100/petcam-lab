import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import ReviewVideo, { formatReviewVideoTime, getContainedMediaRect } from './_review-video';

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

  it('renders the optional GME overlay over the video and before controls', () => {
    const html = renderToStaticMarkup(
      <ReviewVideo
        src="https://media.example/test.mp4"
        getDownload={async () => ({ url: 'https://download.example/x', filename: 'x.mp4' })}
        overlay={<span data-overlay="gme" />}
      />,
    );
    expect(html).toContain('data-overlay="gme"');
    expect(html.indexOf('data-overlay="gme"')).toBeLessThan(html.indexOf('aria-label="영상 재생"'));
  });

  it('maps overlays to the object-contain content box for non-16:9 video', () => {
    expect(getContainedMediaRect(4, 3, 16, 9)).toEqual({
      leftPct: 12.5,
      topPct: 0,
      widthPct: 75,
      heightPct: 100,
    });
    expect(getContainedMediaRect(21, 9, 16, 9)).toEqual({
      leftPct: 0,
      topPct: 11.904761904761905,
      widthPct: 100,
      heightPct: 76.19047619047619,
    });
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

  it('synchronizes parent playback time immediately for slider and frame seeks', () => {
    const reviewSource = readFileSync(
      fileURLToPath(new URL('./_review-video.tsx', import.meta.url)),
      'utf8',
    );
    const formSource = readFileSync(
      fileURLToPath(new URL('./_labeling-forms.tsx', import.meta.url)),
      'utf8',
    );
    const seekRegion = reviewSource.slice(
      reviewSource.indexOf('function seek('),
      reviewSource.indexOf('async function openFullscreen'),
    );
    expect(seekRegion).toContain('onTimeUpdate?.(video.currentTime)');
    expect(formSource).toContain('function stepFrame(');
    expect(formSource).toContain('onTimeUpdate?.(nextTime)');
  });

  it('remounts playback state when the source changes', () => {
    const source = readFileSync(
      fileURLToPath(new URL('./_review-video.tsx', import.meta.url)),
      'utf8',
    );

    expect(source).toContain('<ReviewVideoInstance key={src}');
  });
});
