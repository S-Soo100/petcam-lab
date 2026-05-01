# dish-presence oracle spot check report

> 스펙: `specs/feature-vlm-feeding-postfilter.md §2.1`. oracle = Gemini 2.5 Pro.
> 의심 케이스만 영상 직접 확인하고, 결정 다르면 알려줘 → GT 수정 반영.

## 1. 분포 요약

- 전체: **39건**
- dish=true: 22건 / dish=false: 17건
- licking=true: 38건 / licking=false: 1건
- 평균 confidence: 0.98
- 의심 케이스: **17건** (영상 확인 권장)
- 클린 (oracle 결정 그대로 GT 채택 후보): 22건

## 2. (gt_action, dish, licking) 매트릭스

| GT | dish | licking | n |
|---|---|---|---|
| defecating | ✗ | ✓ | 1 |
| drinking | ✗ | ✓ | 9 |
| drinking | ✓ | ✓ | 2 |
| drinking | ✓ | ✗ | 1 |
| eating_paste | ✓ | ✓ | 12 |
| eating_paste | ✗ | ✓ | 5 |
| moving | ✓ | ✓ | 7 |
| moving | ✗ | ✓ | 2 |

## 3. 의심 케이스 (17건) — **영상 확인 부탁**

### 05da625c — GT=drinking인데 dish=true (사료 보이는데 물 마심?)

- GT: `drinking`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✓ / conf=0.90
- reasoning: _A dish containing food is visible on the floor. The gecko approaches a water dispenser and licks it repeatedly to drink._
- 영상: `05da625c-d1bc-428f-a480-83f763900940` (web/eval에서 clip_id로 file_path 조회)

### 95502679 — GT=drinking인데 dish=true (사료 보이는데 물 마심?)

- GT: `drinking`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✗ / conf=0.90
- reasoning: _A dish containing food is visible. A gecko approaches the dish and positions its head over it, but no actual licking is seen._
- 영상: `95502679-7220-40ac-9be8-429644415478` (web/eval에서 clip_id로 file_path 조회)

### 987c7b5d — GT=drinking인데 dish=true (사료 보이는데 물 마심?)

- GT: `drinking`  /  raw v3.5: `moving`
- oracle: dish=✓ / licking=✓ / conf=1.00
- reasoning: _The gecko approaches a dish containing food and clearly licks from it at 00:49._
- 영상: `987c7b5d-d7d6-41c0-9564-b26567d7dd41` (web/eval에서 clip_id로 file_path 조회)

### 27c5b14f — GT=eating_paste지만 dish=false (사료 안 보임?)

- GT: `eating_paste`  /  raw v3.5: `eating_paste`
- oracle: dish=✗ / licking=✓ / conf=1.00
- reasoning: _The gecko is being hand-fed from a stick, not a dish. It is actively licking the food paste from the stick throughout the clip._
- 영상: `27c5b14f-05f8-41ec-b26d-527d84ebbfb4` (web/eval에서 clip_id로 file_path 조회)

### 41aecaea — GT=eating_paste지만 dish=false (사료 안 보임?)

- GT: `eating_paste`  /  raw v3.5: `eating_paste`
- oracle: dish=✗ / licking=✓ / conf=1.00
- reasoning: _The gecko is being fed with a syringe, not from a dish. It clearly licks the food from the syringe and then cleans its mouth._
- 영상: `41aecaea-d352-49cf-926e-315d72173845` (web/eval에서 clip_id로 file_path 조회)

### 5cfe1d48 — GT=eating_paste지만 dish=false (사료 안 보임?)

- GT: `eating_paste`  /  raw v3.5: `eating_paste`
- oracle: dish=✗ / licking=✓ / conf=1.00
- reasoning: _The gecko is being hand-fed from a spoon and clearly licks the food. The purple feeding ledge is visible but appears to be empty._
- 영상: `5cfe1d48-5f7c-40ff-836e-e6cbe58f2eac` (web/eval에서 clip_id로 file_path 조회)

