# B1R2 R2 Media Availability (SELECT + R2 list, read-only)

- evidence identity: `python-evidence-raw-v1` / `croi-temporal-v1`
- cutoff_started_at: `2026-07-22T02:45:33+00:00`
- r2_prefix: `terra-clips/clips/`

## study_total 5-상태 partition

```text
study_total            = 16786
evidence_succeeded     = 2990
media_available_open   = 381
media_available_silent = 13307
media_available_terminal = 0
source_expired         = 108
```

- 합계 등식 성립 ? **True**
- recoverable_total (study−expired) = 16678
- recoverable_coverage_closed (open==0 ∧ silent==0) ? **False**
- availability_sha256: `617adee28c6780917009bc3e66f603d34ab329583fccd5de7b588ee79f4bc264`

## R2 inventory

```text
prefix        = terra-clips/clips/
object_count  = 33437
mp4_available = 16731
total_bytes   = 56062939757
page_count    = 34
started_at    = 2026-07-22T08:50:16.138610+00:00
finished_at   = 2026-07-22T08:50:33.822864+00:00
```

## camera/date 별 available vs source_expired

| camera|date | available | source_expired |
|---|---:|---:|
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-06-17 | 0 | 21 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-06-22 | 1 | 10 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-06-23 | 282 | 1 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-01 | 31 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-02 | 23 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-03 | 636 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-04 | 660 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-05 | 134 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-06 | 458 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-07 | 892 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-08 | 1110 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-09 | 887 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-10 | 1009 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-11 | 1176 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-12 | 1039 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-13 | 1056 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-14 | 720 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-15 | 1192 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-16 | 792 | 0 |
| 5b3ea7aa-b4a7-4146-8f48-caf69e29e49c|2026-07-17 | 495 | 0 |
| 90119209-4cdf-46f0-a151-c16d2445a1f1|2026-07-14 | 6 | 27 |
| 90119209-4cdf-46f0-a151-c16d2445a1f1|2026-07-15 | 2 | 0 |
| 90119209-4cdf-46f0-a151-c16d2445a1f1|2026-07-16 | 52 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-06-23 | 0 | 4 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-06-24 | 0 | 1 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-06-30 | 305 | 7 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-02 | 74 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-03 | 128 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-04 | 133 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-05 | 75 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-06 | 5 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-13 | 0 | 12 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-14 | 0 | 25 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-16 | 187 | 0 |
| f6599924-d133-4562-a48c-a06ff59db29d|2026-07-17 | 128 | 0 |
