import type { GroundTruthInput } from './labelingV2';
import {
  BLIND_COMPARATOR_VERSION,
  compareBlindSubmissions,
  type BlindComparison,
  type BlindSubmissionInput,
} from './motionBlindReview';

export const LIVE_V2_COMPARATOR_VERSION = 'motion-blind-live-v2-highlight-soft' as const;

export type BlindComparatorVersion =
  | typeof BLIND_COMPARATOR_VERSION
  | typeof LIVE_V2_COMPARATOR_VERSION;

export type VersionedBlindComparison = BlindComparison<BlindComparatorVersion>;

export function isBlindComparatorVersion(value: unknown): value is BlindComparatorVersion {
  return value === BLIND_COMPARATOR_VERSION || value === LIVE_V2_COMPARATOR_VERSION;
}

export function compareBlindSubmissionsByVersion(
  version: BlindComparatorVersion,
  a: BlindSubmissionInput,
  b: BlindSubmissionInput,
): VersionedBlindComparison {
  if (!isBlindComparatorVersion(version)) {
    throw new Error('unknown_blind_comparator_version');
  }

  const result = compareBlindSubmissions(a, b);
  if (version === BLIND_COMPARATOR_VERSION) {
    return result;
  }

  if (
    result.status === 'conflict'
    && result.differing_fields.length === 1
    && result.differing_fields[0] === 'highlight_recommendation'
  ) {
    const finalGt = a.initial_gt as GroundTruthInput;
    return {
      status: 'agreed',
      final_decision: 'label',
      final_gt: {
        ...finalGt,
        highlight_recommendation: 'uncertain',
      },
      differing_fields: ['highlight_recommendation'],
      comparator_version: version,
    };
  }

  return {
    ...result,
    comparator_version: version,
  };
}
