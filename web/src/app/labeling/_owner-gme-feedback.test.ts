import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(join(process.cwd(), 'src/app/labeling/motion/[clipId]/page.tsx'), 'utf8');

describe('Owner 직접 라벨링 GME 피드백 연결', () => {
  it('GME overlay를 독립 로드하고 미탐·오탐·부정확 bbox를 GT와 분리해 기록한다', () => {
    expect(source).toContain('getOwnerGmeOverlay');
    expect(source).toContain('reportOwnerGmeFeedback');
    expect(source).toContain('GmeVideoOverlay');
    expect(source).toContain('GmeFeedbackReportPanel');
    expect(source).toContain('onTimeUpdate={setPlaybackTime}');
    expect(source).toContain('false_positive:');
    expect(source).toContain('bad_box:');

    const saveStart = source.indexOf('await lockMotionGt(');
    const saveRegion = source.slice(saveStart, saveStart + 500);
    expect(saveRegion).not.toContain('overlay');
    expect(saveRegion).not.toContain('gme');
  });

  it('영상 전체 미탐이면 사람 확인 한 번으로 absent GT를 잠근다', () => {
    expect(source).toContain('confirmAbsent');
    expect(source).toContain("applyVisibilityChange(emptyGt(duration), new Set(), 'absent')");
    expect(source).toContain('await lockMotionGt(clipId, absent.gt)');
    expect(source).toContain('onConfirmAbsent');
  });
});
