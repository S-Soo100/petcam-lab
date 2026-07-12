-- Allow "unseen" in router review labels.
-- Run after 2026-07-10_router_review_tables.sql if the original CHECK exists.

ALTER TABLE public.router_review_labels
  DROP CONSTRAINT IF EXISTS router_review_labels_manual_action_gt_check;

ALTER TABLE public.router_review_labels
  ADD CONSTRAINT router_review_labels_manual_action_gt_check
  CHECK (
    manual_action_gt IN (
      'moving',
      'static',
      'feeding',
      'drinking',
      'hidden',
      'unseen',
      'human_noise',
      'other'
    )
  );