### cc0c1d04 — GT=eating_paste지만 dish=false (사료 안 보임?)

- GT: `eating_paste`  /  raw v3.5: `eating_paste`
- oracle: dish=✗ / licking=✓ / conf=1.00
- reasoning: _The gecko is being hand-fed from a syringe, not a dish. It is clearly licking the food paste from the syringe tip._
- 영상: `cc0c1d04-0a27-4941-985f-4db3bc407b38` (web/eval에서 clip_id로 file_path 조회)

### ce5fee73 — GT=eating_paste지만 dish=false (사료 안 보임?)

- GT: `eating_paste`  /  raw v3.5: `eating_paste`
- oracle: dish=✗ / licking=✓ / conf=1.00
- reasoning: _The gecko is being hand-fed from a stick, not a dish. The licking behavior is very clear throughout the clip._
- 영상: `ce5fee73-9f8f-4083-820d-15e1c04af6b9` (web/eval에서 clip_id로 file_path 조회)

### 09bc2ee4 — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✓ / conf=1.00
- reasoning: _A gecko approaches a food dish and clearly licks the contents before moving away._
- 영상: `09bc2ee4-5db0-4bc7-8299-34ea43c04ac3` (web/eval에서 clip_id로 file_path 조회)

### 379e97a3 — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✓ / conf=1.00
- reasoning: _A dish containing food is visible, and the gecko approaches it and eats from it for several seconds._
- 영상: `379e97a3-7eaa-4fc2-bddc-bf4297cb1c46` (web/eval에서 clip_id로 file_path 조회)

### 76a24e8b — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✓ / conf=0.90
- reasoning: _The gecko approaches the food dish and eats from it for several seconds. Both the food in the dish and the licking behavior are clearly visible._
- 영상: `76a24e8b-7d02-42d5-b95b-ce43e98b43f2` (web/eval에서 clip_id로 file_path 조회)

### 9ad8d159 — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✓ / conf=1.00
- reasoning: _A food dish is visible on the enclosure floor. The gecko moves down from a ledge and licks the water dispenser on the right._
- 영상: `9ad8d159-f530-41be-af05-722c2cafb160` (web/eval에서 clip_id로 file_path 조회)

### aaafbe3f — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✗ / licking=✓ / conf=1.00
- reasoning: _The dish contains water, not food. The gecko is clearly seen drinking from the water dish towards the end of the clip._
- 영상: `aaafbe3f-5cf0-4c9c-bc1b-13c5be442080` (web/eval에서 clip_id로 file_path 조회)

### b100a145 — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✓ / conf=1.00
- reasoning: _A dish containing food is visible. The gecko approaches the dish and begins to eat from it._
- 영상: `b100a145-4bb5-495f-9eec-3510ed0d5584` (web/eval에서 clip_id로 file_path 조회)

### c41cf2f9 — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✓ / conf=0.90
- reasoning: _A dish containing food is visible. The gecko approaches the dish and performs head movements consistent with eating, although the tongue itself is not clearly visible._
- 영상: `c41cf2f9-d11d-49f1-afcd-003a88bc9f88` (web/eval에서 clip_id로 file_path 조회)

### e303a6e8 — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✓ / licking=✓ / conf=0.90
- reasoning: _A dish with food is visible on the floor. The gecko moves to the water dispenser on the right and appears to be licking it, although the tongue itself is not clearly resolved._
- 영상: `e303a6e8-6b42-44b5-b8ce-b08d2a3cfcf0` (web/eval에서 clip_id로 file_path 조회)

### e6f5f2f0 — GT=moving인데 licking=true

- GT: `moving`  /  raw v3.5: `eating_paste`
- oracle: dish=✗ / licking=✓ / conf=0.90
- reasoning: _The gecko approaches the dish and puts its head inside, appearing to drink. The dish does not contain any visible food._
- 영상: `e6f5f2f0-5f8a-4800-b568-0b5bb38b60f1` (web/eval에서 clip_id로 file_path 조회)

