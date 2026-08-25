-- A batch may close only after every frozen item has exactly one submission.
-- This is a forward migration because the original audit ledger is already in use.
CREATE OR REPLACE FUNCTION public.fn_validate_gme_negative_audit_batch_event()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  batch public.gme_negative_audit_batches%ROWTYPE;
  previous_event text;
BEGIN
  SELECT * INTO batch FROM public.gme_negative_audit_batches current_batch
  WHERE current_batch.id = NEW.batch_id FOR UPDATE;
  IF NOT FOUND OR batch.owner_id <> NEW.actor_id THEN
    RAISE EXCEPTION 'batch_event_owner_forbidden' USING ERRCODE = 'PT403';
  END IF;
  SELECT event.event_type INTO previous_event
  FROM public.gme_negative_audit_batch_events event
  WHERE event.batch_id = NEW.batch_id
  ORDER BY event.created_at DESC, event.id DESC LIMIT 1;
  IF (
    (NEW.event_type = 'prepared' AND previous_event IS NULL)
    OR (NEW.event_type = 'opened' AND previous_event = 'prepared')
    OR (NEW.event_type = 'closed' AND previous_event = 'opened')
    OR (NEW.event_type = 'scored' AND previous_event = 'closed')
    OR (NEW.event_type = 'invalidated' AND previous_event IN ('prepared','opened','closed'))
  ) IS NOT TRUE THEN
    RAISE EXCEPTION 'invalid_batch_event_transition' USING ERRCODE = '22023';
  END IF;
  IF NEW.event_type = 'closed' AND (
    (SELECT count(*)
     FROM public.gme_negative_audit_items item
     WHERE item.batch_id = NEW.batch_id) <> batch.expected_total_count
    OR
    (SELECT count(*)
     FROM public.gme_negative_audit_items item
     JOIN public.gme_negative_audit_submissions submission ON submission.item_id = item.id
     WHERE item.batch_id = NEW.batch_id) <> batch.expected_total_count
  ) THEN
    RAISE EXCEPTION 'batch_incomplete' USING ERRCODE = 'PT409';
  END IF;
  IF NEW.reason IS DISTINCT FROM btrim(NEW.reason) THEN
    RAISE EXCEPTION 'batch_event_reason_not_canonical' USING ERRCODE = '22023';
  END IF;
  IF NEW.digest IS DISTINCT FROM public.fn_gme_negative_audit_ledger_digest(ARRAY[
    NEW.id::text, NEW.batch_id::text, NEW.event_type, NEW.actor_id::text,
    coalesce(NEW.reason, 'null')
  ]) THEN
    RAISE EXCEPTION 'batch_event_digest_mismatch' USING ERRCODE = '22023';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_validate_gme_negative_audit_batch_event()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_validate_gme_negative_audit_batch_event() TO service_role;
