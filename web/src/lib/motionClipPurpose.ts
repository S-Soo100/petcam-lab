// 운영 라벨링은 촬영 목적과 현재 R2 위치가 모두 canonical일 때만 허용한다.
// `production = test가 아님`처럼 넓게 잡으면 격리·제외·삭제 namespace가 재진입하므로
// 명시적 prefix를 사용한다. DB guard와 별개인 API 계층의 2차 fail-closed 방어다.
export const PRODUCTION_MOTION_CLIP_PREFIX = 'terra-clips/clips/';

export function isProductionLabelingMedia(
  clipPurpose: unknown,
  r2Key: unknown,
): boolean {
  return clipPurpose === 'production'
    && typeof r2Key === 'string'
    && r2Key.startsWith(PRODUCTION_MOTION_CLIP_PREFIX);
}
