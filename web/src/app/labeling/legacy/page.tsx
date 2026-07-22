// /labeling/legacy — 과거 camera_clips 큐 진입점(설계 §6.1).
// v3 전환 뒤에도 legacy 큐를 명시적으로 열 수 있게 유지한다.

import LegacyQueue from '../_legacy-queue';

export default function LegacyLabelingPage() {
  return <LegacyQueue />;
}
