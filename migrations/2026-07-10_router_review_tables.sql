-- Router review dashboard tables.
-- Purpose: keep router validation separate from behavior GT labels.

CREATE TABLE IF NOT EXISTS public.router_review_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id TEXT NOT NULL,
  clip_id UUID NOT NULL REFERENCES public.camera_clips(id) ON DELETE CASCADE,
  sample_group TEXT NOT NULL,
  route TEXT NOT NULL CHECK (route IN ('cloud_now', 'cloud_later', 'activity_only', 'review_candidate')),
  risk TEXT NOT NULL CHECK (risk IN ('low', 'medium', 'high')),
  reason TEXT NOT NULL,
  priority REAL NOT NULL,
  camera_id UUID NULL,
  started_at TIMESTAMPTZ NULL,
  evidence_reliability TEXT NULL CHECK (
    evidence_reliability IS NULL OR evidence_reliability IN ('low', 'medium', 'high')
  ),
  motion_mean DOUBLE PRECISION NULL,
  motion_peak DOUBLE PRECISION NULL,
  active_motion_ratio DOUBLE PRECISION NULL,
  motion_burst_count INTEGER NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (batch_id, clip_id)
);

CREATE INDEX IF NOT EXISTS idx_router_review_items_batch_id
  ON public.router_review_items (batch_id);

CREATE INDEX IF NOT EXISTS idx_router_review_items_batch_group
  ON public.router_review_items (batch_id, sample_group);

CREATE INDEX IF NOT EXISTS idx_router_review_items_clip_id
  ON public.router_review_items (clip_id);

CREATE TABLE IF NOT EXISTS public.router_review_labels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  review_item_id UUID NOT NULL REFERENCES public.router_review_items(id) ON DELETE CASCADE,
  clip_id UUID NOT NULL REFERENCES public.camera_clips(id) ON DELETE CASCADE,
  reviewed_by UUID NOT NULL,
  manual_visible_gecko TEXT NOT NULL CHECK (manual_visible_gecko IN ('yes', 'no', 'unclear')),
  manual_action_gt TEXT NOT NULL CHECK (
    manual_action_gt IN ('moving', 'static', 'feeding', 'drinking', 'hidden', 'human_noise', 'other')
  ),
  manual_router_ok TEXT NOT NULL CHECK (manual_router_ok IN ('yes', 'no', 'unclear')),
  manual_notes TEXT NULL,
  reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (review_item_id, reviewed_by)
);

CREATE INDEX IF NOT EXISTS idx_router_review_labels_review_item_id
  ON public.router_review_labels (review_item_id);

CREATE INDEX IF NOT EXISTS idx_router_review_labels_clip_id
  ON public.router_review_labels (clip_id);

CREATE INDEX IF NOT EXISTS idx_router_review_labels_reviewed_by
  ON public.router_review_labels (reviewed_by);

ALTER TABLE public.router_review_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.router_review_labels ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS router_review_items_select ON public.router_review_items;
CREATE POLICY router_review_items_select ON public.router_review_items
  FOR SELECT
  USING (
    auth.uid() IS NOT NULL
    AND (
      EXISTS (SELECT 1 FROM public.labelers WHERE labelers.user_id = auth.uid())
      OR EXISTS (
        SELECT 1
        FROM public.camera_clips
        WHERE camera_clips.id = router_review_items.clip_id
          AND camera_clips.user_id = auth.uid()
      )
    )
  );

DROP POLICY IF EXISTS router_review_labels_select ON public.router_review_labels;
CREATE POLICY router_review_labels_select ON public.router_review_labels
  FOR SELECT
  USING (
    reviewed_by = auth.uid()
    OR EXISTS (
      SELECT 1
      FROM public.camera_clips
      WHERE camera_clips.id = router_review_labels.clip_id
        AND camera_clips.user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS router_review_labels_insert ON public.router_review_labels;
CREATE POLICY router_review_labels_insert ON public.router_review_labels
  FOR INSERT
  WITH CHECK (reviewed_by = auth.uid());

DROP POLICY IF EXISTS router_review_labels_update ON public.router_review_labels;
CREATE POLICY router_review_labels_update ON public.router_review_labels
  FOR UPDATE
  USING (reviewed_by = auth.uid())
  WITH CHECK (reviewed_by = auth.uid());

COMMENT ON TABLE public.router_review_items IS
  'Router validation queue. Stores fixed sampled router decision snapshots by batch.';

COMMENT ON TABLE public.router_review_labels IS
  'Human review results for router decisions. Separate from behavior_labels GT.';
