import { NextRequest } from 'next/server';

import { validateAuditSubmission, type AuditSubmission } from '@/lib/gmeNegativeAudit';
import {
  auditInvalid,
  auditJson,
  auditUnavailable,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256 = /^[0-9a-f]{64}$/;

type PrivateItem = {
  id: string;
  ordinal: number;
  durationSec: number;
  stratum: 'random_negative' | 'positive_control';
  assignedReviewerId: string;
};
type Effective = AuditSubmission & { digest: string };

function exactRecord(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('shape');
  const row = value as Record<string, unknown>;
  const actual = Object.keys(row).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new Error('keys');
  }
  return row;
}

function rows(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('rows');
  return value;
}

function uuid(value: unknown): string {
  if (typeof value !== 'string' || !UUID.test(value)) throw new Error('uuid');
  return value;
}

function digest(value: unknown): string {
  if (typeof value !== 'string' || !SHA256.test(value)) throw new Error('digest');
  return value;
}

function count(value: unknown): number {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN;
  if (!Number.isSafeInteger(parsed) || parsed < 0) throw new Error('count');
  return parsed;
}

function positiveNumber(value: unknown): number {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN;
  if (!Number.isFinite(parsed) || parsed <= 0 || Math.abs(parsed) > Number.MAX_SAFE_INTEGER) throw new Error('number');
  return parsed;
}

function nullableNumber(value: unknown): number | null {
  if (value === null) return null;
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN;
  if (!Number.isFinite(parsed) || Math.abs(parsed) > Number.MAX_SAFE_INTEGER) throw new Error('number');
  return parsed;
}

function ownerRequired() {
  return auditJson({ detail: 'Owner만 접근할 수 있어.', code: 'owner_required' }, 403);
}

function notFound() {
  return auditJson({ detail: '진행 중인 점검을 찾을 수 없어.', code: 'audit_not_found' }, 404);
}

function batchClosed() {
  return auditJson({ detail: '점검이 종료됐어.', code: 'batch_closed' }, 410);
}

async function selectItemChildren(table: string, selection: string, itemIds: string[]) {
  const query = supabaseAdmin.from(table).select(selection).in('item_id', itemIds);
  const { data, error } = await (table === 'gme_negative_audit_corrections'
    ? query.order('created_at', { ascending: true }).order('id', { ascending: true })
    : query);
  if (error) throw error;
  return rows(data);
}

