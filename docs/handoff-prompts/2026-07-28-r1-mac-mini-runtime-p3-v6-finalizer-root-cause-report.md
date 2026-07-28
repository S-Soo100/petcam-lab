# R1 Mac mini runtime P3 v6 finalizer root-cause 보고

## 판정

`R1_RUNTIME_P3_V6_FINALIZER_SELF_UNLOAD_CONFIRMED`

이 문서는
`2026-07-28-r1-mac-mini-runtime-p3-v6-post-reboot-drift-report.md`의 이력을
삭제하지 않고 원인 미확정 부분과 zero-access 판정을 additive로 정정한다.

v6 production baseline에서 사라진
`com.petcam.vlm-backfill-finalizer.plist`는 research controller가 제거한 파일이 아니야.
production one-shot finalizer가 reboot/login 과정에서 실행된 뒤 자기 `EXIT` trap으로
자기 service와 plist를 제거했다.

## 결정론적 근거

pre-reboot baseline은 2026-07-28 20:55 KST에 finalizer plist를 실제 파일로 읽어
SHA-256 `8e999261ba1c96d22e882350b10bb11914456f70aef3c759a602fae434be8fbb`로
기록했다.

production repo의 tracked wrapper:

```text
repo=/Users/baek-end/petcam-nightly-reporter
repo HEAD=75819399bbdb87ee84e8525184fb3ea9d48bb817
wrapper=run-vlm-backfill-finalizer.sh
wrapper SHA-256=fc51c14748a3123f8dd1524367f06f322ce9b16da245d26f0a62e8666d72e054
```

wrapper의 종료 계약:

```bash
LABEL="com.petcam.vlm-backfill-finalizer"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
trap self_unload EXIT
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"
```

installer는 `StartCalendarInterval=20:30`인 one-shot service를 만들며,
`StandardOutPath`와 `StandardErrorPath`는 `/tmp/vlm-backfill-finalizer.log`다.
reboot 뒤 `/tmp` 로그는 남아 있지 않았지만 unified log는 실행 경계를 보존했다.

```text
21:08:19 claude PID 10530 시작, keychain 조회
21:08:19~21:08:20 외부 443 network path 생성
21:08:22 com.petcam.vlm-backfill-finalizer inactive/removing
21:09:48 background task registration removing
```

이전 작업 session transcript의 모든 shell command도 구조적으로 검사했다. LaunchAgent
제거 명령은 매번 literal
`$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist`만 대상으로 했고 wildcard,
directory-wide remove, finalizer label은 없었다.

## zero-access 정정

v6 reboot에서 `claude` process와 외부 network path가 관측됐으므로 v6 전체에 대해
`Claude 접근 0`을 주장할 수 없다. 요청 성공, 응답 수신, 과금은 로그만으로 단정하지 않는다.
research runtime ledger의 provider calls/cost는 계속 `0/0`이고 research code가 Claude를
호출한 증거도 없다.

이 access는 기존 production one-shot service의 자체 실행이지만, research reboot와 같은
시간 경계에서 발생했으므로 fail-closed 감사에는 위반으로 남긴다.

## v7 안전 계약

fresh v7은 현재 production plist 7개를 새 immutable baseline으로 기록하고,
`com.petcam.vlm-backfill-finalizer`를 `expected_absent_labels`에 넣는다.

- 기존 7개 plist SHA-256/WorkingDirectory drift: 실패
- finalizer plist 재등장: 실패
- production service를 복구, bootout, kickstart, signal: 금지
- v7 시작 이후 production DB/R2/media/dataset/model/Claude/VLM/local LLM/provider 접근: 0

v6 target은 이미 rollback 상태고 24시간 검증은 시작하지 않았다.
