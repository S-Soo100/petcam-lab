import type { GmeObservedMovingTime } from './labelingV3';


export interface GmeObservedMovingTimeCopy {
  title: string;
  detail: string;
}

function seconds(value: number): string {
  return String(Math.round((value + Number.EPSILON) * 10) / 10);
}

function measuredDetail(metric: GmeObservedMovingTime): string {
  return [
    `게코가 보인 시간 ${seconds(metric.visible_sec ?? 0)}초`,
    `미확정 ${seconds(metric.unknown_sec ?? 0)}초`,
    `카메라 움직임 ${seconds(metric.camera_motion_sec ?? 0)}초`,
  ].join(' · ');
}

function isValidMeasuredMetric(metric: GmeObservedMovingTime): boolean {
  const values = [
    metric.moving_time_sec,
    metric.visible_sec,
    metric.unknown_sec,
    metric.camera_motion_sec,
  ];
  return (
    values.every(
      (value): value is number =>
        typeof value === 'number' && Number.isFinite(value) && value >= 0,
    ) &&
    metric.visible_sec !== null &&
    metric.visible_sec > 0 &&
    metric.moving_time_sec !== null &&
    metric.moving_time_sec <= metric.visible_sec
  );
}

// UI 문구만 담당하는 순수 함수. 지표 유효성은 server allowlist mapper에서 이미 검증한다.
export function formatGmeObservedMovingTime(
  metric: GmeObservedMovingTime,
): GmeObservedMovingTimeCopy {
  switch (metric.measurement_status) {
    case 'measured': {
      const movingTimeSec = metric.moving_time_sec;
      if (!isValidMeasuredMetric(metric) || movingTimeSec === null) {
        return {
          title: 'GME 분석 실패',
          detail: '현재 모델의 결과가 올바르지 않아 움직임 시간을 표시할 수 없어.',
        };
      }
      return {
        title: `영상에서 확인된 움직임 ${seconds(movingTimeSec)}초`,
        detail: measuredDetail(metric),
      };
    }
    case 'not_observed':
      return {
        title: '게코 미관측 · 측정 불가',
        detail: measuredDetail(metric),
      };
    case 'pending':
      return {
        title: 'GME 분석 대기 중',
        detail: '현재 모델의 분석이 끝나면 관측 움직임 시간을 표시해.',
      };
    case 'failed':
      return {
        title: 'GME 분석 실패',
        detail: '현재 모델의 결과가 없어 움직임 시간을 표시할 수 없어.',
      };
  }
}
