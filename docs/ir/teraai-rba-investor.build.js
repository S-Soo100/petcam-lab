// Terra AI RBA — 투자자용 압축 IR 덱 (표지 + 본문 7장 + 부록 3장)
// 기획서: teraai-rba-investor-pdf-plan.md
const pptxgen = require("pptxgenjs");
const path = require("path");

const IMG = path.join(__dirname, "assets");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333" x 7.5"
pres.author = "Terra AI";
pres.title = "Terra AI RBA — 파충류 행동 분석 AI (투자자용)";

const M = { W: 13.333, H: 7.5, LM: 0.62, RM: 0.62 };
const CW = M.W - M.LM - M.RM;      // 12.093
const RIGHT = M.W - M.RM;          // 12.713

const C = {
  INK: "1E293B", INK2: "0F172A", MUTED: "64748B", MUTED2: "94A3B8", FAINT: "CBD5E1",
  LINE: "E2E8F0", CARD: "F8FAFC", CARD2: "F1F5F9", WHITE: "FFFFFF",
  A_FILL: "FEF3C7", A_FILL2: "FEF9EC", A_BORD: "FCD34D", A_TEXT: "B45309", A_DEEP: "92400E",
  B_FILL: "EDE9FE", B_FILL2: "F5F3FF", B_BORD: "C4B5FD", B_TEXT: "7C3AED",
  G_FILL: "D1FAE5", G_FILL2: "ECFDF5", G_BORD: "6EE7B7", G_TEXT: "059669", G_DEEP: "047857",
  BL_FILL: "DBEAFE", BL_FILL2: "EFF6FF", BL_BORD: "93C5FD", BL_TEXT: "2563EB",
  R_TEXT: "DC2626", R_FILL: "FEE2E2", R_BORD: "FCA5A5", CORAL: "F97066",
  DARK: "1E293B", DARK2: "0F172A", DARKTX: "E2E8F0", DARK_ACC: "FCD34D",
};
const F = { KR: "Apple SD Gothic Neo", MONO: "Courier New" };

const cardSh = () => ({ type: "outer", color: "64748B", blur: 7, offset: 2, angle: 90, opacity: 0.16 });
const softSh = () => ({ type: "outer", color: "94A3B8", blur: 9, offset: 3, angle: 90, opacity: 0.20 });

const R = pres.shapes.ROUNDED_RECTANGLE;
const RECT = pres.shapes.RECTANGLE;

// ---------- helpers ----------
function header(slide, o) {
  const dark = !!o.dark;
  const tx = dark ? C.WHITE : C.INK;
  const sub = dark ? C.MUTED2 : C.MUTED;
  const eb = dark ? C.DARK_ACC : (o.ebColor || C.MUTED);
  slide.addText(o.eyebrow, { x: M.LM, y: 0.44, w: CW, h: 0.3, fontFace: F.KR, fontSize: 12.5, bold: true, color: eb, margin: 0, charSpacing: 1 });
  slide.addText(o.title, { x: M.LM, y: 0.76, w: CW, h: 0.78, fontFace: F.KR, fontSize: 27, bold: true, color: tx, margin: 0, valign: "top", lineSpacingMultiple: 1.03 });
  if (o.subtitle) slide.addText(o.subtitle, { x: M.LM, y: 1.58, w: CW, h: 0.5, fontFace: F.KR, fontSize: 14.5, color: sub, margin: 0, valign: "top", lineSpacingMultiple: 1.12 });
  if (o.page) slide.addText(o.page, { x: RIGHT - 3.5, y: 7.02, w: 3.5, h: 0.3, fontFace: F.KR, fontSize: 10, color: C.MUTED2, align: "right", margin: 0 });
}

function card(slide, x, y, w, h, o = {}) {
  slide.addShape(R, {
    x, y, w, h,
    fill: { color: o.fill || C.CARD },
    line: o.border === null ? { type: "none" } : { color: o.border || C.LINE, width: o.bw || 1 },
    rectRadius: o.rad == null ? 0.11 : o.rad,
    ...(o.sh === false ? {} : { shadow: (o.softSh ? softSh() : cardSh()) }),
  });
}

function pill(slide, x, y, w, h, text, fill, txcolor, fs) {
  slide.addShape(R, { x, y, w, h, fill: { color: fill }, line: { type: "none" }, rectRadius: h / 2 });
  slide.addText(text, { x, y: y - 0.01, w, h, fontFace: F.KR, fontSize: fs || 10.5, bold: true, color: txcolor, align: "center", valign: "middle", margin: 0 });
}

function arrow(slide, x, y, w, color) {
  slide.addText("→", { x, y, w: w || 0.5, h: 0.4, fontFace: F.KR, fontSize: 22, bold: true, color: color || C.FAINT, align: "center", valign: "middle", margin: 0 });
}
function plusSign(slide, x, y, w, color) {
  slide.addText("+", { x, y, w: w || 0.4, h: 0.5, fontFace: F.KR, fontSize: 26, bold: true, color: color || C.MUTED2, align: "center", valign: "middle", margin: 0 });
}

// dark takeaway callout with rich text runs
function callout(slide, x, y, w, h, runs, o = {}) {
  slide.addShape(R, { x, y, w, h, fill: { color: o.fill || C.DARK }, line: { type: "none" }, rectRadius: 0.12, shadow: softSh() });
  const tag = o.tag || null;
  let ty = y + 0.22, tw = w - 0.9, tx = x + 0.45;
  if (tag) {
    slide.addText(tag, { x: x + 0.45, y: y + 0.2, w: 2.2, h: 0.34, fontFace: F.KR, fontSize: 11.5, bold: true, color: o.tagColor || C.DARK_ACC, margin: 0, charSpacing: 1 });
    ty = y + 0.6;
  }
  slide.addText(runs, { x: tx, y: ty, w: tw, h: h - (ty - y) - 0.18, fontFace: F.KR, fontSize: o.fs || 13.5, color: C.DARKTX, margin: 0, valign: "top", lineSpacingMultiple: 1.18 });
}