## 4. 클린 케이스 (22건)

| clip_id (8) | GT | raw | dish | lick | conf | reasoning |
|---|---|---|---|---|---|---|
| 3369d723 | drinking | drinking | ✗ | ✓ | 1.00 | The gecko is clearly and repeatedly licking water droplets from a surface. No fo |
| 6a24c2e6 | drinking | drinking | ✗ | ✓ | 1.00 | The gecko is clearly licking the glass wall of the enclosure, likely drinking wa |
| 7124cebe | drinking | drinking | ✗ | ✓ | 1.00 | The gecko is clearly licking water droplets from the glass wall of the enclosure |
| 71889c3c | drinking | drinking | ✗ | ✓ | 1.00 | The gecko is clearly licking water from a bottle cap. Since the dish contains on |
| bf83c4cf | drinking | drinking | ✗ | ✓ | 1.00 | The gecko is clearly visible licking water droplets off the glass wall of its en |
| cf698b78 | drinking | drinking | ✗ | ✓ | 1.00 | The gecko is sitting on a ledge with empty dish indentations. It repeatedly lick |
| 2420abd8 | drinking | eating_paste | ✗ | ✓ | 1.00 | The gecko clearly licks the water dispenser for an extended period. A food dish  |
| d95e9eaa | drinking | eating_paste | ✗ | ✓ | 1.00 | The gecko is clearly visible licking water droplets off the enclosure wall. No f |
| ff1ecb03 | drinking | moving | ✗ | ✓ | 0.90 | A dish is visible on the ground, but it is not clear if it contains food. The ge |
| 0dbc54a8 | eating_paste | eating_paste | ✓ | ✓ | 1.00 | A dish containing food is visible, and the gecko approaches it and eats for seve |
| 1ef6f35c | eating_paste | eating_paste | ✓ | ✓ | 1.00 | The gecko is clearly eating a pasty supplement from a dish throughout the entire |
| 5a907d7b | eating_paste | eating_paste | ✓ | ✓ | 1.00 | The gecko is clearly seen eating a pasty supplement from a food dish throughout  |
| 65b57205 | eating_paste | eating_paste | ✓ | ✓ | 0.90 | A dish containing food is visible on the enclosure floor. The gecko is seen with |
| 69c4badd | eating_paste | eating_paste | ✓ | ✓ | 1.00 | The gecko is clearly and repeatedly licking a pasty food supplement from a pink  |
| 6ecd693c | eating_paste | eating_paste | ✓ | ✓ | 1.00 | 음식이 담긴 접시가 있고, 게코가 음식을 여러 번 핥는 모습이 보입니다. |
| 7f4dbdcc | eating_paste | eating_paste | ✓ | ✓ | 1.00 | The gecko is clearly seen licking food from a yellow dish throughout the entire  |
| 8f186154 | eating_paste | eating_paste | ✓ | ✓ | 1.00 | A dish containing food is visible throughout the clip. The gecko approaches the  |
| 9af1ba2e | eating_paste | eating_paste | ✓ | ✓ | 1.00 | The gecko is being hand-fed with a spoon, which contains food, and it clearly li |
| b8317750 | eating_paste | eating_paste | ✓ | ✓ | 1.00 | The gecko is being hand-fed with a spoon and is clearly seen licking the food mu |
| c711cce8 | eating_paste | eating_paste | ✓ | ✓ | 1.00 | 도마뱀이 그릇에 담긴 먹이를 핥아 먹는 모습이 명확하게 보입니다. |
| dbdd4378 | eating_paste | eating_paste | ✓ | ✓ | 1.00 | The gecko is being hand-fed a pasty supplement from a spoon and is clearly seen  |
| d88e1390 | defecating | drinking | ✗ | ✓ | 1.00 | No food dish is visible. The gecko is on a spray bottle and clearly licks its ow |
