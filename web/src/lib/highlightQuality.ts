// owner 전용 집계 계약. raw row spread 없이 필요한 집계·버전만 전달해.
import { HIGHLIGHT_TRIGGERS, type HighlightTrigger } from './highlightV4';

type Obj = Record<string, unknown>;
function object(v: unknown): Obj {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('invalid_quality_row');
  return v as Obj;
}
function text(v: unknown): string {
  if (typeof v !== 'string' || !v) throw new Error('invalid_quality_text');
  return v;
}
function nullableText(v: unknown): string | null { return v === null ? null : text(v); }
function count(v: unknown): number {
  if (typeof v !== 'number' && !(typeof v === 'string' && /^\d+$/.test(v))) throw new Error('invalid_quality_count');
  const n = Number(v);
  if (!Number.isSafeInteger(n) || n < 0) throw new Error('invalid_quality_count');
  return n;
}
function identity(r: Obj) {
  return {
    rule_version: text(r.rule_version), camera_id: nullableText(r.camera_id), camera_name: nullableText(r.camera_name),
    activity_day: text(r.activity_day), engine_schema_version: nullableText(r.engine_schema_version),
    algorithm_version: nullableText(r.algorithm_version), detector_identity: nullableText(r.detector_identity),
  };
}
function ratio(n: number, d: number): number | null { return d ? n / d : null; }

export function mapHighlightQuality(raw: unknown) {
  const data = object(raw);
  if (!Array.isArray(data.rows) || !Array.isArray(data.shadow_rows)) throw new Error('invalid_quality_report');
  const rows = data.rows.map((v) => {
    const r = object(v);
    const counts = {
      reviewed_count: count(r.reviewed_count), o_to_o: count(r.o_to_o), o_to_x: count(r.o_to_x),
      x_to_o: count(r.x_to_o), x_to_x: count(r.x_to_x), pending_initial: count(r.pending_initial),
      failed_initial: count(r.failed_initial), correction_count: count(r.correction_count),
      technical_rejects: count(r.technical_rejects), preference_rejects: count(r.preference_rejects),
      other_rejects: count(r.other_rejects), missed_visibility: count(r.missed_visibility),
    };
    if (counts.reviewed_count !== counts.o_to_o + counts.o_to_x + counts.x_to_o + counts.x_to_x + counts.pending_initial + counts.failed_initial
        || counts.correction_count > counts.reviewed_count
        || counts.technical_rejects + counts.preference_rejects + counts.other_rejects !== counts.o_to_x
        || counts.missed_visibility > counts.reviewed_count) throw new Error('invalid_quality_totals');
    return {...identity(r), ...counts,
      o_acceptance: ratio(counts.o_to_o, counts.o_to_o + counts.o_to_x),
      x_miss_rate: ratio(counts.x_to_o, counts.x_to_o + counts.x_to_x)};
  });
  const shadow_rows = data.shadow_rows.map((v) => {
    const r = object(v);
    const trigger = text(r.trigger_name);
    if (!(HIGHLIGHT_TRIGGERS as readonly string[]).includes(trigger)) throw new Error('invalid_quality_trigger');
    const additional_count = count(r.additional_count), human_o = count(r.human_o);
    if (human_o > additional_count) throw new Error('invalid_quality_totals');
    return {...identity(r), trigger_name: trigger as HighlightTrigger, additional_count, human_o,
      acceptance: ratio(human_o, additional_count)};
  });
  return {rows, shadow_rows};
}
export type HighlightQuality = ReturnType<typeof mapHighlightQuality>;
