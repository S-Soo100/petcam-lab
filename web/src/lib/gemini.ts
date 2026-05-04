import 'server-only';
// Gemini 2.5 Flash 호출. 영상은 inline base64 (60초 mp4 ~5MB). 라운드 2~ R2 도입 시 File API.
import { GoogleGenerativeAI, type GenerativeModel } from '@google/generative-ai';
import fs from 'node:fs/promises';

export const VLM_MODEL_ID = 'gemini-2.5-flash';

// Lazy 초기화 — module load 시 throw 면 Vercel build collect-page-data fail.
// generationConfig — 분류 task 는 결정론적 디코딩 (temperature 0.1). 미지정 시 기본 1.0 →
// 같은 클립도 호출마다 라벨 흔들림 (외부 critic 교차 검증 지적).
let _model: GenerativeModel | null = null;
function _getModel(): GenerativeModel {
  if (_model) return _model;
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) throw new Error('GEMINI_API_KEY 누락. web/.env.local 확인.');
  _model = new GoogleGenerativeAI(apiKey).getGenerativeModel({
    model: VLM_MODEL_ID,
    generationConfig: {
      temperature: 0.1,
      topP: 0.95,
      responseMimeType: 'application/json',
    },
  });
  return _model;
}

export interface VlmResponse {
  action: string; // 8클래스 검증은 호출 측 (isBehaviorClass)
  confidence: number;
  reasoning: string;
}

export async function classifyClip(args: {
  videoPath: string;
  systemPrompt: string;
}): Promise<VlmResponse> {
  const videoBytes = await fs.readFile(args.videoPath);
  const base64 = videoBytes.toString('base64');

  const result = await _getModel().generateContent([
    args.systemPrompt,
    {
      inlineData: {
        mimeType: 'video/mp4',
        data: base64,
      },
    },
  ]);
  const text = result.response.text();

  // Gemini가 ```json 펜스 / 설명 prose 섞어 보내는 경우 첫 { ... } 추출 (§4-12 리스크 대응).
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) throw new Error(`No JSON in Gemini response: ${text.slice(0, 300)}`);

  let parsed: unknown;
  try {
    parsed = JSON.parse(match[0]);
  } catch (e) {
    throw new Error(`Malformed JSON in Gemini response: ${match[0].slice(0, 300)}`);
  }
  if (
    !parsed ||
    typeof parsed !== 'object' ||
    typeof (parsed as VlmResponse).action !== 'string' ||
    typeof (parsed as VlmResponse).confidence !== 'number'
  ) {
    throw new Error(`Invalid VLM JSON shape: ${JSON.stringify(parsed)}`);
  }
  const p = parsed as VlmResponse;
  return {
    action: p.action,
    confidence: p.confidence,
    reasoning: p.reasoning ?? '',
  };
}
