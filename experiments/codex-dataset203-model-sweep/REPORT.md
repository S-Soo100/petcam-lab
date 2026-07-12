# Codex dataset-203 model sweep

## Summary

- total records: 9
- successful records: 7
- error records: 2
- successful records without Codex usage JSON: 0

## Model x Representation

| model | prompt | repr | N | accuracy | avg input tok | avg sec | median sec |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.4-mini | compact | contact-sheet-96 | 1 | 0.0% | 62,148 | 65.85 | 65.85 |
| gpt-5.4-mini | v40 | frames-adaptive | 1 | 0.0% | 27,361 | 22.87 | 22.87 |
| gpt-5.5 | compact | contact-sheet-120 | 1 | 0.0% | 21,638 | 16.87 | 16.87 |
| gpt-5.5 | compact | contact-sheet-180 | 1 | 0.0% | 22,792 | 13.89 | 13.89 |
| gpt-5.5 | compact | contact-sheet-96 | 1 | 0.0% | 21,280 | 15.01 | 15.01 |
| gpt-5.5 | v40 | contact-sheet | 1 | 0.0% | 26,486 | 16.98 | 16.98 |
| gpt-5.5 | v40 | frames-adaptive | 1 | 100.0% | 29,097 | 19.80 | 19.80 |

## Paired Reduction

| model | prompt | candidate | baseline prompt | token reduction | accuracy drop | speed delta sec |
|---|---:|---:|---:|---:|---:|---:|
| gpt-5.4-mini | compact | contact-sheet-96 | v40 | -127.1% | 0.00pp | 42.98 |
| gpt-5.5 | compact | contact-sheet-120 | v40 | 25.6% | 100.00pp | -2.92 |
| gpt-5.5 | compact | contact-sheet-180 | v40 | 21.7% | 100.00pp | -5.90 |
| gpt-5.5 | compact | contact-sheet-96 | v40 | 26.9% | 100.00pp | -4.79 |
| gpt-5.5 | v40 | contact-sheet | v40 | 9.0% | 100.00pp | -2.82 |

## Cascade Simulation

| model | primary | fallback | threshold | N | fallback rate | accuracy | token reduction | avg sec |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.4-mini | compact/contact-sheet-96 | v40/frames-adaptive | 0.5 | 1 | 0.0% | 0.0% | -127.1% | 65.85 |
| gpt-5.4-mini | compact/contact-sheet-96 | v40/frames-adaptive | 0.6 | 1 | 0.0% | 0.0% | -127.1% | 65.85 |
| gpt-5.4-mini | compact/contact-sheet-96 | v40/frames-adaptive | 0.7 | 1 | 0.0% | 0.0% | -127.1% | 65.85 |
| gpt-5.4-mini | compact/contact-sheet-96 | v40/frames-adaptive | 0.8 | 1 | 0.0% | 0.0% | -127.1% | 65.85 |
| gpt-5.4-mini | compact/contact-sheet-96 | v40/frames-adaptive | 0.9 | 1 | 100.0% | 0.0% | -227.1% | 88.73 |
| gpt-5.5 | compact/contact-sheet-120 | v40/frames-adaptive | 0.5 | 1 | 0.0% | 0.0% | 25.6% | 16.87 |
| gpt-5.5 | compact/contact-sheet-120 | v40/frames-adaptive | 0.6 | 1 | 0.0% | 0.0% | 25.6% | 16.87 |
| gpt-5.5 | compact/contact-sheet-120 | v40/frames-adaptive | 0.7 | 1 | 0.0% | 0.0% | 25.6% | 16.87 |
| gpt-5.5 | compact/contact-sheet-120 | v40/frames-adaptive | 0.8 | 1 | 100.0% | 100.0% | -74.4% | 36.67 |
| gpt-5.5 | compact/contact-sheet-120 | v40/frames-adaptive | 0.9 | 1 | 100.0% | 100.0% | -74.4% | 36.67 |
| gpt-5.5 | compact/contact-sheet-180 | v40/frames-adaptive | 0.5 | 1 | 0.0% | 0.0% | 21.7% | 13.89 |
| gpt-5.5 | compact/contact-sheet-180 | v40/frames-adaptive | 0.6 | 1 | 0.0% | 0.0% | 21.7% | 13.89 |
| gpt-5.5 | compact/contact-sheet-180 | v40/frames-adaptive | 0.7 | 1 | 0.0% | 0.0% | 21.7% | 13.89 |
| gpt-5.5 | compact/contact-sheet-180 | v40/frames-adaptive | 0.8 | 1 | 0.0% | 0.0% | 21.7% | 13.89 |
| gpt-5.5 | compact/contact-sheet-180 | v40/frames-adaptive | 0.9 | 1 | 100.0% | 100.0% | -78.3% | 33.69 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.5 | 1 | 0.0% | 0.0% | 26.9% | 15.01 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.6 | 1 | 0.0% | 0.0% | 26.9% | 15.01 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.7 | 1 | 0.0% | 0.0% | 26.9% | 15.01 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.8 | 1 | 0.0% | 0.0% | 26.9% | 15.01 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.9 | 1 | 100.0% | 100.0% | -73.1% | 34.80 |
| gpt-5.5 | v40/contact-sheet | v40/frames-adaptive | 0.5 | 1 | 0.0% | 0.0% | 9.0% | 16.98 |
| gpt-5.5 | v40/contact-sheet | v40/frames-adaptive | 0.6 | 1 | 0.0% | 0.0% | 9.0% | 16.98 |
| gpt-5.5 | v40/contact-sheet | v40/frames-adaptive | 0.7 | 1 | 0.0% | 0.0% | 9.0% | 16.98 |
| gpt-5.5 | v40/contact-sheet | v40/frames-adaptive | 0.8 | 1 | 0.0% | 0.0% | 9.0% | 16.98 |
| gpt-5.5 | v40/contact-sheet | v40/frames-adaptive | 0.9 | 1 | 100.0% | 100.0% | -91.0% | 36.78 |

## Confusion

### gpt-5.5|v40|contact-sheet
- 1x drinking -> moving

### gpt-5.4-mini|compact|contact-sheet-96
- 1x drinking -> moving

### gpt-5.4-mini|v40|frames-adaptive
- 1x drinking -> moving

### gpt-5.5|compact|contact-sheet-120
- 1x drinking -> moving

### gpt-5.5|compact|contact-sheet-180
- 1x drinking -> moving

### gpt-5.5|compact|contact-sheet-96
- 1x drinking -> moving
