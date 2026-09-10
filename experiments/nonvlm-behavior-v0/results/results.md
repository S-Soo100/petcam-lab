# nonvlm-behavior-v0 채점 결과 (자동 생성)

- paired(185 동결 기준) n = 185 · 전체 측정 n = 197
- **decision_B = `reject`** (§9 룰)

## 게이트 (§7)

| 게이트 | 판정 | 값 |
|---|---|---|
| G_B1_moving_recall ≥0.90 | ❌ | 46/72 = 63.9% |
| G_B2_hand_feeding_recall ≥0.80 | ❌ | 10/28 = 35.7% |
| G_B3_feeding_recall_vs_A (−10%p) | ❌ | B 0/32 = 0.0% vs A 26/32 = 81.2% |
| G_B4_feeding_fp ≤10% | ✅ | 0/153 = 0.0% |
| G_C (C 급여경계 ≥ A AND recovered ≥ broken) | ❌ | acc A 86.5% / C 72.4% · recovered 1 / broken 27 |

## 정확도

- 급여경계: A 86.5% · B 31.9% · C 72.4%
- B raw(6-class, 급여 묶음): paired 31.9% · 전체 29.9%
- 분류기 arm(그룹 LOO CV, 상한): 20.0%

## A↔B 상보성 (complementarity, 급여경계 기준)

| both | A만 정답 | B만 정답 | 둘 다 오답 |
|---|---|---|---|
| 55 | 105 | 4 | 21 |

## 클래스별 (B, 급여 묶음)

| 클래스 | recall | precision | 혼동 |
|---|---|---|---|
| moving | 46/72 | 38% | {'shedding': 21, 'moving': 46, 'hand_feeding': 3, 'unseen': 2} |
| feeding | 0/32 | — | {'shedding': 5, 'hand_feeding': 2, 'unseen': 3, 'moving': 22} |
| shedding | 3/29 | 9% | {'moving': 20, 'hand_feeding': 5, 'shedding': 3, 'unseen': 1} |
| hand_feeding | 10/28 | 43% | {'moving': 13, 'hand_feeding': 10, 'shedding': 4, 'unseen': 1} |
| eating_prey | 0/22 | — | {'moving': 17, 'hand_feeding': 3, 'unseen': 1, 'shedding': 1} |
| unseen | 0/2 | 0% | {'moving': 2} |

## 클래스별 (A = v4.0 Sonnet, 7-class)

| 클래스 | recall | precision |
|---|---|---|
| moving | 68/72 | 78% |
| shedding | 26/29 | 93% |
| hand_feeding | 27/28 | 100% |
| eating_prey | 13/22 | 93% |
| eating_paste | 14/17 | 100% |
| drinking | 11/15 | 79% |
| unseen | 0/2 | 0% |

## C paired (A→C)

