import type { GroundTruthInput } from './labelingV2';

export type CanonicalGtStatus = 'none' | 'review_in_progress' | 'conflict' | 'final';
export type CanonicalGtDecision = 'label' | 'hold' | 'exclude';
export type CanonicalGtSource =
  | 'blind_consensus'
  | 'owner_adjudication'
  | 'owner_override'
  | 'owner_direct_legacy'
  | 'owner_single_adopt';
export type CanonicalCandidateSource = 'consensus' | 'direct';

export interface CanonicalGtCandidate {
  source: CanonicalCandidateSource;
  decision: CanonicalGtDecision;
  gt: GroundTruthInput | null;
  sourceType: CanonicalGtSource;
  sourceLabel: string;
}

export interface CanonicalMotionGt {
  status: CanonicalGtStatus;
  revisionId: string | null;
  decision: CanonicalGtDecision | null;
  gt: GroundTruthInput | null;
  source: CanonicalGtSource | null;
  sourceLabel: string | null;
  updatedAt: string | null;
  candidates: CanonicalGtCandidate[] | null;
}

const STATUS = new Set<CanonicalGtStatus>(['none', 'review_in_progress', 'conflict', 'final']);
const DECISION = new Set<CanonicalGtDecision>(['label', 'hold', 'exclude']);
const SOURCE_LABEL: Record<CanonicalGtSource, string> = {
  blind_consensus: '교차검수 합의',
  owner_adjudication: 'Owner 불일치 해결',
  owner_override: 'Owner 보정',
  owner_direct_legacy: '기존 Owner 직접 라벨',
  owner_single_adopt: 'Owner 단독 확정',
};

function nullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function parseSource(value: unknown): CanonicalGtSource | null {
  if (value == null) return null;
  if (typeof value !== 'string' || !(value in SOURCE_LABEL)) throw new Error('invalid_canonical_gt_source');
  return value as CanonicalGtSource;
}

function parseDecision(value: unknown): CanonicalGtDecision | null {
  if (value == null) return null;
  if (typeof value !== 'string' || !DECISION.has(value as CanonicalGtDecision)) {
    throw new Error('invalid_canonical_gt_decision');
  }
  return value as CanonicalGtDecision;
}

export function canonicalGtSourceLabel(source: CanonicalGtSource): string {
  return SOURCE_LABEL[source];
}

export function canShowCanonicalCorrection(
  canonical: CanonicalMotionGt | undefined,
  canonicalWriteEnabled: boolean,
): boolean {
  return canonical == null || canonicalWriteEnabled;
}

export function mapCanonicalMotionGt(raw: unknown): CanonicalMotionGt {
  const row = (raw ?? {}) as Record<string, unknown>;
  if (typeof row.status !== 'string' || !STATUS.has(row.status as CanonicalGtStatus)) {
    throw new Error('invalid_canonical_gt_status');
  }
  const status = row.status as CanonicalGtStatus;
  const empty = {
    status, revisionId: null, decision: null, gt: null, source: null,
    sourceLabel: null, updatedAt: nullableString(row.updated_at), candidates: null,
  } satisfies CanonicalMotionGt;
  if (status === 'none' || status === 'review_in_progress') return { ...empty, updatedAt: status === 'none' ? null : empty.updatedAt };

  if (status === 'final') {
    const source = parseSource(row.source_type);
    return {
      ...empty,
      revisionId: nullableString(row.revision_id),
      decision: parseDecision(row.decision),
      gt: row.gt && typeof row.gt === 'object' ? row.gt as GroundTruthInput : null,
      source,
      sourceLabel: source ? SOURCE_LABEL[source] : null,
    };
  }

  const candidates = Array.isArray(row.candidates)
    ? row.candidates.map((rawCandidate) => {
        const candidate = (rawCandidate ?? {}) as Record<string, unknown>;
        const sourceType = parseSource(candidate.source_type);
        if (!sourceType || (candidate.source !== 'consensus' && candidate.source !== 'direct')) {
          throw new Error('invalid_canonical_gt_candidate');
        }
        const decision = parseDecision(candidate.decision);
        if (!decision) throw new Error('invalid_canonical_gt_candidate');
        return {
          source: candidate.source as CanonicalCandidateSource,
          decision,
          gt: candidate.gt && typeof candidate.gt === 'object' ? candidate.gt as GroundTruthInput : null,
          sourceType,
          sourceLabel: SOURCE_LABEL[sourceType],
        };
      })
    : null;
  return { ...empty, candidates };
}
