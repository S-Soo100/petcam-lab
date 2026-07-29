# News comments/admin migration design

## 목표

기존 `news_articles` 공개 읽기 계약을 유지하면서 익명 댓글과 뉴스 전용 관리자 발행
기능을 추가한다. 브라우저 역할에는 테이블 쓰기 권한을 주지 않고, 검증된
`SECURITY DEFINER` RPC만 공개한다.

## 정본

- 요청:
  `/Users/baek/terra-ai-promotion-website/docs/requests/2026-07-29-petcam-lab-news-comments-admin-migration.md`
- 요청 commit:
  `34a51e615a63a431a81ea684db896a349e969eae`
- 선행 migration:
  `migrations/2026-07-29_news_articles.sql`
- 대상 project:
  `slxjvzzfisxqwnghvrit`

요청서가 지정한 petcam-lab handoff와 promotion plan 파일은 로컬에 없으므로,
이 설계와 구현 계획을 petcam-lab의 tracked 정본으로 새로 만든다.

## 데이터 경계

### `news_admins`

- `auth.users(id)`를 참조하는 뉴스 전용 멤버십이다.
- 기존 라벨러·Owner 여부는 뉴스 권한의 근거가 아니다.
- anon/authenticated는 테이블의 존재와 행을 직접 읽거나 쓸 수 없다.
- 최초 관리자는 service-role 운영 절차로만 등록한다.

### `news_comments`

- 발행 시각이 지난 published article에만 달 수 있다.
- anon/authenticated는 숨김이 아닌 공개 글의 댓글만 SELECT한다.
- 댓글 작성은 `fn_submit_news_comment`만 허용한다.
- 본인 수정·삭제는 없고 관리자 숨김·삭제만 제공한다.
- fingerprint는 원본 IP/UA를 저장하지 않는 64자리 SHA-256 pseudonymous identifier다.

## RPC 경계

- `fn_is_news_admin`: 현재 JWT의 `auth.uid()`가 `news_admins`에 있는지만 반환한다.
- `fn_news_article_is_public`: 주어진 article UUID가 현재 공개 상태인지 반환한다.
- `fn_submit_news_comment`: slug·nickname·body 검증, 공개 글 검증, rate limit, INSERT를
  한 transaction에서 수행한다.
- 관리자 RPC 4종은 첫 단계에서 `fn_is_news_admin()`을 확인하고 아니면 SQLSTATE
  `42501`로 거부한다.

모든 definer 함수는 `search_path=''`이고 객체를 schema-qualified로 참조한다.
PUBLIC 기본 EXECUTE를 회수한 뒤 필요한 역할에만 명시적으로 부여한다.

## Rate limit 하드닝

요청 헤더에서 `x-forwarded-for`와 `user-agent`를 읽어 SHA-256 fingerprint를 만든다.
고정 문자열 `news-comment-v1`은 비밀 salt가 아니라 domain separator다.

- 같은 fingerprint: 1분 1건
- 같은 fingerprint: 1시간 5건
- 카운트 전에 fingerprint 기반 transaction advisory lock을 잡아 동시 요청 두 건이
  모두 0건을 관찰하는 race를 막는다.
- 헤더 설정이 없거나 빈 문자열이어도 `{}`로 정규화해 JSON cast 오류 없이
  fail-closed 공통 fingerprint를 만든다.

이 제한은 기본적인 스팸 완화이며 강한 신원 인증이 아니다. UA 변경으로 회피할 수 있다는
한계를 운영 문서에 남긴다.

## Storage

`news-media` public bucket을 migration transaction에서 만들고 다음 정책을 둔다.

- anon/authenticated public read
- authenticated 중 `fn_is_news_admin()`만 insert/update/delete
- update에는 `USING`과 `WITH CHECK`를 모두 둬 다른 bucket으로 이동시키는 우회를 막는다.

기존 동명 bucket·policy가 있으면 조용히 덮지 않고 migration을 중단한다.

## 실패·롤백

- migration은 `BEGIN/COMMIT` 한 transaction이다.
- 기존 객체와 충돌하면 fail-closed로 중단한다.
- 적용 전 로컬 PostgreSQL 15 임시 DB에서 RLS·RPC·동시성·Storage 정책을 검증한다.
- production probe는 고유 slug와 comment만 만들고 `finally`에서 article cascade로
  전부 정리한다.
- 기존 영상·라벨·RBA·blind·GT 테이블은 읽거나 변경하지 않는다.

## 성공 조건

1. anon 직접 comment INSERT 거부
2. anon RPC comment INSERT 성공
3. 동일 fingerprint 두 번째 요청 rate limit 거부
4. draft article comment 거부
5. hidden comment anon 비노출
6. 비관리자 authenticated 관리자 RPC 거부
7. 기존 `motion_clips` anon 접근 거부 유지
8. 서로 다른 실제 HTTP User-Agent가 서로 다른 fingerprint로 분리
9. 관리자 RPC 및 Storage 정책의 비관리자 거부
10. probe residue 0, Security Advisor 신규 error/warning 0

