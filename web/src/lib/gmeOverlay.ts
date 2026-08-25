export type GmeOverlayProvenance = 'observed' | 'tracked' | 'interpolated';
export type GmeFeedbackKind = 'miss' | 'false_positive' | 'bad_box';

export interface GmeOverlayPoint {
  track_index: number;
  timestamp_sec: number;
  bbox_norm: [number, number, number, number];
  confidence: number;
  provenance: GmeOverlayProvenance;
}

export interface ParsedGmeOverlay {
  duration_sec: number;
  points: GmeOverlayPoint[];
}

export interface GmeOverlayResponse extends ParsedGmeOverlay {
  available: boolean;
  overlay_revision: string | null;
}

const DISPLAY_PROVENANCE = new Set<GmeOverlayProvenance>([
  'observed',
  'tracked',
  'interpolated',
]);
const ALL_PROVENANCE = new Set(['observed', 'tracked', 'interpolated', 'unknown']);
export const MAX_GME_OVERLAY_POINTS = 50_000;

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function finite(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`invalid ${label}`);
  }
  return value;
}

export function parseGmeOverlayArtifact(value: unknown): ParsedGmeOverlay {
  const root = record(value, 'artifact');
  if (root.schema_version !== 'gme-artifact-v1') throw new Error('unsupported GME artifact schema');
  record(root.artifact_identity, 'artifact identity');
  if (!Array.isArray(root.intervals)) throw new Error('invalid intervals');
  record(root.tracking_quality, 'tracking quality');

  const duration = finite(root.duration_sec, 'duration');
  if (duration < 0) throw new Error('invalid duration');
  if (!Array.isArray(root.track_points) || root.track_points.length > MAX_GME_OVERLAY_POINTS) {
    throw new Error('invalid track point count');
  }

  const rawPoints = root.track_points.map((raw, index) => {
    const point = record(raw, `track point ${index}`);
    if (typeof point.track_id !== 'string' || point.track_id.trim() === '' || point.track_id.length > 128) {
      throw new Error('invalid track id');
    }
    const timestamp = finite(point.timestamp_sec, 'track timestamp');
    if (timestamp < 0 || timestamp > duration + 0.001) throw new Error('track timestamp outside duration');
    const confidence = finite(point.confidence, 'track confidence');
    if (confidence < 0 || confidence > 1) throw new Error('invalid track confidence');
    if (typeof point.provenance !== 'string' || !ALL_PROVENANCE.has(point.provenance)) {
      throw new Error('invalid track provenance');
    }
    if (!Array.isArray(point.bbox_norm) || point.bbox_norm.length !== 4) {
      throw new Error('invalid bbox');
    }
    const bbox = point.bbox_norm.map((part) => finite(part, 'bbox')) as [number, number, number, number];
    const [x, y, width, height] = bbox;
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > 1.000001 || y + height > 1.000001) {
      throw new Error('bbox outside normalized frame');
    }
    return {
      trackId: point.track_id,
      timestamp,
      bbox,
      confidence,
      provenance: point.provenance,
    };
  });

  const trackIndexes = new Map(
    Array.from(new Set(rawPoints.map((point) => point.trackId)))
      .sort()
      .map((trackId, index) => [trackId, index]),
  );
  const points = rawPoints
    .filter((point) => DISPLAY_PROVENANCE.has(point.provenance as GmeOverlayProvenance))
    .map((point): GmeOverlayPoint => ({
      track_index: trackIndexes.get(point.trackId)!,
      timestamp_sec: point.timestamp,
      bbox_norm: point.bbox,
      confidence: point.confidence,
      provenance: point.provenance as GmeOverlayProvenance,
    }))
    .sort((a, b) => a.timestamp_sec - b.timestamp_sec || a.track_index - b.track_index);

  return { duration_sec: duration, points };
}

export function selectGmeOverlayPoints(
  points: GmeOverlayPoint[],
  currentTimeSec: number,
  toleranceSec = 0.25,
): GmeOverlayPoint[] {
  if (!Number.isFinite(currentTimeSec) || !Number.isFinite(toleranceSec) || toleranceSec < 0) return [];
  const nearest = new Map<number, { point: GmeOverlayPoint; distance: number }>();
  for (const point of points) {
    const distance = Math.abs(point.timestamp_sec - currentTimeSec);
    if (distance > toleranceSec) continue;
    const previous = nearest.get(point.track_index);
    if (!previous || distance < previous.distance) {
      nearest.set(point.track_index, { point, distance });
    }
  }
  return Array.from(nearest.values())
    .sort((a, b) => a.point.track_index - b.point.track_index)
    .map(({ point }) => point);
}
