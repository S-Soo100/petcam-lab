import {NextRequest,NextResponse} from 'next/server';
import {beforeEach,expect,it,vi} from 'vitest';
const {requireOwner,rpc}=vi.hoisted(()=>({requireOwner:vi.fn(),rpc:vi.fn()}));
vi.mock('@/lib/labelingAccess',()=>({requireOwner}));
vi.mock('@/lib/supabase',()=>({supabaseAdmin:{rpc}}));
import {GET} from './route';
const url='https://test/api/labeling-v4/owner/highlight-quality';
beforeEach(()=>{vi.clearAllMocks();requireOwner.mockResolvedValue({ok:true});rpc.mockResolvedValue({data:{rows:[],shadow_rows:[]},error:null});});
it('owner 외에는 집계 접근 불가',async()=>{
  requireOwner.mockResolvedValue({ok:false,response:NextResponse.json({detail:'forbidden'},{status:403})});
  expect((await GET(new NextRequest(url))).status).toBe(403);expect(rpc).not.toHaveBeenCalled();
});
it.each(['?from=2026-02-30&to=2026-03-03','?from=2026-01-01&to=2026-03-01','?from=2026-09-08&to=2026-09-08'])('기간 검증 %s',async(q)=>{
  expect((await GET(new NextRequest(url+q))).status).toBe(400);expect(rpc).not.toHaveBeenCalled();
});
it('과거 기간을 RPC에 고정해',async()=>{
  const r=await GET(new NextRequest(url+'?from=2026-09-01&to=2026-09-08'));
  expect(r.status).toBe(200);expect(await r.json()).toMatchObject({rows:[],shadow_rows:[]});
  expect(rpc).toHaveBeenCalledWith('fn_highlight_quality_stats',{p_from:'2026-09-01T00:00:00.000Z',p_to:'2026-09-08T00:00:00.000Z'});
});
it('DB 원문과 잘못된 응답은 노출하지 않아',async()=>{
  rpc.mockResolvedValue({data:null,error:{message:'private-connection'}});
  const r=await GET(new NextRequest(url));expect(r.status).toBe(502);expect(await r.text()).not.toContain('private-connection');
  rpc.mockResolvedValue({data:null,error:null});expect((await GET(new NextRequest(url))).status).toBe(502);
});
