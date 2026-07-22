# B1R Python Evidence Coverage (SELECT-only)

- coverage_verdict: **COVERAGE_OPEN**
- evidence identity: `python-evidence-raw-v1` / `croi-temporal-v1`
- cutoff_started_at: `2026-07-22T02:45:33+00:00`
- query_watermark: `2026-07-22T03:33:45.551380+00:00`
- range: 2026-06-17 .. 2026-07-22

## 완료 등식

```text
eligible                    = 16786
succeeded_with_active_run   = 2841
allowlisted_terminal        = 0
accounted (succ+terminal)   = 2841
queued/processing/retryable = 0/0/0 (open=0)
silent_missing              = 13945
```

- eligible == succeeded + terminal ? **False**
- silent_missing == 0 ? **False** · open == 0 ? **True**
- terminal_by_code: -
- camera 수: 3 · date 수: 27