// ============================================================
// COVER
// ============================================================
(function cover() {
  const s = pres.addSlide();
  s.background = { color: C.DARK2 };
  // right image panel (cover-crop portrait, removes letterbox)
  const panelX = 9.0, panelW = M.W - 9.0;
  s.addImage({ path: path.join(IMG, "rba-example-drinking.png"), x: panelX, y: 0, w: panelW, h: M.H, sizing: { type: "cover", w: panelW, h: M.H } });

  s.addText("TERRA AI  ·  INVESTOR BRIEF", { x: M.LM, y: 1.15, w: 7.6, h: 0.35, fontFace: F.KR, fontSize: 13, bold: true, color: C.DARK_ACC, charSpacing: 2, margin: 0 });
  s.addText([
    { text: "밤사이 펫캠 영상을", options: { breakLine: true } },
    { text: "행동 일지로 바꾸는 AI", options: {} },
  ], { x: M.LM, y: 1.7, w: 8.0, h: 2.1, fontFace: F.KR, fontSize: 46, bold: true, color: C.WHITE, margin: 0, lineSpacingMultiple: 1.05 });

  s.addText([
    { text: "RBA", options: { bold: true, color: C.DARK_ACC } },
    { text: " — 파충류 행동 분석 AI", options: { bold: true, color: C.WHITE } },
  ], { x: M.LM, y: 3.95, w: 8.0, h: 0.5, fontFace: F.KR, fontSize: 22, margin: 0 });

  s.addText("단순 펫캠 기능이나 고정 알고리즘이 아니라, 밤사이 영상을 행동 타임라인과 아침 활동 보고서로 바꾸는 파충류 특화 AI 분석 엔진.", {
    x: M.LM, y: 4.55, w: 7.7, h: 1.0, fontFace: F.KR, fontSize: 14.5, color: C.MUTED2, margin: 0, lineSpacingMultiple: 1.25, valign: "top",
  });

  // bottom meta row
  s.addText("Reptile Behavior Analysis", { x: M.LM, y: 6.7, w: 5, h: 0.3, fontFace: F.KR, fontSize: 11, color: C.MUTED, margin: 0 });
  s.addText("2026", { x: 7.4, y: 6.7, w: 1.3, h: 0.3, fontFace: F.KR, fontSize: 11, color: C.MUTED, align: "right", margin: 0 });
})();

// ============================================================
// SLIDE 1 — 무엇을 하는가
// ============================================================
(function s1() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "01 · 분석 파이프라인",
    title: "RBA 분석 파이프라인 — 영상에서 아침 활동 보고서까지",
    subtitle: "밤사이 펫캠 영상을 수집 · 1차 판독 · 정밀 판독 3단계로 처리해, 아침 활동 보고서로 전달한다.",
    page: "본문 01 / 07",
  });

  // 4단계 파이프라인 (그룹 노드 + 화살표)
  const stages = [
    { pill: "1 · 수집 · 저장", pf: "E2E8F0", pt: "334155", panel: C.CARD2, bd: C.LINE, deep: "334155",
      nodes: [{ t: "카메라 · 밤사이 RTSP" }, { t: "움직임 클립 선별 (Motion)" }, { t: "gecko-vision-gate · 개체 탐지", hl: true }] },
    { pill: "2 · Track A · 1차 판독", pf: C.A_FILL, pt: C.A_DEEP, panel: C.A_FILL2, bd: C.A_BORD, deep: C.A_DEEP,
      nodes: [{ t: "Zero-shot VLM 전수 판독" }, { t: "행동 라벨 + 자기확신 점수" }] },
    { pill: "3 · Track B · 정밀 판독", pf: C.B_FILL, pt: C.B_TEXT, panel: C.B_FILL2, bd: C.B_BORD, deep: C.B_TEXT,
      nodes: [{ t: "애매·중요 장면만 재분석" }, { t: "시간·위치·움직임 증거 결합" }] },
    { pill: "4 · 아침 활동 보고서", pf: C.G_FILL, pt: C.G_DEEP, panel: C.G_FILL2, bd: C.G_BORD, deep: C.G_DEEP,
      nodes: [{ t: "밤사이 행동 시간순 정리" }, { t: "아침에 보호자에게 전달" }] },
  ];
  const n = 4, agap = 0.5, pw = (CW - agap * (n - 1)) / n, py = 2.3, ph = 2.5;
  stages.forEach((st, i) => {
    const x = M.LM + i * (pw + agap);
    card(s, x, py, pw, ph, { fill: st.panel, border: st.bd, softSh: true });
    pill(s, x + 0.16, py + 0.16, pw - 0.32, 0.4, st.pill, st.pf, st.pt, 10.5);
    const areaTop = py + 0.7, areaBot = py + ph - 0.16, k = st.nodes.length, ng = 0.13;
    const nh = (areaBot - areaTop - (k - 1) * ng) / k;
    st.nodes.forEach((nd, j) => {
      const ny = areaTop + j * (nh + ng);
      const nf = nd.hl ? C.G_FILL2 : C.WHITE, nb = nd.hl ? C.G_BORD : C.LINE, nc = nd.hl ? C.G_DEEP : st.deep;
      card(s, x + 0.2, ny, pw - 0.4, nh, { fill: nf, border: nb, bw: nd.hl ? 1.25 : 1, sh: false, rad: 0.07 });
      s.addText(nd.t, { x: x + 0.22, y: ny, w: pw - 0.44, h: nh, fontFace: F.KR, fontSize: k >= 3 ? 9.6 : 10.8, bold: true, color: nc, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 0.98 });
      if (j < k - 1) s.addText("↓", { x: x + pw / 2 - 0.2, y: ny + nh - 0.03, w: 0.4, h: ng + 0.06, fontFace: F.KR, fontSize: 12, bold: true, color: C.FAINT, align: "center", valign: "middle", margin: 0 });
    });
    if (i < n - 1) s.addText("→", { x: x + pw + (agap - 0.5) / 2, y: py + ph / 2 - 0.22, w: 0.5, h: 0.44, fontFace: F.KR, fontSize: 22, bold: true, color: C.FAINT, align: "center", valign: "middle", margin: 0 });
  });

  // 사람 검수 루프 밴드
  const by = 5.02, bh = 0.5;
  card(s, M.LM, by, CW, bh, { fill: C.G_FILL2, border: C.G_BORD, sh: false, rad: bh / 2 });
  s.addText([
    { text: "↻  사람 검수 루프(HITL)", options: { bold: true, color: C.G_DEEP } },
    { text: "  —  애매한 결과를 사람이 확인해 다시 학습 데이터로 쌓고, 모델·규칙을 개선한다.", options: { color: C.G_DEEP } },
  ], { x: M.LM + 0.3, y: by, w: CW - 0.6, h: bh, fontFace: F.KR, fontSize: 11.5, align: "center", valign: "middle", margin: 0 });

  callout(s, M.LM, 5.72, CW, 0.95, [
    { text: "실시간 ‘케어 알림’이 아니다. ", options: { bold: true, color: C.DARK_ACC } },
    { text: "밤사이 도마뱀이 무엇을 했는지를 아침에 활동 보고서로 정리해 전달한다 — 녹화가 아니라 해석이다.", options: {} },
  ], { fs: 13.5 });
})();