- [recovered] `hand_feeding__moving__e0e38e0c.mp4` GT=hand_feeding: eating_prey → hand_feeding
- [broken] `drinking__drinking__3d46364a.mov` GT=drinking: drinking → moving
- [broken] `drinking__drinking__6d9d504f.mov` GT=drinking: drinking → moving
- [broken] `drinking__drinking__c9bc5878.mov` GT=drinking: drinking → moving
- [broken] `drinking__eating_paste__71889c3c.mp4` GT=drinking: drinking → moving
- [broken] `drinking__moving__6a24c2e6.mp4` GT=drinking: drinking → moving
- [broken] `drinking__moving__bf83c4cf.mp4` GT=drinking: drinking → moving
- [broken] `drinking__moving__d95e9eaa.mp4` GT=drinking: drinking → moving
- [broken] `eating_paste__eating_paste__2c5c4fc6.mov` GT=eating_paste: eating_paste → moving
- [broken] `eating_paste__eating_paste__5a907d7b.mp4` GT=eating_paste: eating_paste → moving
- [broken] `eating_paste__eating_paste__7f4dbdcc.mp4` GT=eating_paste: eating_paste → moving
- [broken] `eating_paste__eating_paste__8329c627.mov` GT=eating_paste: eating_paste → moving
- [broken] `eating_paste__eating_paste__bae3a9e3.mov` GT=eating_paste: eating_paste → moving
- [broken] `eating_paste__eating_paste__c33da2d9.mov` GT=eating_paste: eating_paste → moving
- [broken] `eating_paste__eating_paste__ce6643fc.mov` GT=eating_paste: eating_paste → moving
- [broken] `eating_paste__eating_paste__f3154209.mov` GT=eating_paste: eating_paste → moving
- [broken] `eating_paste__moving__165f593f.mov` GT=eating_paste: eating_paste → moving
- [broken] `eating_prey__eating_prey__9cb5ffab.mov` GT=eating_prey: eating_prey → hand_feeding
- [broken] `eating_prey__eating_prey__caf661e0.mov` GT=eating_prey: eating_prey → hand_feeding
- [broken] `eating_prey__moving__b9656d30.mp4` GT=eating_prey: eating_prey → hand_feeding
- [broken] `moving__moving__08ec5a50.mp4` GT=moving: moving → hand_feeding
- [broken] `moving__moving__5477a71a.mp4` GT=moving: moving → hand_feeding
- [broken] `moving__moving__f8ffab0a.mp4` GT=moving: moving → hand_feeding
- [broken] `shedding__na__0525472f.mp4` GT=shedding: shedding → hand_feeding
- [broken] `shedding__na__0e7bccb0.mp4` GT=shedding: shedding → hand_feeding
- [broken] `shedding__na__9c871834.mp4` GT=shedding: shedding → hand_feeding
- [broken] `shedding__na__ba39511a.mp4` GT=shedding: shedding → hand_feeding
- [broken] `shedding__na__d83eacae.mp4` GT=shedding: shedding → hand_feeding

## Discordant review 후보 — A↔B 급여경계 정오 불일치 109건 (owner 육안, 최대 20건 권장)

