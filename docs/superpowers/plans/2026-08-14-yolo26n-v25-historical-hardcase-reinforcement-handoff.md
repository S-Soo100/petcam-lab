# YOLO26n v2.5 historical hard-case — Mac mini handoff tracking record

**상태:** `PENDING_I4_PRIVATE_HANDOFF_VERIFICATION`

이 파일은 tracked tracking record이며 `verify_agent_handoff.py` 입력이 아니다. 실제 validator manifest는
repo 밖 private attempt root에 mode 0600으로 만들고 Gate-free Owner runtime의 exact implementation
commit `I4`를 검증한다. 과거 I3 SHA와 v1/v2 attempt root는 보존만 하며 재실행하지 않는다.

## 고정 구현 경계

| 항목 | 값 |
|---|---|
| implementation commit `I4` | `39baf45096773e1a0bf4509fe6d41d718a3dc162` |
| implementation host | `BaekBook-Pro-14-M5.local` |
| runtime host | `baeg-endeuui-Macmini.local` |
| MacBook prepare repo | `/Users/baek/petcam-lab-yolo-v25-owner-only` |
| MacBook private attempt root | `/Users/baek/private-rba/yolo26n-v25-historical-hardcase-reinforcement/attempt-20260814-owner-only-v2` |
| Mac mini execution repo | `/Users/baek-end/petcam-lab-yolo-v25-owner-only` |
| plan | `/Users/baek-end/petcam-lab-yolo-v25-owner-only/docs/superpowers/plans/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement.md` |
| design | `/Users/baek-end/petcam-lab-yolo-v25-owner-only/docs/superpowers/specs/2026-08-14-yolo26n-v25-historical-hardcase-reinforcement-design.md` |
| runtime kind / label | `oneshot` / `yolo26n-v25-owner-only-hardcase` |
| Mac mini private attempt root | `/Users/baek-end/private-rba/yolo26n-v25-historical-hardcase-reinforcement/attempt-20260814-owner-only-v3` |
| private validator manifest | `/Users/baek-end/private-rba/yolo26n-v25-historical-hardcase-reinforcement/handoff-owner-only-v3.private.md` |

## 순서와 hard stop

1. `I4..H4-final`의 net diff는 이 tracking file 하나뿐이어야 한다. 최초 H4의 in-root manifest 경로
   충돌을 고친 tracking-only 후속도 이 파일 외에는 바꾸지 않는다.
2. Mac mini의 기존 dirty checkout은 열람 외 변경하지 않는다. 별도 execution repo를 exact `I4` detached
   HEAD로 만들고 tracked/untracked clean을 확인한다.
   MacBook prepare도 위 별도 repo를 exact `I4` detached HEAD로 만들고 clean을 확인한다.
3. repo 밖 private manifest는 fresh attempt root 밖의 위 sibling path에 O_EXCL/0600으로 만들고 supported
   front matter의 `commit_sha=I4`만 사용한다. pipeline 시작 때 두 fresh attempt root는 계속 미존재여야 한다. input artifact SHA와
   directory SHA는 body 및 별도 preflight에서 raw bytes와 exact 비교한다.
4. repo 밖 manifest의 실제 `HANDOFF_OK` 전에는 Owner audit, bundle, inference, queue 생성을 실행하지 않는다.
5. runtime은 승인된 isolated environment를 concurrent package writer 없이 exclusive-use해야 한다.
   exact pre/post fingerprint를 재계산하며 이 전제를 보장할 수 없으면 immutable/root-owned runtime을 별도
   승인받기 전 fail-closed다.
6. 새 순서는 Gate path를 받지 않는 Owner input audit → Owner inventory/mining/dedup bundle → runtime inference
   → blind queue → independent acceptance다. Gate raw/manifest/COCO/lineage를 preflight·handoff·runtime에서
   읽지 않는다. validation153/internal151/external60은 열거나 재평가하지 않는다.

DB/R2/service/production model/GME/labeling web write·deploy는 0이다. 기존 v2.4b freeze, ledgers, locks,
historical fingerprint와 future-holdout shortage artifact는 삭제·덮어쓰기·재실행하지 않는다.

## Preflight residue 기록

첫 private-manifest preflight는 checkpoint의 `.pinned/` 위치를 확인하기 전에 v1 attempt directory만
0700으로 만들고 실패했다. MacBook의 과거 v1과 Mac mini의 과거 v1/v2는 모두 historical preserve-only이며
재사용·삭제하지 않는다. H4의 fresh root는 MacBook v2와 Mac mini v3이고, tracking 작성 시점에 둘 다
미존재여야 한다.