// ============================================================
// SLIDE 2 — 실제 데이터
// ============================================================
(function s2() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "02 · 실제 데이터",
    title: "실제 장면을 보면 기술이 바로 이해된다",
    subtitle: "RBA는 도마뱀의 실제 행동 장면을 보고, 행동 라벨과 판단 근거를 함께 남긴다.",
    page: "본문 02 / 07",
  });

  const items = [
    { img: "rba-example-eating-paste.jpg", tag: "사료 섭취 · eating_paste", head: "그릇 + 반복 접촉", cap: "그릇이 보이고, 혀가 먹이 표면에 반복 접촉해야 섭취로 인정." },
    { img: "rba-example-eating-prey.jpg", tag: "먹이 사냥 · eating_prey", head: "먹이 보임 + 시선 고정", cap: "먹이가 같은 프레임에 보이고, 몸 방향·시선이 먹이에 고정된 사냥 자세." },
    { img: "rba-example-hand-feeding.jpg", tag: "사람 급여 · hand_feeding", head: "손·도구가 직접 전달", cap: "사람 손·도구가 먹이를 직접 전달하고, 받아먹는 장면은 별도 분리." },
  ];
  const n = 3, gap = 0.4, cw = (CW - gap * (n - 1)) / n;
  const y = 2.26, ch = 3.62;
  const iw = cw - 0.36, ih = 1.9;
  items.forEach((it, i) => {
    const x = M.LM + i * (cw + gap);
    card(s, x, y, cw, ch, { fill: C.WHITE, border: C.LINE, softSh: true });
    s.addImage({ path: path.join(IMG, it.img), x: x + 0.18, y: y + 0.16, w: iw, h: ih, sizing: { type: "cover", w: iw, h: ih } });
    const base = y + 0.16 + ih;
    pill(s, x + 0.18, base + 0.14, iw, 0.34, it.tag, C.A_FILL, C.A_DEEP, 10.5);
    s.addText(it.head, { x: x + 0.2, y: base + 0.6, w: cw - 0.4, h: 0.32, fontFace: F.KR, fontSize: 14, bold: true, color: C.INK, margin: 0 });
    s.addText(it.cap, { x: x + 0.2, y: base + 0.94, w: cw - 0.4, h: 0.6, fontFace: F.KR, fontSize: 10.8, color: C.MUTED, margin: 0, valign: "top", lineSpacingMultiple: 1.1 });
  });

  callout(s, M.LM, 6.0, CW, 0.82, [
    { text: "Track A는 라벨 하나만 남기지 않는다. ", options: {} },
    { text: "행동 + 자기확신 점수 + 판단 근거", options: { bold: true, color: C.DARK_ACC } },
    { text: "를 함께 남기고, 이 근거가 다음 정밀 판독·사람 검수의 출발점이 된다.", options: {} },
  ], { fs: 13 });
})();

// ============================================================
// SLIDE 3 — Track A
// ============================================================
(function s3() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "03 · 빠른 1차 판독 AI (Track A)",
    title: "빠른 1차 판독 AI(Track A)는 모든 움직임을 먼저 훑는다",
    subtitle: "Track A는 모든 움직임 클립을 빠르게 훑고, 행동 라벨과 ‘AI 자기확신 점수’를 함께 남긴다.",
    page: "본문 03 / 07",
  });

  const topY = 2.3;
  // LEFT: labels + output
  const lx = M.LM, lw = 6.0;
  s.addText("행동 라벨 7종 + 이상행동(개발 예정)", { x: lx, y: topY, w: lw, h: 0.3, fontFace: F.KR, fontSize: 13, bold: true, color: C.INK, margin: 0 });
  const labels = [
    { t: "Drinking · 음수", w: 1.55 },
    { t: "Eating paste · 사료 섭취", w: 2.55 },
    { t: "Eating prey · 먹이 사냥", w: 2.55 },
    { t: "Hand feeding · 사람 급여", w: 2.6 },
    { t: "Shedding · 탈피", w: 1.5 },
    { t: "Moving · 이동", w: 1.5 },
    { t: "Unseen · 미관측", w: 1.7 },
    { t: "이상행동 · 개발 예정", w: 2.55, planned: true },
  ];
  let py = topY + 0.4; const ph = 0.38, pgap = 0.12;
  let cx = lx, cy = py;
  labels.forEach((L) => {
    if (cx + L.w > lx + lw + 0.02) { cx = lx; cy += ph + pgap; }
    if (L.planned) {
      s.addShape(R, { x: cx, y: cy, w: L.w, h: ph, fill: { color: C.A_FILL2 }, line: { color: C.A_BORD, width: 1.25, dashType: "dash" }, rectRadius: ph / 2 });
      s.addText(L.t, { x: cx, y: cy - 0.01, w: L.w, h: ph, fontFace: F.KR, fontSize: 10.5, bold: true, color: C.A_DEEP, align: "center", valign: "middle", margin: 0 });
    } else {
      pill(s, cx, cy, L.w, ph, L.t, C.CARD2, C.INK, 10.5);
    }
    cx += L.w + pgap;
  });
  const outY = cy + ph + 0.28;
  s.addText("출력 형식", { x: lx, y: outY, w: lw, h: 0.28, fontFace: F.KR, fontSize: 13, bold: true, color: C.INK, margin: 0 });
  card(s, lx, outY + 0.36, lw, 0.56, { fill: C.CARD2, border: C.LINE, sh: false, rad: 0.08 });
  s.addText("{ action, confidence, reasoning }", { x: lx, y: outY + 0.36, w: lw, h: 0.56, fontFace: F.MONO, fontSize: 14.5, bold: true, color: C.A_DEEP, align: "center", valign: "middle", margin: 0 });

  // RIGHT: confidence 3 tiers
  const rx = M.LM + 6.5, rw = CW - 6.5;
  s.addText("AI 자기확신 점수 3단계", { x: rx, y: topY, w: rw, h: 0.3, fontFace: F.KR, fontSize: 13, bold: true, color: C.INK, margin: 0 });
  const tiers = [
    { t: "0.9 이상 · 명확", d: "행동 증거가 분명하다. 1차 라벨로 바로 쓴다.", fill: C.A_FILL2, bd: C.A_BORD, tc: C.A_DEEP },
    { t: "0.6 – 0.8 · 부분적", d: "가림·짧은 장면·일부 증거. 필요하면 정밀 판독으로 넘긴다.", fill: C.CARD, bd: C.LINE, tc: C.INK },
    { t: "0.5 이하 · 애매", d: "제한된 증거에서의 최선 추정. 정밀 판독·사람 검수 우선.", fill: C.CARD, bd: C.LINE, tc: C.INK },
  ];
  let ty = topY + 0.42; const th = 0.86, tgap = 0.16;
  tiers.forEach((tr) => {
    card(s, rx, ty, rw, th, { fill: tr.fill, border: tr.bd });
    s.addText(tr.t, { x: rx + 0.25, y: ty + 0.12, w: rw - 0.5, h: 0.3, fontFace: F.KR, fontSize: 13.5, bold: true, color: tr.tc, margin: 0 });
    s.addText(tr.d, { x: rx + 0.25, y: ty + 0.44, w: rw - 0.5, h: 0.36, fontFace: F.KR, fontSize: 11, color: C.MUTED, margin: 0, valign: "top", lineSpacingMultiple: 1.05 });
    ty += th + tgap;
  });

  callout(s, M.LM, 5.95, CW, 0.98, [
    { text: "‘AI 자기확신 점수(confidence)’는 정답 확률이 아니다. ", options: { bold: true, color: C.DARK_ACC } },
    { text: "AI가 스스로 매긴 확실성 신호이며, 정밀 판독(Track B)이나 사람 검수로 보낼지 판단하는 데 쓴다.", options: {} },
  ], { fs: 13.5 });
})();

