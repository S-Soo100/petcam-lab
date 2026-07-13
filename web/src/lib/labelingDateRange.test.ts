import { describe, expect, it } from 'vitest';

import {
  describeRange,
  kstDate,
  parseRange,
  presetRange,
  rangeToParams,
  shiftDate,
  singleDayOf,
  singleDayRange,
  stepDay,
  type DateRange,
} from './labelingDateRange';

// KST 14:00 on 2026-07-08 — comfortably inside the 8th regardless of UTC offset.
const NOW = new Date('2026-07-08T05:00:00Z');

describe('kstDate', () => {
  it('maps an instant to its KST calendar day', () => {
    expect(kstDate(NOW)).toBe('2026-07-08');
  });

  it('rolls to the next KST day after 15:00 UTC (00:00 KST)', () => {
    expect(kstDate(new Date('2026-07-08T15:30:00Z'))).toBe('2026-07-09');
    expect(kstDate(new Date('2026-07-08T14:30:00Z'))).toBe('2026-07-08');
  });
});

describe('presetRange', () => {
  it('today spans one KST calendar day', () => {
    expect(presetRange('today', NOW)).toEqual({
      date_from: '2026-07-08T00:00:00+09:00',
      date_to: '2026-07-08T23:59:59+09:00',
    });
  });

  it('yesterday is the previous KST day', () => {
    expect(presetRange('yesterday', NOW)).toEqual(singleDayRange('2026-07-07'));
  });

  it('last3 covers today plus the two prior KST days', () => {
    expect(presetRange('last3', NOW)).toEqual({
      date_from: '2026-07-06T00:00:00+09:00',
      date_to: '2026-07-08T23:59:59+09:00',
    });
  });

  it('last7 covers today plus the six prior KST days', () => {
    expect(presetRange('last7', NOW)).toEqual({
      date_from: '2026-07-02T00:00:00+09:00',
      date_to: '2026-07-08T23:59:59+09:00',
    });
  });
});

describe('shiftDate / stepDay across boundaries', () => {
  it('steps forward across a year boundary', () => {
    expect(shiftDate('2026-12-31', 1)).toBe('2027-01-01');
  });

  it('steps backward across a year boundary', () => {
    expect(shiftDate('2027-01-01', -1)).toBe('2026-12-31');
  });

  it('moves a single-day range to the next day (12/31 → 1/1)', () => {
    expect(stepDay(singleDayRange('2026-12-31'), 1)).toEqual(
      singleDayRange('2027-01-01'),
    );
  });

  it('moves a single-day range to the previous day (1/1 → 12/31)', () => {
    expect(stepDay(singleDayRange('2027-01-01'), -1)).toEqual(
      singleDayRange('2026-12-31'),
    );
  });

  it('refuses to step a multi-day range', () => {
    expect(stepDay(presetRange('last3', NOW), 1)).toBeNull();
    expect(stepDay({}, 1)).toBeNull();
  });
});

describe('singleDayOf', () => {
  it('detects a one-day range', () => {
    expect(singleDayOf(singleDayRange('2026-07-08'))).toBe('2026-07-08');
  });

  it('returns null for multi-day and all-time ranges', () => {
    expect(singleDayOf(presetRange('last7', NOW))).toBeNull();
    expect(singleDayOf({})).toBeNull();
  });
});

describe('describeRange', () => {
  it('describes a single day', () => {
    expect(describeRange(singleDayRange('2026-07-08'))).toBe(
      '2026년 7월 8일 하루',
    );
  });

  it('describes a multi-day span', () => {
    expect(describeRange(presetRange('last3', NOW))).toBe(
      '2026년 7월 6일 ~ 2026년 7월 8일',
    );
  });

  it('describes the all-time range', () => {
    expect(describeRange({})).toBe('전체 기간');
  });
});

describe('URL round trip', () => {
  it('serialises and parses a range back to itself', () => {
    const ranges: DateRange[] = [
      singleDayRange('2026-07-08'),
      presetRange('last7', NOW),
      {},
    ];
    for (const range of ranges) {
      const sp = new URLSearchParams(rangeToParams(range));
      const parsed = parseRange(sp);
      // {} normalises undefined keys — compare the meaningful fields.
      expect(parsed.date_from ?? undefined).toBe(range.date_from ?? undefined);
      expect(parsed.date_to ?? undefined).toBe(range.date_to ?? undefined);
    }
  });
});
