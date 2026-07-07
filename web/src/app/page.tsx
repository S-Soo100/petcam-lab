import { redirect } from 'next/navigation';

// 루트 진입점 = 라벨링 큐로 통합 (관리자 전용).
// 옛 Round 1 PoC 대시보드(Gemini)는 폐기 — /labeling 이 유일한 진입점이다.
// redirect() 는 서버에서 즉시 응답하므로 label.tera-ai.uk/ 접속 시 바로 /labeling 으로 이동.
export default function Home() {
  redirect('/labeling');
}