// ============================================================
// SLIDE 4 — 프롬프트 = 판독 체크리스트
// ============================================================
(function s4() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "04 · 판독 매뉴얼",
    title: "프롬프트는 AI에게 주는 행동 판독 체크리스트다",
    subtitle: "RBA의 프롬프트는 AI가 행동을 과잉 해석하지 않도록 ‘증거 기준’을 정해주는 판독 매뉴얼이다.",
    page: "본문 04 / 07",
  });

  const cols = [
    { tag: "입력", head: "60초 움직임 클립", body: ["밤사이 움직임 구간을 프레임으로 샘플링", "종 정보와 함께 AI에 전달"] },
    { tag: "판독 기준", head: "행동 라벨 7종", body: ["먹이·음수·탈피·이동·미관측", "사람 급여는 별도 행동", "모호하면 기본값 moving"] },
    { tag: "결정 규칙", head: "증거 없으면 판단 금지", body: ["그릇 근처에 있음 ≠ 먹음", "paste는 혀·먹이 반복 접촉 필요", "drinking은 한 지점 반복 핥기"] },
    { tag: "출력", head: "JSON 결과", body: ["앱과 정밀 판독이 바로 읽는 구조", "action + confidence + reasoning"] },
  ];
  const n = 4, gap = 0.32, cw = (CW - gap * (n - 1)) / n, y = 2.35, ch = 2.35;
  cols.forEach((col, i) => {
    const x = M.LM + i * (cw + gap);
    card(s, x, y, cw, ch, { fill: C.CARD, border: C.LINE, softSh: true });
    pill(s, x + 0.24, y + 0.24, 1.2, 0.36, col.tag, C.A_FILL, C.A_DEEP, 11);
    s.addText(col.head, { x: x + 0.24, y: y + 0.72, w: cw - 0.48, h: 0.6, fontFace: F.KR, fontSize: 14.5, bold: true, color: C.INK, margin: 0, valign: "top", lineSpacingMultiple: 1.05 });
    s.addText(col.body.map((b, j) => ({ text: b, options: { bullet: { indent: 12 }, breakLine: true, color: C.MUTED, fontSize: 10.8, paraSpaceAfter: 4 } })),
      { x: x + 0.26, y: y + 1.32, w: cw - 0.5, h: 0.95, fontFace: F.KR, margin: 0, valign: "top", lineSpacingMultiple: 1.02 });
    if (i < n - 1) arrow(s, x + cw + (gap - 0.5) / 2, y + ch / 2 - 0.2, 0.5, C.FAINT);
  });

  // 판정 예시 2 cards
  const ey = 4.95, eh = 0.92, egap = 0.32, ew = (CW - egap) / 2;
  const ex = [
    { n: "판정 예시 1", runs: [{ text: "먹이그릇 근처지만 혀 접촉이 안 보이면 ", options: { color: C.MUTED } }, { text: "eating_paste가 아니라 moving", options: { bold: true, color: C.INK } }, { text: " 후보로 둔다.", options: { color: C.MUTED } }] },
    { n: "판정 예시 2", runs: [{ text: "몸이 고정되고 한 지점을 반복해서 핥으면, 물방울이 안 보여도 ", options: { color: C.MUTED } }, { text: "drinking", options: { bold: true, color: C.INK } }, { text: " 후보로 본다.", options: { color: C.MUTED } }] },
  ];
  ex.forEach((e, i) => {
    const x = M.LM + i * (ew + egap);
    card(s, x, ey, ew, eh, { fill: C.A_FILL2, border: C.A_BORD, sh: false });
    s.addText(e.n, { x: x + 0.26, y: ey + 0.14, w: ew - 0.5, h: 0.3, fontFace: F.KR, fontSize: 11.5, bold: true, color: C.A_DEEP, margin: 0 });
    s.addText(e.runs, { x: x + 0.26, y: ey + 0.46, w: ew - 0.5, h: 0.4, fontFace: F.KR, fontSize: 12, margin: 0, valign: "top", lineSpacingMultiple: 1.05 });
  });

  s.addText("현재 v4.0 프롬프트는 자체 회귀 평가를 통과해 채택된 1차 판독 기준선이다. (평가 수치는 부록 2)", {
    x: M.LM, y: 6.12, w: CW, h: 0.35, fontFace: F.KR, fontSize: 11, italic: true, color: C.MUTED2, margin: 0,
  });
})();

