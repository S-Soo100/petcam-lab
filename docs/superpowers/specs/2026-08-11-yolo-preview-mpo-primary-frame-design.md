# YOLO Preview MPO 첫 프레임 호환 설계

**상태:** Owner 승인 — 2026-08-11

## 문제

보호 Preview 브라우저 회귀 테스트에서 Owner가 제공한 `.JPG` 4장이 모두 10 MiB·20 MP 제한을
통과했지만 worker가 `422 media_invalid`로 거부했다. 네 파일은 Pillow 기준 `format=MPO`,
`n_frames=2`이고, 현재 `_decode_image`가 형식과 무관하게 `n_frames != 1`을 차단해서 YOLO까지
도달하지 못했다.

## 결정

- 요청 `Content-Type`이 `image/jpeg`이고 Pillow가 `JPEG` 또는 `MPO`로 판독한 경우 첫 프레임만
  검증하고 EXIF orientation을 적용해 RGB 디코드한 뒤 기존 YOLO image inference에 전달한다.
- `image/png`와 `image/webp`의 다중 프레임 입력은 계속 `422 media_invalid`로 거부한다.
- 이미지 signature allowlist, 10 MiB body cap, 첫 프레임 20 MP cap, 임시파일 0700·cleanup,
  bearer 인증, rate limit은 변경하지 않는다.
- 모델 version, threshold, bbox schema, active model, production 배포는 변경하지 않는다.
- MPO의 보조 프레임은 학습 데이터·GT·추론 입력으로 사용하지 않는다.

## 사용자 체험 흐름

1. **[화면]** 사용자가 기존 게코 찾기 화면과 드롭존을 본다.
2. **[조작]** `.JPG` MPO 사진을 선택하거나 드롭하고 `게코 찾기`를 누른다.
3. **[반응]** 화면은 기존과 동일하게 `처리 중…`을 표시하고 worker는 첫 프레임만 추론한다.
4. **[반응]** 성공하면 model version·confidence·처리시각과 bbox overlay가 표시된다.
5. **[감정]** 사용자는 휴대폰에서 받은 정상 JPG를 별도 변환 없이 시연할 수 있다.

animated WebP/PNG, 손상 MPO, 첫 프레임 20 MP 초과는 기존 안전 오류 화면을 유지한다.

## 테스트 계약

- synthetic 2-frame MPO가 `image/jpeg`로 제출되면 200이고 runner가 정확히 한 번 호출된다.
- runner가 받은 frame은 MPO 첫 프레임의 크기·픽셀에 대응하고 EXIF orientation 6을 반영한다.
- 기존 animated WebP 테스트는 계속 422다.
- 일반 JPEG, 20 MP cap, signature mismatch, temp cleanup 회귀 테스트는 계속 통과한다.
- 실제 Owner 사진 4장을 보호 Preview에서 다시 제출해 bbox 결과와 model metadata를 확인한다.

## 배포 경계

Mac mini `com.petcam.yolo-preview-worker`와 보호 Vercel Preview만 갱신한다. production active model,
production DB/R2, `label.tera-ai.uk` production 배포는 변경하지 않는다.
