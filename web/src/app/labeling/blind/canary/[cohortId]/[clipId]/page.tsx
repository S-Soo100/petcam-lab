'use client';

import { useParams } from 'next/navigation';

import { BlindReviewDetail } from '../../../../_blind-review-detail';

// canary 상세 = /labeling/blind/canary/[cohortId]/[clipId]. cohort_id 를 path 에서 고정해 모든
// 요청·URL 에 붙는다(설계 §6.3). 활동일 unlock/progress 는 건드리지 않는다(canary 격리).
export default function BlindCanaryClipPage() {
  const { cohortId, clipId } = useParams<{ cohortId: string; clipId: string }>();
  return <BlindReviewDetail clipId={clipId} cohortId={cohortId} activityDay={null} />;
}