// ============================================================
// SLIDE 5 — Track B (drinking recovery case)
// ============================================================
(function s5() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "05 · 정밀 판독 AI (Track B)",
    title: "정밀 판독 AI(Track B)는 애매한 장면을 증거와 함께 다시 본다",
    subtitle: "Track B는 애매한 장면을 시간·위치·움직임 같은 ‘판단 재료’와 함께 다시 분석한다.",
    page: "본문 05 / 07",
  });

  // LEFT image
  const iy = 2.35, ih = 2.75, iw = ih * (716 / 1080); // portrait
  const ix = M.LM;
  card(s, ix, iy, iw + 0.24, ih + 0.24, { fill: C.INK2, border: null, rad: 0.1 });
  s.addImage({ path: path.join(IMG, "rba-example-drinking.png"), x: ix + 0.12, y: iy + 0.12, w: iw, h: ih, sizing: { type: "cover", w: iw, h: ih } });
  s.addText("drinking 사례 · 물 마시는 결정적 순간", { x: ix - 0.15, y: iy + ih + 0.36, w: iw + 0.54, h: 0.3, fontFace: F.KR, fontSize: 10.5, bold: true, color: C.MUTED, align: "center", margin: 0 });

  // RIGHT 3-step flow
  const rx = ix + iw + 0.7, rw = RIGHT - rx;
  const steps = [
    { tag: "1 · 빠른 1차 판독 (Track A)", body: "eating_paste(사료 섭취) 후보 — 자기확신 점수 낮음", fill: C.A_FILL2, bd: C.A_BORD, tc: C.A_DEEP },
    { tag: "2 · 정밀 판독 (Track B)", body: "물그릇 관심 구역(ROI), 머리 위치, 혀 동작을 증거와 함께 재확인", fill: C.B_FILL2, bd: C.B_BORD, tc: C.B_TEXT },
    { tag: "3 · 최종 판정", body: "drinking (음수) — 근거와 함께 확정", fill: C.G_FILL2, bd: C.G_BORD, tc: C.G_DEEP },
  ];
  let sy = iy + 0.05; const sh = 0.86, sgap = 0.32;
  steps.forEach((st, i) => {
    card(s, rx, sy, rw, sh, { fill: st.fill, border: st.bd });
    s.addText(st.tag, { x: rx + 0.28, y: sy + 0.13, w: rw - 0.56, h: 0.3, fontFace: F.KR, fontSize: 12.5, bold: true, color: st.tc, margin: 0 });
    s.addText(st.body, { x: rx + 0.28, y: sy + 0.44, w: rw - 0.56, h: 0.38, fontFace: F.KR, fontSize: 11.5, color: C.INK, margin: 0, valign: "top", lineSpacingMultiple: 1.05 });
    if (i < 2) s.addText("↓", { x: rx + rw / 2 - 0.25, y: sy + sh - 0.02, w: 0.5, h: sgap, fontFace: F.KR, fontSize: 18, bold: true, color: C.FAINT, align: "center", valign: "middle", margin: 0 });
    sy += sh + sgap;
  });

  callout(s, M.LM, 5.95, CW, 0.92, [
    { text: "Track B는 단순히 ‘더 비싼 AI’가 아니다. ", options: { bold: true, color: C.DARK_ACC } },
    { text: "시간·위치·움직임 증거를 결합해 1차 판독의 오판을 바로잡고, 그 결과가 다시 데이터가 된다.", options: {} },
  ], { fs: 13.5 });
})();

// ============================================================
// SLIDE 6 — AI 자산 축적 단계
// ============================================================
(function s6() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "06 · AI 자산 축적",
    title: "RBA는 데이터가 쌓일수록 더 좋아지는 구조다",
    subtitle: "행동 라벨과 사람 검수 데이터가 쌓일수록, RBA는 도마뱀 특화 AI로 진화한다.",
    page: "본문 06 / 07",
  });

  const stages = [
    { badge: "1단계 · RBA 1.0 (현재·베타)", head: "빠른 1차 + 정밀 판독", body: ["크레스티드 게코 대상", "자동 분석 + 사람 검수로 라벨 품질 향상", "앱에서 자동 라벨·밤사이 요약 제공"] },
    { badge: "2단계 · RBA 1.5", head: "선별적 정밀 분석", body: ["확실한 행동은 1차에서 바로 확정", "모호·중요 행동만 정밀 판독", "비용과 정확도를 동시에"] },
    { badge: "3단계 · RBA 2.0", head: "자체 특화 모델", body: ["자체 서버 + 도마뱀 특화 모델", "증거 기반 앙상블로 오판 보정", "외부 AI 의존도↓ · 단위 비용 통제"] },
  ];
  const n = 3, gap = 0.5, cw = (CW - gap * (n - 1)) / n, y = 2.35, ch = 2.5;
  stages.forEach((st, i) => {
    const x = M.LM + i * (cw + gap);
    card(s, x, y, cw, ch, { fill: C.CARD, border: C.LINE, softSh: true });
    // badge (dark rounded pill)
    pill(s, x + 0.26, y + 0.26, cw - 0.52, 0.4, st.badge, C.INK, C.WHITE, 11);
    s.addText(st.head, { x: x + 0.28, y: y + 0.8, w: cw - 0.56, h: 0.4, fontFace: F.KR, fontSize: 15.5, bold: true, color: C.INK, margin: 0 });
    s.addText(st.body.map((b) => ({ text: b, options: { bullet: { indent: 12 }, breakLine: true, color: C.MUTED, fontSize: 11, paraSpaceAfter: 5 } })),
      { x: x + 0.3, y: y + 1.28, w: cw - 0.58, h: 1.1, fontFace: F.KR, margin: 0, valign: "top", lineSpacingMultiple: 1.02 });
    if (i < n - 1) arrow(s, x + cw + (gap - 0.5) / 2, y + ch / 2 - 0.2, 0.5, C.MUTED2);
  });

  callout(s, M.LM, 5.2, CW, 1.35, [
    { text: "다종 확장", options: { bold: true, color: C.DARK_ACC } },
    { text: "  —  크레스티드 게코를 넘어 인기 파충류·양서류로 분석 대상을 넓힌다. ", options: {} },
    { text: "종이 늘고 데이터가 쌓일수록 그대로 모델 실력이 되는 선순환", options: { bold: true, color: C.WHITE } },
    { text: "이 만들어지고, 이것이 장기 진입장벽이 된다.", options: {} },
  ], { fs: 14 });
})();

