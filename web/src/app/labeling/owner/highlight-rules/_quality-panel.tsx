import { Card, CardTitle } from '@/components/ui/Card';
import type { HighlightQuality } from '@/lib/highlightQuality';
import { HIGHLIGHT_TRIGGER_LABELS } from '@/lib/highlightV4';

function rate(value: number | null, numerator: number, denominator: number) {
  return value === null ? '표본 없음' : `${Math.round(value * 100)}% (${numerator}/${denominator})`;
}
function Contract({row}: {row: HighlightQuality['rows'][number] | HighlightQuality['shadow_rows'][number]}) {
  return <details className="text-xs">
    <summary>{row.algorithm_version ?? '분석 전 확정'} · {row.detector_identity?.slice(0, 8) ?? '-'}</summary>
    <p className="max-w-xs break-all">{row.engine_schema_version} / {row.detector_identity}</p>
  </details>;
}
export default function QualityPanel({report}: {report: HighlightQuality}) {
  return <Card className="space-y-3">
    <CardTitle>최근 7일 검수 품질 · GME 버전별</CardTitle>
    <p className="text-xs text-zinc-600">최초 자동 판정과 조회 종료 시점의 사람 최종값을 비교해. 아래는 검수한 표본의 수치이며 전체 정확도가 아니야.</p>
    <p className="text-xs text-zinc-500">카메라마다 O와 X를 모두 골고루 확인해. 대기·실패는 O/X 분모에서 제외해. 활동일은 한국시간 오전 7시에 바뀌어.</p>
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead><tr><th>활동일 / 카메라</th><th>규칙 / GME</th><th>검수</th><th>O 수용률</th><th>X 놓침률</th><th>O→X 사유</th><th>대기 / 실패 / 정정</th></tr></thead>
        <tbody>{report.rows.map((r,i)=><tr key={i} className="border-t align-top">
          <td className="py-2">{r.activity_day}<br/>{r.camera_name ?? '-'}</td>
          <td className="py-2">{r.rule_version}<Contract row={r}/></td>
          <td>{r.reviewed_count}</td>
          <td>{rate(r.o_acceptance,r.o_to_o,r.o_to_o+r.o_to_x)}</td>
          <td>{rate(r.x_miss_rate,r.x_to_o,r.x_to_o+r.x_to_x)}</td>
          <td className="text-xs">검출·흔들림 {r.technical_rejects}<br/>짧음·선호 {r.preference_rejects}<br/>기타·미입력 {r.other_rejects}<br/>가시성 누락 신호 {r.missed_visibility}</td>
          <td>{r.pending_initial} / {r.failed_initial} / {r.correction_count}</td>
        </tr>)}</tbody>
      </table>
    </div>
    {!report.rows.length && <p className="text-sm text-zinc-500">최근 7일 검수 표본이 없어.</p>}
    <h3 className="text-sm font-semibold">당시 꺼진 트리거의 추가 포착</h3>
    <p className="text-xs text-zinc-500">원래 X 중 해당 트리거가 맞은 전체 표본의 사람 O/X를 봐. 같은 영상이 여러 트리거에 포함될 수 있으니 합산하지 마. 트리거는 자동으로 켜지지 않아.</p>
    <div className="overflow-x-auto"><table className="w-full text-left text-sm">
      <thead><tr><th>활동일 / 카메라</th><th>규칙 / GME</th><th>트리거</th><th>사람 O / X</th><th>추가 O 수용률</th></tr></thead>
      <tbody>{report.shadow_rows.map((r,i)=><tr key={i} className="border-t align-top">
        <td className="py-2">{r.activity_day}<br/>{r.camera_name ?? '-'}</td>
        <td>{r.rule_version}<Contract row={r}/></td>
        <td>{HIGHLIGHT_TRIGGER_LABELS[r.trigger_name]}</td>
        <td>{r.human_o} / {r.additional_count-r.human_o}</td>
        <td>{rate(r.acceptance,r.human_o,r.additional_count)}</td>
      </tr>)}</tbody>
    </table></div>
    {!report.shadow_rows.length && <p className="text-xs text-zinc-500">아직 추가 포착 표본이 없어.</p>}
  </Card>;
}