export async function GET(req: NextRequest) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return withAuditNoStore(access.response);
  if (!access.isOwner) return ownerRequired();
  if (Array.from(req.nextUrl.searchParams.keys()).length > 0) return auditInvalid();

  try {
    const batchResult = await supabaseAdmin
      .from('gme_negative_audit_batches')
      .select('id, batch_kind, expected_negative_count, expected_control_count, expected_total_count')
      .eq('owner_id', access.userId)
      .order('created_at', { ascending: false })
      .order('id', { ascending: false })
      .limit(1);
    if (batchResult.error) throw batchResult.error;
    const batchRows = rows(batchResult.data);
    if (batchRows.length === 0) return notFound();
    if (batchRows.length !== 1) throw new Error('batch cardinality');
    const batch = exactRecord(batchRows[0], [
      'id', 'batch_kind', 'expected_negative_count', 'expected_control_count', 'expected_total_count',
    ]);
    const batchId = uuid(batch.id);
    const negativeTotal = count(batch.expected_negative_count);
    const controlTotal = count(batch.expected_control_count);
    const total = count(batch.expected_total_count);
    if (
      batch.batch_kind !== 'calibration' || negativeTotal !== 120 || controlTotal !== 30 ||
      total !== 150 || negativeTotal + controlTotal !== total
    ) throw new Error('batch contract');

    const eventResult = await supabaseAdmin
      .from('gme_negative_audit_batch_events')
      .select('event_type')
      .eq('batch_id', batchId)
      .order('created_at', { ascending: false })
      .order('id', { ascending: false })
      .limit(1);
    if (eventResult.error) throw eventResult.error;
    const eventRows = rows(eventResult.data);
    if (eventRows.length !== 1) throw new Error('batch event cardinality');
    const event = exactRecord(eventRows[0], ['event_type']);
    if (event.event_type !== 'opened') return batchClosed();

    const itemResult = await supabaseAdmin
      .from('gme_negative_audit_items')
      .select('id, ordinal, duration_sec, stratum, assigned_reviewer_id')
      .eq('batch_id', batchId)
      .order('ordinal', { ascending: true });
    if (itemResult.error) throw itemResult.error;
    const itemRows = rows(itemResult.data);
    const itemIds = itemRows.map((value) => uuid(exactRecord(
      value,
      ['id', 'ordinal', 'duration_sec', 'stratum', 'assigned_reviewer_id'],
    ).id));
    if (itemIds.length === 0) throw new Error('empty frozen batch');

    const [submissionRows, correctionRows, adjudicationRows, decisionRows] = await Promise.all([
      selectItemChildren(
        'gme_negative_audit_submissions',
        'id, item_id, reviewer_id, verdict, representative_sec, bbox, digest',
        itemIds,
      ),
      selectItemChildren(
        'gme_negative_audit_corrections',
        'id, item_id, original_submission_id, reviewer_id, verdict, representative_sec, bbox, expected_submission_digest, digest, created_at',
        itemIds,
      ),
      selectItemChildren(
        'gme_negative_audit_adjudications',
        'id, item_id, original_submission_id, owner_id, final_verdict, representative_sec, bbox, effective_submission_digest, digest',
        itemIds,
      ),
      selectItemChildren('gme_negative_audit_dataset_decisions', 'item_id', itemIds),
    ]);

    const items = new Map<string, PrivateItem>();
    for (const value of itemRows) {
      const row = exactRecord(value, ['id', 'ordinal', 'duration_sec', 'stratum', 'assigned_reviewer_id']);
      const id = uuid(row.id);
      const ordinal = count(row.ordinal);
      const stratum = row.stratum;
      if (ordinal < 1 || !['random_negative', 'positive_control'].includes(String(stratum))) throw new Error('item');
      if (items.has(id)) throw new Error('duplicate item');
      items.set(id, {
        id,
        ordinal,
        durationSec: positiveNumber(row.duration_sec),
        stratum: stratum as PrivateItem['stratum'],
        assignedReviewerId: uuid(row.assigned_reviewer_id),
      });
    }

    const submissions = new Map<string, { id: string; reviewerId: string; effective: Effective }>();
    for (const value of submissionRows) {
      const row = exactRecord(value, [
        'id', 'item_id', 'reviewer_id', 'verdict', 'representative_sec', 'bbox', 'digest',
      ]);
      const itemId = uuid(row.item_id);
      const item = items.get(itemId);
      if (!item || submissions.has(itemId)) throw new Error('submission item');
      const reviewerId = uuid(row.reviewer_id);
      if (reviewerId !== item.assignedReviewerId) throw new Error('assignment');
      const submission = validateAuditSubmission({
        verdict: row.verdict,
        representative_sec: nullableNumber(row.representative_sec),
        bbox: row.bbox,
      }, item.durationSec);
      submissions.set(itemId, {
        id: uuid(row.id),
        reviewerId,
        effective: { ...submission, digest: digest(row.digest) },
      });
    }

    for (const value of correctionRows) {
      const row = exactRecord(value, [
        'id', 'item_id', 'original_submission_id', 'reviewer_id', 'verdict',
        'representative_sec', 'bbox', 'expected_submission_digest', 'digest', 'created_at',
      ]);
      uuid(row.id);
      const itemId = uuid(row.item_id);
      const item = items.get(itemId);
      const submission = submissions.get(itemId);
      if (
        !item || !submission || row.original_submission_id !== submission.id ||
        row.reviewer_id !== submission.reviewerId || row.expected_submission_digest !== submission.effective.digest
      ) throw new Error('correction chain');
      const corrected = validateAuditSubmission({
        verdict: row.verdict,
        representative_sec: nullableNumber(row.representative_sec),
        bbox: row.bbox,
      }, item.durationSec);
      submission.effective = { ...corrected, digest: digest(row.digest) };
    }

    const adjudicated = new Set<string>();
    for (const value of adjudicationRows) {
      const row = exactRecord(value, [
        'id', 'item_id', 'original_submission_id', 'owner_id', 'final_verdict',
        'representative_sec', 'bbox', 'effective_submission_digest', 'digest',
      ]);
      uuid(row.id);
      const itemId = uuid(row.item_id);
      const item = items.get(itemId);
      const submission = submissions.get(itemId);
      if (
        !item || !submission || adjudicated.has(itemId) ||
        row.original_submission_id !== submission.id || row.owner_id !== access.userId ||
        row.effective_submission_digest !== submission.effective.digest
      ) throw new Error('adjudication');
      const finalVerdict = validateAuditSubmission({
        verdict: row.final_verdict,
        representative_sec: nullableNumber(row.representative_sec),
        bbox: row.bbox,
      }, item.durationSec);
      submission.effective = { ...finalVerdict, digest: digest(row.digest) };
      adjudicated.add(itemId);
    }

    const decided = new Set<string>();
    for (const value of decisionRows) {
      const row = exactRecord(value, ['item_id']);
      const itemId = uuid(row.item_id);
      if (!items.has(itemId) || decided.has(itemId)) throw new Error('dataset decision');
      decided.add(itemId);
    }

    const completedItems = Array.from(submissions.keys()).map((itemId) => items.get(itemId)!);
    const needsAdjudication = completedItems
      .filter((item) => {
        const submission = submissions.get(item.id)!;
        return submission.reviewerId !== access.userId
          && submission.effective.verdict !== 'gecko_absent'
          && !adjudicated.has(item.id);
      })
      .sort((left, right) => left.ordinal - right.ordinal)
      .map((item) => {
        const effective = submissions.get(item.id)!.effective;
        return {
          item_id: item.id,
          ordinal: item.ordinal,
          duration_sec: item.durationSec,
          stratum: item.stratum,
          effective_verdict: effective.verdict,
          effective_representative_sec: effective.representative_sec,
          effective_bbox: effective.bbox,
          expected_submission_digest: effective.digest,
        };
      });
    const datasetDecisionEligible = completedItems
      .filter((item) => {
        const submission = submissions.get(item.id)!;
        return item.stratum === 'random_negative' && !decided.has(item.id)
          && (submission.reviewerId === access.userId || adjudicated.has(item.id));
      })
      .sort((left, right) => left.ordinal - right.ordinal)
      .map((item) => {
        const effective = submissions.get(item.id)!.effective;
        return {
          item_id: item.id,
          ordinal: item.ordinal,
          duration_sec: item.durationSec,
          stratum: item.stratum,
          effective_verdict: effective.verdict,
          effective_representative_sec: effective.representative_sec,
          effective_bbox: effective.bbox,
          expected_effective_digest: effective.digest,
        };
      });
    return auditJson({
      batch_id: batchId,
      batch_state: 'opened',
      completed: completedItems.length,
      total,
      random_negative: {
        completed: completedItems.filter((item) => item.stratum === 'random_negative').length,
        total: negativeTotal,
      },
      positive_control: {
        completed: completedItems.filter((item) => item.stratum === 'positive_control').length,
        total: controlTotal,
      },
      needs_adjudication: needsAdjudication,
      dataset_decision_eligible: datasetDecisionEligible,
    });
  } catch {
    return auditUnavailable();
  }
}