// ============================================================
// SLIDE 7 — 해자
// ============================================================
(function s7() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "07 · 해자",
    title: "우리의 해자는 영상 AI·특화 모델·사육 규칙의 결합이다",
    subtitle: "외부 AI 하나를 쓰는 게 아니라 영상 AI·우리 데이터·사육 규칙을 결합하기 때문에, 시간이 갈수록 복제 난이도가 올라간다.",
    page: "본문 07 / 07",
  });

  const parts = [
    { head: "영상을 이해하는 AI", sub: "VLM", body: "영상을 보고 의미를 해석하는 범용 시각 AI", fill: C.BL_FILL2, bd: C.BL_BORD, tc: C.BL_TEXT },
    { head: "특화 모델", sub: "fine-tuned", body: "라벨 데이터로 학습하는 도마뱀 행동 AI", fill: C.G_FILL2, bd: C.G_BORD, tc: C.G_DEEP },
    { head: "사육 규칙", sub: "domain rules", body: "도메인 기준으로 AI 오판을 보정", fill: C.B_FILL2, bd: C.B_BORD, tc: C.B_TEXT },
    { head: "판단 재료 묶음", sub: "context packet", body: "시간·ROI·움직임·전후 맥락을 함께 제공", fill: C.A_FILL2, bd: C.A_BORD, tc: C.A_DEEP },
  ];
  const n = 4, opW = 0.42, gap = 0.28;
  const cw = (CW - opW * (n - 1) - gap * 2 * (n - 1)) / n; // account for +signs with padding
  const cwFinal = (CW - (opW + gap * 2) * (n - 1)) / n;
  const y = 2.4, ch = 2.15;
  parts.forEach((p, i) => {
    const x = M.LM + i * (cwFinal + opW + gap * 2);
    card(s, x, y, cwFinal, ch, { fill: p.fill, border: p.bd });
    s.addText(p.head, { x: x + 0.2, y: y + 0.42, w: cwFinal - 0.4, h: 0.6, fontFace: F.KR, fontSize: 15, bold: true, color: p.tc, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 1.0 });
    s.addText(p.sub, { x: x + 0.2, y: y + 1.0, w: cwFinal - 0.4, h: 0.28, fontFace: F.MONO, fontSize: 10.5, color: C.MUTED, align: "center", margin: 0 });
    s.addText(p.body, { x: x + 0.18, y: y + 1.34, w: cwFinal - 0.36, h: 0.7, fontFace: F.KR, fontSize: 10.8, color: C.INK, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.12 });
    if (i < n - 1) plusSign(s, x + cwFinal + gap, y + ch / 2 - 0.25, opW, C.MUTED2);
  });

  callout(s, M.LM, 5.05, CW, 1.5, [
    { text: "= 최종 행동 판단", options: { bold: true, color: C.DARK_ACC, fontSize: 16 } },
    { text: "\n", options: { fontSize: 8 } },
    { text: "RBA의 핵심 자산은 모델 하나가 아니라, ", options: {} },
    { text: "행동 데이터와 사육 맥락이 함께 쌓이는 판단 구조", options: { bold: true, color: C.WHITE } },
    { text: "다. 외부 AI를 그대로 가져다 쓰는 경쟁자가 따라오기 어려운 지점이 바로 여기다.", options: {} },
  ], { fs: 14 });
})();

// ============================================================
// APPENDIX DIVIDER
// ============================================================
(function divider() {
  const s = pres.addSlide();
  s.background = { color: C.DARK2 };
  s.addText("APPENDIX", { x: M.LM, y: 2.7, w: CW, h: 0.5, fontFace: F.KR, fontSize: 15, bold: true, color: C.DARK_ACC, charSpacing: 3, margin: 0 });
  s.addText("부록 · 상세 기술 구조", { x: M.LM, y: 3.2, w: CW, h: 1.0, fontFace: F.KR, fontSize: 40, bold: true, color: C.WHITE, margin: 0 });
  s.addText("본문 7장의 근거가 되는 상세 자료 — ① RBA 전체 구조도   ② Track A 프롬프트·평가 수치   ③ 판단 재료 묶음(structured context packet)", {
    x: M.LM, y: 4.35, w: 11.5, h: 0.7, fontFace: F.KR, fontSize: 14.5, color: C.MUTED2, margin: 0, valign: "top", lineSpacingMultiple: 1.2,
  });
})();

