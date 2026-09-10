import {renderToStaticMarkup} from 'react-dom/server';
import {expect,it} from 'vitest';
import {mapHighlightQuality} from '@/lib/highlightQuality';
import QualityPanel from './_quality-panel';
it('실제 표에 O/X 분모·대기·계약과 표본 한계를 표시해',()=>{
  const r={rule_version:'hl-rule-v0',camera_id:'cam',camera_name:'테스트 카메라',activity_day:'2026-09-08',
    engine_schema_version:'gme-shadow-v1',algorithm_version:'gme-motion-v1',detector_identity:'a'.repeat(64),
    reviewed_count:5,o_to_o:3,o_to_x:1,x_to_o:0,x_to_x:0,pending_initial:1,failed_initial:0,
    correction_count:0,technical_rejects:1,preference_rejects:0,other_rejects:0,missed_visibility:0};
  const html=renderToStaticMarkup(<QualityPanel report={mapHighlightQuality({rows:[r],shadow_rows:[]})}/>);
  expect(html).toContain('75%');expect(html).toContain('3/4');expect(html).toContain('표본 없음');
  expect(html).toContain('테스트 카메라');expect(html).toContain('gme-motion-v1');
  expect(html).toContain('전체 정확도가 아니야');expect(html).toContain('아직 추가 포착 표본이 없어');
  const shadowHtml=renderToStaticMarkup(<QualityPanel report={mapHighlightQuality({rows:[],shadow_rows:[
    {...r,trigger_name:'frequent_bursts',additional_count:5,human_o:2}]})}/>);
  expect(shadowHtml).toContain('사람 O / X');expect(shadowHtml).toContain('2 / 3');expect(shadowHtml).toContain('40%');
});
