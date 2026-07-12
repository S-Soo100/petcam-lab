# Codex dataset-203 model sweep

## Summary

- total records: 2
- successful records: 2
- error records: 0
- successful records without Codex usage JSON: 0

## Model x Representation

| model | prompt | repr | N | accuracy | avg input tok | avg sec | median sec |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.5 | compact | contact-sheet-96 | 1 | 0.0% | 21,274 | 10.53 | 10.53 |
| gpt-5.5 | v40 | frames-adaptive | 1 | 0.0% | 29,047 | 12.43 | 12.43 |

## Paired Reduction

| model | prompt | candidate | baseline prompt | token reduction | accuracy drop | speed delta sec |
|---|---:|---:|---:|---:|---:|---:|
| gpt-5.5 | compact | contact-sheet-96 | v40 | 26.8% | 0.00pp | -1.90 |

## Cascade Simulation

| model | primary | fallback | threshold | N | fallback rate | accuracy | token reduction | avg sec |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.5 | 1 | 0.0% | 0.0% | 26.8% | 10.53 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.6 | 1 | 0.0% | 0.0% | 26.8% | 10.53 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.7 | 1 | 0.0% | 0.0% | 26.8% | 10.53 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.8 | 1 | 0.0% | 0.0% | 26.8% | 10.53 |
| gpt-5.5 | compact/contact-sheet-96 | v40/frames-adaptive | 0.9 | 1 | 100.0% | 0.0% | -73.2% | 22.96 |

## Confusion

### gpt-5.5|compact|contact-sheet-96
- 1x drinking -> moving

### gpt-5.5|v40|frames-adaptive
- 1x drinking -> moving