// ============================================================
// APPENDIX 1 — RBA 전체 구조도
// ============================================================
(function a1() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "부록 1 · 전체 구조도",
    title: "RBA 1.0 전체 관계도",
    subtitle: "밤사이 RTSP 영상을 행동 타임라인과 아침 활동 보고서로 바꾸는 AI 분석 시스템의 전체 흐름.",
    page: "부록 01 / 03",
  });

  const colY = 2.35;
  const colW = (CW - 0.7 * 2) / 3;
  const colX = [M.LM, M.LM + colW + 0.7, M.LM + (colW + 0.7) * 2];
  const heads = ["수집 / 저장", "Track A — 전수 1차 라벨링", "Track B — 정밀 분석 / 회복"];
  const headColors = [C.G_DEEP, C.A_DEEP, C.B_TEXT];
  heads.forEach((h, i) => s.addText(h, { x: colX[i], y: colY, w: colW, h: 0.32, fontFace: F.KR, fontSize: 12.5, bold: true, color: headColors[i], align: "center", margin: 0 }));

  const bh = 0.62, bgap = 0.26; const by0 = colY + 0.5;
  function box(x, yIndex, w, title, sub, fill, bd, tc) {
    const y = by0 + yIndex * (bh + bgap);
    card(s, x, y, w, bh, { fill, border: bd, sh: false, rad: 0.09 });
    s.addText([{ text: title, options: { bold: true, fontSize: 11.5, color: tc, breakLine: true } }, { text: sub, options: { fontSize: 8.8, color: C.MUTED } }],
      { x: x + 0.1, y: y + 0.06, w: w - 0.2, h: bh - 0.12, fontFace: F.KR, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 0.98 });
    return y;
  }
  function vArrow(x, yIndex, w) {
    const y = by0 + yIndex * (bh + bgap) + bh - 0.02;
    s.addText("↓", { x: x + w / 2 - 0.2, y, w: 0.4, h: bgap + 0.04, fontFace: F.KR, fontSize: 14, bold: true, color: C.FAINT, align: "center", valign: "middle", margin: 0 });
  }

  // Col1: 수집/저장
  box(colX[0], 0, colW, "카메라 / 자체 HW", "밤사이 RTSP 영상", C.CARD2, C.LINE, C.INK); vArrow(colX[0], 0, colW);
  box(colX[0], 1, colW, "Capture Worker", "1분 mp4 생성", C.CARD2, C.LINE, C.INK); vArrow(colX[0], 1, colW);
  box(colX[0], 2, colW, "Motion Detection", "움직임 있는 클립 선별", C.G_FILL2, C.G_BORD, C.G_DEEP); vArrow(colX[0], 2, colW);
  // storage split (two half boxes on row 3)
  const y3 = by0 + 3 * (bh + bgap); const hw = (colW - 0.2) / 2;
  card(s, colX[0], y3, hw, bh, { fill: C.BL_FILL2, border: C.BL_BORD, sh: false, rad: 0.09 });
  s.addText([{ text: "Supabase", options: { bold: true, fontSize: 10.5, color: C.BL_TEXT, breakLine: true } }, { text: "clip metadata", options: { fontSize: 8.5, color: C.MUTED } }], { x: colX[0], y: y3 + 0.06, w: hw, h: bh - 0.12, fontFace: F.KR, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 0.98 });
  card(s, colX[0] + hw + 0.2, y3, hw, bh, { fill: C.BL_FILL2, border: C.BL_BORD, sh: false, rad: 0.09 });
  s.addText([{ text: "R2 Storage", options: { bold: true, fontSize: 10.5, color: C.BL_TEXT, breakLine: true } }, { text: "영상 / 썸네일", options: { fontSize: 8.5, color: C.MUTED } }], { x: colX[0] + hw + 0.2, y: y3 + 0.06, w: hw, h: bh - 0.12, fontFace: F.KR, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 0.98 });

  // Col2: Track A
  box(colX[1], 0, colW, "증거 레이어", "메타데이터 · ROI · 모션 단서", C.A_FILL2, C.A_BORD, C.A_DEEP); vArrow(colX[1], 0, colW);
  box(colX[1], 1, colW, "Track A · Zero-shot VLM", "top-1 행동 라벨 + confidence", C.A_FILL, C.A_BORD, C.A_DEEP); vArrow(colX[1], 1, colW);
  // decision diamond (as pill)
  const yd = by0 + 2 * (bh + bgap);
  card(s, colX[1] + colW / 2 - 1.1, yd, 2.2, bh, { fill: C.WHITE, border: C.MUTED2, sh: false, rad: 0.31 });
  s.addText("정밀 분석 필요?", { x: colX[1] + colW / 2 - 1.1, y: yd, w: 2.2, h: bh, fontFace: F.KR, fontSize: 11, bold: true, color: C.INK, align: "center", valign: "middle", margin: 0 });
  s.addText("예 →", { x: colX[1] + colW - 0.05, y: yd + 0.1, w: 0.8, h: 0.4, fontFace: F.KR, fontSize: 11, bold: true, color: C.B_TEXT, align: "left", valign: "middle", margin: 0 });
  s.addText("↓ 아니오", { x: colX[1] + colW / 2 - 0.2, y: yd + bh, w: 1.4, h: 0.3, fontFace: F.KR, fontSize: 10, color: C.MUTED, align: "center", margin: 0 });

  // Col3: Track B
  box(colX[2], 0, colW, "Track B · SegmentVLM", "정밀 분석 진입", C.B_FILL2, C.B_BORD, C.B_TEXT); vArrow(colX[2], 0, colW);
  box(colX[2], 1, colW, "event segment 분해", "5~15초 단위", C.B_FILL2, C.B_BORD, C.B_TEXT); vArrow(colX[2], 1, colW);
  box(colX[2], 2, colW, "ROI / motion metadata", "먹이그릇 · 물그릇 · 은신처", C.B_FILL2, C.B_BORD, C.B_TEXT); vArrow(colX[2], 2, colW);
  box(colX[2], 3, colW, "event별 AI 분석 → timeline 병합", "행동 후보 + 시간대 + 검수", C.BL_FILL2, C.BL_BORD, C.BL_TEXT);

  // bottom loop row
  const yb = by0 + 4 * (bh + bgap) + 0.16;
  card(s, colX[0], yb, colW, bh, { fill: C.G_FILL2, border: C.G_BORD, sh: false, rad: 0.09 });
  s.addText([{ text: "HITL · 사람 검수", options: { bold: true, fontSize: 11, color: C.G_DEEP, breakLine: true } }, { text: "평가셋 개선 → 모델·룰 개선", options: { fontSize: 8.8, color: C.MUTED } }], { x: colX[0], y: yb, w: colW, h: bh, fontFace: F.KR, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 0.98 });
  s.addText("→", { x: colX[0] + colW + 0.02, y: yb, w: 0.66, h: bh, fontFace: F.KR, fontSize: 16, bold: true, color: C.FAINT, align: "center", valign: "middle", margin: 0 });
  card(s, colX[1], yb, colW, bh, { fill: C.G_FILL, border: C.G_BORD, sh: false, rad: 0.09 });
  s.addText([{ text: "사용자 앱 · 아침 활동 보고서", options: { bold: true, fontSize: 11, color: C.G_DEEP, breakLine: true } }, { text: "밤사이 행동을 시간순 정리", options: { fontSize: 8.8, color: C.MUTED } }], { x: colX[1], y: yb, w: colW, h: bh, fontFace: F.KR, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 0.98 });
})();

