// PoC VLM 도메인 타입 (specs/feature-poc-vlm-web.md §4-5)

// 행동 9 클래스 (Round 1 v3.4부터 shedding 추가 — 모든 reptile 종 공통).
export const BEHAVIOR_CLASSES = [
  'eating_paste',
  'eating_prey',
  'drinking',
  'defecating',
  'shedding',
  'basking',
  'hiding',
  'moving',
  'unseen',
] as const;
export type BehaviorClass = (typeof BEHAVIOR_CLASSES)[number];

// 멀티 행동 시 단일 라벨 선택 (§0-5). shedding은 sustained 행동이라 basking 위.
export const PRIORITY_ORDER: BehaviorClass[] = [
  'eating_prey',
  'eating_paste',
  'drinking',
  'defecating',
  'shedding',
  'basking',
  'moving',
  'hiding',
  'unseen',
];

// 4 종 (라운드 1은 crested_gecko만)
export const SPECIES = ['crested_gecko', 'gargoyle_gecko', 'leopard_gecko', 'aft'] as const;
export type Species = (typeof SPECIES)[number];

// 종별 가용 클래스. paste 사료는 게코류만.
export const SPECIES_CLASSES: Record<Species, BehaviorClass[]> = {
  crested_gecko: [...BEHAVIOR_CLASSES],
  gargoyle_gecko: [...BEHAVIOR_CLASSES],
  leopard_gecko: BEHAVIOR_CLASSES.filter((c) => c !== 'eating_paste'),
  aft: BEHAVIOR_CLASSES.filter((c) => c !== 'eating_paste'),
};

// DB enum-ish (CHECK 제약 그대로 미러)
export const CLIP_SOURCES = ['camera', 'upload', 'youtube'] as const;
export type ClipSource = (typeof CLIP_SOURCES)[number];

export const LOG_SOURCES = ['vlm', 'human', 'yolo'] as const;
export type LogSource = (typeof LOG_SOURCES)[number];

// camera_clips 행 (필요 컬럼만 typing — 학습 메모: TS는 부분 타입도 허용,
// PostgREST 응답 select() 결과를 안전하게 받기 위함)
export interface Clip {
  id: string;
  user_id: string;
  pet_id: string | null;
  camera_id: string | null;
  source: ClipSource;
  started_at: string;
  duration_sec: number;
  file_path: string;
  thumbnail_path: string | null;
  has_motion: boolean;
  width: number | null;
  height: number | null;
  fps: number | null;
  created_at: string;
}

export interface BehaviorLog {
  id: number;
  clip_id: string;
  frame_idx: number;
  action: string; // 모델 응답이 8클래스 외일 수 있어 string. 검증은 호출 측.
  confidence: number | null;
  source: LogSource;
  vlm_model: string | null;
  reasoning: string | null;
  verified: boolean;
  corrected_to: string | null;
  notes: string | null;
  created_at: string;
  created_by: string | null;
}

export function isBehaviorClass(s: string): s is BehaviorClass {
  return (BEHAVIOR_CLASSES as readonly string[]).includes(s);
}

// DB species.id (kebab) → 코드 Species union (snake) 매핑.
// 라운드 1은 crested-gecko만 사용. gargoyle은 DB에 미등록 → 라운드 2 추가.
export const DB_SPECIES_TO_CODE: Record<string, Species> = {
  'crested-gecko': 'crested_gecko',
  'leopard-gecko': 'leopard_gecko',
  'fat-tailed-gecko': 'aft',
  // 'gargoyle-gecko': 'gargoyle_gecko',  // DB 등록 후 활성
};

export const CODE_SPECIES_TO_DB: Record<Species, string> = {
  crested_gecko: 'crested-gecko',
  leopard_gecko: 'leopard-gecko',
  aft: 'fat-tailed-gecko',
  gargoyle_gecko: 'gargoyle-gecko',
};
