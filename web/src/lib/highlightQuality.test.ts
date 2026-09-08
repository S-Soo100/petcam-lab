import { describe, expect, it } from 'vitest';
import { mapHighlightQuality } from './highlightQuality';

const identity = {rule_version:'hl-rule-v0',camera_id:'cam',camera_name:'카메라',activity_day:'2026-09-08',
  engine_schema_version:'gme-shadow-v1',algorithm_version:'gme-motion-v1',detector_identity:'a'.repeat(64)};
const row = {...identity,reviewed_count:10,o_to_o:3,o_to_x:1,x_to_o:2,x_to_x:2,
  pending_initial:1,failed_initial:1,correction_count:1,technical_rejects:1,preference_rejects:0,other_rejects:0,missed_visibility:0};
describe('highlight quality', () => {
  it('분모를 O/X로 분리하고 pending을 빼며 raw 필드는 숨겨', () => {
    const report=mapHighlightQuality({rows:[{...row,o_to_o:'3',reviewer_id:'private'}],shadow_rows:[
      {...identity,trigger_name:'frequent_bursts',additional_count:2,human_o:1}]});
    expect(report.rows[0].o_acceptance).toBe(.75);
    expect(report.rows[0].x_miss_rate).toBe(.5);
    expect(report.rows[0].reviewed_count).toBe(10);
    expect(report.rows[0]).not.toHaveProperty('reviewer_id');
    expect(report.shadow_rows[0].acceptance).toBe(.5);
  });
  it('빈 분모를 0%로 표시하지 않아', () => {
    const empty={...row,reviewed_count:2,o_to_o:0,o_to_x:0,x_to_o:0,x_to_x:0,technical_rejects:0};
    expect(mapHighlightQuality({rows:[empty],shadow_rows:[]}).rows[0]).toMatchObject({o_acceptance:null,x_miss_rate:null});
  });
  it.each([-1,1.5,'NaN',null])('잘못된 count %s는 실패해', (bad) => {
    expect(()=>mapHighlightQuality({rows:[{...row,o_to_o:bad}],shadow_rows:[]})).toThrow();
  });
  it('응답 누락과 shadow 초과 count를 거부해', () => {
    expect(()=>mapHighlightQuality(null)).toThrow();
    expect(()=>mapHighlightQuality({rows:[],shadow_rows:[{...identity,trigger_name:'early_action',additional_count:1,human_o:2}]})).toThrow();
  });
});