// ============================================================
// APPENDIX 2 — Track A 프롬프트 상세 + 수치
// ============================================================
(function a2() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "부록 2 · 프롬프트 상세",
    title: "Track A 프롬프트(v4.0) — 규칙과 평가 수치",
    subtitle: "프롬프트는 “AI에게 주는 판독 체크리스트”다. 채택 근거가 되는 결정 규칙과 자체 평가 수치를 함께 둔다.",
    page: "부록 02 / 03",
  });

  // LEFT: 결정 규칙 상세
  const lx = M.LM, lw = 6.9, y = 2.35;
  s.addText("결정 규칙 (과잉 해석 방지)", { x: lx, y, w: lw, h: 0.3, fontFace: F.KR, fontSize: 13, bold: true, color: C.INK, margin: 0 });
  card(s, lx, y + 0.4, lw, 2.35, { fill: C.CARD, border: C.LINE, softSh: true });
  const rules = [
    "그릇 근처에 있음 ≠ 먹음 — 위치만으로 feeding 판단 금지",
    "eating_paste는 혀와 먹이 표면의 반복 접촉이 필요",
    "drinking은 몸을 고정하고 한 지점을 반복해 핥는 자세로 판단",
    "hand_feeding(사람 급여)은 다른 행동과 따로 분리",
    "증거가 모호하면 특정 행동으로 단정하지 말고 이동(moving)을 우선",
  ];
  s.addText(rules.map((r) => ({ text: r, options: { bullet: { indent: 14 }, breakLine: true, fontSize: 12, color: C.INK, paraSpaceAfter: 8 } })),
    { x: lx + 0.3, y: y + 0.62, w: lw - 0.6, h: 1.95, fontFace: F.KR, margin: 0, valign: "top", lineSpacingMultiple: 1.05 });

  s.addText("출력 형식", { x: lx, y: y + 2.95, w: lw, h: 0.3, fontFace: F.KR, fontSize: 13, bold: true, color: C.INK, margin: 0 });
  card(s, lx, y + 3.35, lw, 0.6, { fill: C.CARD2, border: C.LINE, sh: false, rad: 0.08 });
  s.addText("{ action, confidence, reasoning }  →  앱·Track B가 바로 읽는 JSON", { x: lx + 0.2, y: y + 3.35, w: lw - 0.4, h: 0.6, fontFace: F.MONO, fontSize: 11.5, color: C.A_DEEP, valign: "middle", margin: 0 });

  // RIGHT: stat cards + confidence 한계
  const rx = M.LM + 7.3, rw = RIGHT - rx;
  s.addText("v4.0 자체 회귀 평가 (채택 기준선)", { x: rx, y, w: rw, h: 0.3, fontFace: F.KR, fontSize: 13, bold: true, color: C.INK, margin: 0 });
  const stW = (rw - 0.3) / 2;
  const stats = [{ n: "85.9%", l: "raw 정확도" }, { n: "86.5%", l: "급여경계 정확도" }];
  stats.forEach((st, i) => {
    const x = rx + i * (stW + 0.3);
    card(s, x, y + 0.4, stW, 1.15, { fill: C.A_FILL2, border: C.A_BORD, softSh: true });
    s.addText(st.n, { x, y: y + 0.5, w: stW, h: 0.62, fontFace: F.KR, fontSize: 30, bold: true, color: C.A_DEEP, align: "center", margin: 0 });
    s.addText(st.l, { x, y: y + 1.12, w: stW, h: 0.32, fontFace: F.KR, fontSize: 11, color: C.MUTED, align: "center", margin: 0 });
  });
  s.addText("confidence의 한계", { x: rx, y: y + 1.85, w: rw, h: 0.3, fontFace: F.KR, fontSize: 13, bold: true, color: C.INK, margin: 0 });
  card(s, rx, y + 2.25, rw, 1.7, { fill: C.R_FILL, border: C.R_BORD, sh: false });
  s.addText([
    { text: "confidence는 정답 확률에 맞춘 값이 아닌, 모델의 자체 추정값", options: { bold: true, color: C.R_TEXT, fontSize: 12.5, breakLine: true, paraSpaceAfter: 6 } },
    { text: "0.95 이상 구간도 약 76% 정확도에 그쳐, 점수 하나만으로 나누기엔 부족했다.", options: { color: C.INK, fontSize: 11.5, breakLine: true, paraSpaceAfter: 6 } },
    { text: "→ 그래서 정밀 판독(Track B)·사람 검수와 결합해 신뢰도를 끌어올린다.", options: { color: C.INK, fontSize: 11.5 } },
  ], { x: rx + 0.28, y: y + 2.42, w: rw - 0.56, h: 1.4, fontFace: F.KR, margin: 0, valign: "top", lineSpacingMultiple: 1.1 });
})();

// ============================================================
// APPENDIX 3 — 판단 재료 묶음 (structured context packet)
// ============================================================
(function a3() {
  const s = pres.addSlide();
  s.background = { color: C.WHITE };
  header(s, {
    eyebrow: "부록 3 · 판단 재료 묶음",
    title: "판단 재료 묶음(structured context packet)",
    subtitle: "Track B에서 모델에게 그냥 “이 영상 봐봐”라고 던지는 대신, 영상 주변의 판단 재료를 구조화해 함께 준다.",
    page: "부록 03 / 03",
  });

  const y = 2.35, ch = 2.35, gap = 0.4, cw = (CW - gap) / 2;
  // bad input
  card(s, M.LM, y, cw, ch, { fill: C.R_FILL, border: C.R_BORD, softSh: true });
  s.addText("✕  나쁜 입력", { x: M.LM + 0.3, y: y + 0.24, w: cw - 0.6, h: 0.34, fontFace: F.KR, fontSize: 13.5, bold: true, color: C.R_TEXT, margin: 0 });
  s.addText("“이 영상에서 도마뱀이 뭐 하고 있어?”", { x: M.LM + 0.3, y: y + 0.85, w: cw - 0.6, h: 1.2, fontFace: F.KR, fontSize: 15, color: C.INK, margin: 0, valign: "top", lineSpacingMultiple: 1.2 });
  // good input
  const gx = M.LM + cw + gap;
  card(s, gx, y, cw, ch, { fill: C.G_FILL2, border: C.G_BORD, softSh: true });
  s.addText("✓  좋은 입력", { x: gx + 0.3, y: y + 0.24, w: cw - 0.6, h: 0.34, fontFace: F.KR, fontSize: 13.5, bold: true, color: C.G_DEEP, margin: 0 });
  s.addText("“이 클립은 03:27에 발생했고, 물그릇 ROI(관심 구역) 근처에서 움직임이 있었고, 개체는 크레스티드 게코이며, 최근 2일간 음수 이벤트가 없었고, 전후 10초 프레임에서 머리가 물그릇 방향으로 이동했다. 이 증거로 drinking / moving / unknown 중 판단하라.”", {
    x: gx + 0.3, y: y + 0.68, w: cw - 0.6, h: 1.55, fontFace: F.KR, fontSize: 11.8, color: C.INK, margin: 0, valign: "top", lineSpacingMultiple: 1.18,
  });

  callout(s, M.LM, 5.05, CW, 1.5, [
    { text: "정리  ", options: { bold: true, color: C.DARK_ACC } },
    { text: "지난 연구에서 검증했다 — 프롬프트만으로는 넘지 못하는 한계가 있었고, 모델에게 ‘볼 수 있는 증거’를 늘렸을 때 비로소 정확도가 올라갔다. 즉 다음 도약은 더 좋은 프롬프트가 아니라 ", options: {} },
    { text: "영상 주변의 증거를 구조화해 결합(VLM + 특화 모델 + 사육 규칙 앙상블)", options: { bold: true, color: C.WHITE } },
    { text: "하는 데 있다. 이것이 범용 AI를 그대로 가져다 쓰는 경쟁자가 따라오기 어려운 지점이다.", options: {} },
  ], { fs: 13.5 });
})();

// ---------- write ----------
const OUT = path.join(__dirname, "teraai-rba-investor.pptx");
pres.writeFile({ fileName: OUT }).then(() => console.log("WROTE", OUT)).catch((e) => { console.error(e); process.exit(1); });
