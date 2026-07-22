# B1R2 R2 Media Availability (SELECT + R2 list, read-only)

- evidence identity: `python-evidence-raw-v1` / `croi-temporal-v1`
- cutoff_started_at: `2026-07-22T02:45:33+00:00`
- r2_prefix: `terra-clips/clips/`

## study_total 5-상태 partition

```text
study_total            = 16786
evidence_succeeded     = 2841
media_available_open   = 0
media_available_silent = 13837
media_available_terminal = 0
source_expired         = 108
```

- 합계 등식 성립 ? **True**
- recoverable_total (study−expired) = 16678
- recoverable_coverage_closed (open==0 ∧ silent==0) ? **False**
- availability_sha256: `e69baec9429ef83f274940bd9aa1b05e16de4bb9b79ab056d6190d2e810c8fe3`

## R2 inventory

```text
prefix        = terra-clips/clips/
object_count  = 33433
mp4_available = 16729
total_bytes   = 56045791280
page_count    = 34
started_at    = 2026-07-22T07:45:10.010295+00:00
finished_at   = 2026-07-22T07:45:28.276586+00:00
```

## camera/date 별 available vs source_expired

| camera|date | available | source_expired |
|---|---:|---:|
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-06-17 | 0 | 21 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-06-22 | 2 | 10 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-06-23 | 284 | 1 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-01 | 32 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-02 | 24 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-03 | 642 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-04 | 666 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-05 | 135 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-06 | 464 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-07 | 906 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-08 | 1123 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-09 | 893 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-10 | 1016 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-11 | 1189 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-12 | 1048 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-13 | 1068 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-14 | 728 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-15 | 1206 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-16 | 800 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-17 | 498 | 0 |
| 90119209-4cdf-46f0-a151-c16d2445a1f1|2026-07-14 | 7 | 27 |
| 90119209-4cdf-46f0-a151-c16d2445a1f1|2026-07-15 | 3 | 0 |
| 90119209-4cdf-46f0-a151-c16d2445a1f1|2026-07-16 | 53 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-06-23 | 0 | 4 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-06-24 | 0 | 1 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-06-30 | 306 | 7 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-02 | 76 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-03 | 131 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-04 | 136 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-05 | 76 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-06 | 6 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-13 | 0 | 12 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-14 | 0 | 25 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-16 | 190 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-17 | 129 | 0 |

## bounded HEAD 표본 (inventory 교차확인)

```text
available: checked=173 present=173 mismatch=0
expired:   checked=42 absent=42 mismatch=0
mismatch_total = 0
```