| 파일 | GT | A(v4.0) | B(룰 v0) | 정답 쪽 |
|---|---|---|---|---|
| `drinking__drinking__036a650d.mov` | drinking | drinking | shedding | A |
| `drinking__drinking__2c1be3dd.mov` | drinking | drinking | shedding | A |
| `drinking__drinking__3d46364a.mov` | drinking | drinking | hand_feeding | A |
| `drinking__drinking__6d9d504f.mov` | drinking | drinking | shedding | A |
| `drinking__drinking__c9bc5878.mov` | drinking | drinking | unseen | A |
| `drinking__eating_paste__71889c3c.mp4` | drinking | drinking | moving | A |
| `drinking__moving__00c089c8.mov` | drinking | drinking | moving | A |
| `moving__moving__05da625c.mp4` | moving | moving | shedding | A |
| `moving__moving__2420abd8.mp4` | moving | moving | shedding | A |
| `drinking__moving__3369d723.mp4` | drinking | drinking | moving | A |
| `drinking__moving__6a24c2e6.mp4` | drinking | drinking | moving | A |
| `moving__moving__987c7b5d.mp4` | moving | moving | shedding | A |
| `drinking__moving__bf83c4cf.mp4` | drinking | drinking | moving | A |
| `drinking__moving__d95e9eaa.mp4` | drinking | drinking | moving | A |
| `moving__moving__ff1ecb03.mp4` | moving | moving | shedding | A |
| `eating_paste__eating_paste__2c5c4fc6.mov` | eating_paste | eating_paste | shedding | A |
| `eating_paste__eating_paste__5a907d7b.mp4` | eating_paste | eating_paste | moving | A |
| `eating_paste__eating_paste__5e46192e.mov` | eating_paste | eating_paste | moving | A |
| `hand_feeding__eating_paste__69c4badd.mp4` | hand_feeding | hand_feeding | moving | A |
| `eating_paste__eating_paste__6ecd693c.mp4` | eating_paste | eating_paste | moving | A |
| `eating_paste__eating_paste__7f4dbdcc.mp4` | eating_paste | eating_paste | moving | A |
| `eating_paste__eating_paste__8329c627.mov` | eating_paste | eating_paste | moving | A |
| `eating_paste__eating_paste__bae3a9e3.mov` | eating_paste | eating_paste | moving | A |
| `eating_paste__eating_paste__c33da2d9.mov` | eating_paste | eating_paste | hand_feeding | A |
| `eating_paste__eating_paste__c711cce8.mp4` | eating_paste | eating_paste | shedding | A |
| `eating_paste__eating_paste__ce6643fc.mov` | eating_paste | eating_paste | moving | A |
| `eating_paste__eating_paste__f3154209.mov` | eating_paste | eating_paste | moving | A |
| `eating_paste__moving__165f593f.mov` | eating_paste | eating_paste | unseen | A |
| `eating_paste__moving__1ef6f35c.mp4` | eating_paste | eating_paste | moving | A |
| `eating_paste__moving__3abc83bc.mov` | eating_paste | drinking | moving | A |
| `eating_paste__moving__6ae2b999.mov` | eating_paste | eating_paste | moving | A |
| `eating_prey__eating_prey__3ee98f36.mov` | eating_prey | eating_prey | moving | A |
| `eating_prey__eating_prey__5d52f088.mp4` | eating_prey | eating_prey | moving | A |
| `eating_prey__eating_prey__8dcf1496.mp4` | eating_prey | eating_prey | moving | A |
| `eating_prey__eating_prey__9677f91a.mov` | eating_prey | eating_prey | moving | A |
| `eating_prey__eating_prey__9cb5ffab.mov` | eating_prey | eating_prey | hand_feeding | A |
| `eating_prey__eating_prey__ba91ec72.mov` | eating_prey | eating_prey | moving | A |
| `eating_prey__eating_prey__caf661e0.mov` | eating_prey | eating_prey | hand_feeding | A |
| `eating_prey__eating_prey__e361d6a3.mov` | eating_prey | eating_prey | unseen | A |
| `eating_prey__moving__3ab3bce6.mov` | eating_prey | eating_prey | moving | A |
| `moving__moving__458e8aa7.mp4` | moving | moving | shedding | A |
| `eating_prey__moving__496d4ef4.mp4` | eating_prey | eating_prey | moving | A |
| `eating_prey__moving__b9656d30.mp4` | eating_prey | eating_prey | hand_feeding | A |
| `eating_prey__moving__c006c954.mp4` | eating_prey | eating_prey | moving | A |
| `eating_prey__moving__d70cebe1.mp4` | eating_prey | eating_prey | moving | A |
| `hand_feeding__moving__e0e38e0c.mp4` | hand_feeding | eating_prey | hand_feeding | B |
| `hand_feeding__moving__ea36897b.mp4` | hand_feeding | hand_feeding | shedding | A |
| `hand_feeding__hand_feeding__0d78637c.mov` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__hand_feeding__16b1a2b7.mov` | hand_feeding | hand_feeding | unseen | A |
| `hand_feeding__hand_feeding__1b3627ee.mov` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__hand_feeding__41aecaea.mp4` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__hand_feeding__49458257.mp4` | hand_feeding | hand_feeding | shedding | A |
| `hand_feeding__hand_feeding__922f4cf5.mov` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__hand_feeding__a6512b97.mov` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__hand_feeding__acc2beed.mov` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__hand_feeding__c928b6ff.mp4` | hand_feeding | hand_feeding | shedding | A |
| `hand_feeding__hand_feeding__cc0c1d04.mp4` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__hand_feeding__cd2365f5.mov` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__moving__219014f2.mov` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__moving__27c5b14f.mp4` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__moving__5cfe1d48.mp4` | hand_feeding | hand_feeding | moving | A |
| `hand_feeding__moving__c3fb52f7.mov` | hand_feeding | hand_feeding | shedding | A |
| `hand_feeding__moving__ce5fee73.mp4` | hand_feeding | hand_feeding | moving | A |
| `moving__na__556a7bfe.mp4` | moving | moving | shedding | A |
| `moving__na__8899146c.mp4` | moving | moving | shedding | A |
| `moving__drinking__48b5582e.mp4` | moving | shedding | moving | B |
| `moving__moving__0677794b.mp4` | moving | moving | shedding | A |
| `moving__moving__08ec5a50.mp4` | moving | moving | hand_feeding | A |
| `moving__moving__0ce3cc59.mp4` | moving | unseen | moving | B |
| `moving__moving__1cd320c4.mp4` | moving | moving | shedding | A |
| `moving__moving__377567ac.mp4` | moving | moving | shedding | A |
| `moving__moving__3e51c7ed.mp4` | moving | moving | shedding | A |
| `moving__moving__5477a71a.mp4` | moving | moving | hand_feeding | A |
| `moving__moving__6eaea082.mp4` | moving | moving | shedding | A |
| `moving__moving__76a24e8b.mp4` | moving | moving | shedding | A |
| `moving__moving__78d6736e.mp4` | moving | moving | shedding | A |
| `moving__moving__8a629097.mp4` | moving | moving | shedding | A |
| `moving__moving__95502679.mp4` | moving | moving | unseen | A |
| `moving__moving__9ad8d159.mp4` | moving | moving | shedding | A |
| `moving__moving__a3a453c3.mov` | moving | drinking | moving | B |
| `moving__moving__aaafbe3f.mp4` | moving | moving | shedding | A |
| `moving__moving__b8680579.mp4` | moving | moving | shedding | A |
| `moving__moving__bd96c769.mp4` | moving | moving | shedding | A |
| `moving__moving__c41cf2f9.mp4` | moving | moving | unseen | A |
| `moving__moving__e6f5f2f0.mp4` | moving | moving | shedding | A |
| `moving__moving__f8ffab0a.mp4` | moving | moving | hand_feeding | A |
| `shedding__na__0146200f.mp4` | shedding | shedding | moving | A |
| `shedding__na__0525472f.mp4` | shedding | shedding | hand_feeding | A |
| `shedding__na__0e7bccb0.mp4` | shedding | shedding | hand_feeding | A |
| `shedding__na__25fa7876.mp4` | shedding | shedding | moving | A |
| `shedding__na__2cad1b51.mp4` | shedding | shedding | moving | A |
| `shedding__na__2d583811.mp4` | shedding | shedding | moving | A |
| `shedding__na__3252ac4a.mp4` | shedding | shedding | unseen | A |
| `shedding__na__3b0d9995.mp4` | shedding | shedding | moving | A |
| `shedding__na__3b169faa.mp4` | shedding | shedding | moving | A |
| `shedding__na__3f976b25.mp4` | shedding | shedding | moving | A |
| `shedding__na__53a2525b.mp4` | shedding | shedding | moving | A |
| `shedding__na__6142554e.mp4` | shedding | shedding | moving | A |
| `shedding__na__640ce9bb.mp4` | shedding | shedding | moving | A |
| `shedding__na__67c40fdf.mp4` | shedding | shedding | moving | A |
| `shedding__na__6901da64.mp4` | shedding | shedding | moving | A |
| `shedding__na__6c9b50ad.mp4` | shedding | shedding | moving | A |
| `shedding__na__8d3d74b5.mp4` | shedding | shedding | moving | A |
| `shedding__na__9c871834.mp4` | shedding | shedding | hand_feeding | A |
| `shedding__na__9dd677be.mp4` | shedding | shedding | moving | A |
| `shedding__na__ba39511a.mp4` | shedding | shedding | hand_feeding | A |
| `shedding__na__c72a8256.mp4` | shedding | shedding | moving | A |
| `shedding__na__d83eacae.mp4` | shedding | shedding | hand_feeding | A |
| `shedding__na__efa2afcc.mp4` | shedding | shedding | moving | A |
