import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { RecordingsView } from './_recordings-view';

describe('RAP recordings view', () => {
  it('shows production coverage, safe failure label and recording card', () => {
    const html = renderToStaticMarkup(
      <RecordingsView
        mode="production"
        coverage={{ expected: 72, captured: 71, uploaded: 70, failed: 1, missing: 1 }}
        items={[{
          id: 'id-1', mode: 'production', camera_key: 'cam01', test_run_id: null, night_date: '2026-08-26',
          scheduled_start_utc: '2026-08-26T11:00:00Z', actual_start_utc: '2026-08-26T11:00:00Z', partial: false,
          duration_sec: 1800, codec: 'hevc', width: 2880, height: 1620, fps: 20, video_size_bytes: 10,
          capture_status: 'captured', upload_status: 'upload_failed', last_error_code: 'network', uploaded_at: null,
        }]}
      />,
    );
    expect(html).toContain('72개 중 70개 업로드');
    expect(html).toContain('누락 1');
    expect(html).toContain('업로드 실패');
    expect(html).toContain('cam01');
  });

  it('does not show production coverage in test mode', () => {
    const html = renderToStaticMarkup(<RecordingsView mode="test" coverage={null} items={[]} />);
    expect(html).toContain('테스트 녹화');
    expect(html).not.toContain('72개 중');
  });
});
