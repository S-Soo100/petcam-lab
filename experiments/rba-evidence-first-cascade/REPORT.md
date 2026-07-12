# RBA Evidence-First Cascade Report

## Decision

Decision: `adopt_preprocessor_first_hold_auto_label`

This is a separate strategy from SegmentVLM and contact-sheet token reduction. It tests whether non-VLM video evidence can safely reduce VLM calls before semantic judgment.

## Chosen Rule

- rule: `no-auto`
- split: `holdout`
- N: 60
- non-VLM rate: 0.0%
- fallback rate: 100.0%
- false auto-label rate: 0.0%
- accuracy drop: 0.00pp
- token reduction vs 120k direct: 83.6%
- token reduction vs v40 frames: 0.0%

## Preprocessor-First Baseline

This measures the part of the strategy that is already safe: Python/OpenCV handles video decoding and frame selection, then VLM sees adaptive frames instead of a high-token direct video input.

- token reduction vs 120k direct: 83.6%
- expected avg input tokens: 19730
- accuracy drop vs fallback baseline: 0.00pp

## All Runs

| split | rule | N | non-VLM | false auto | accuracy drop | vs 120k reduction | vs v40 reduction |
|---|---:|---:|---:|---:|---:|---:|---:|
| train | `conservative-v0` | 137 | 6.6% | 77.8% | 5.11pp | 84.6% | 6.6% |
| train | `no-auto` | 137 | 0.0% | 0.0% | 0.00pp | 83.6% | 0.0% |
| holdout | `conservative-v0` | 60 | 5.0% | 66.7% | 3.33pp | 84.4% | 5.0% |
| holdout | `no-auto` | 60 | 0.0% | 0.0% | 0.00pp | 83.6% | 0.0% |
| all | `conservative-v0` | 197 | 6.1% | 75.0% | 4.57pp | 84.6% | 6.1% |
| all | `no-auto` | 197 | 0.0% | 0.0% | 0.00pp | 83.6% | 0.0% |

## Interpretation

The broader goal is partially achieved by moving video decoding, frame selection, and evidence extraction outside the VLM: the v40 adaptive-frame fallback costs 19730 input tokens/clip versus a 120k direct-video baseline (83.6% reduction) while preserving the v40 accuracy baseline. However, OpenCV-only auto-labeling is not safe enough yet. Keep auto-label routing on hold until detector evidence adds gecko presence and object/ROI cues.

## Class Distribution

```json
{
  "drinking": 24,
  "eating_paste": 19,
  "eating_prey": 22,
  "hand_feeding": 29,
  "moving": 72,
  "shedding": 29,
  "unseen": 2
}
```
