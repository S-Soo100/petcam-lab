"""RAP C500G manager의 dependency-free 로컬 dashboard."""

from __future__ import annotations


DASHBOARD_HTML = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RAP C500G 녹화 매니저</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #111310;
      --surface: #1a1d19;
      --surface-2: #232720;
      --line: #343a30;
      --text: #f4f3ea;
      --muted: #a9ad9e;
      --lime: #c6f36a;
      --green: #69d39e;
      --amber: #f3c96a;
      --red: #ff8279;
      --radius: 18px;
      --shadow: 0 18px 45px rgba(0, 0, 0, .22);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at 12% -5%, rgba(198,243,106,.10), transparent 30rem),
        linear-gradient(160deg, #151813 0%, var(--bg) 42%, #0e100d 100%);
      font-family: Pretendard, "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
    }
    button, input, select { font: inherit; }
    .shell { width: min(1380px, calc(100% - 40px)); margin: 0 auto; padding: 38px 0 72px; }
    header { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: 28px; }
    .eyebrow { margin: 0 0 8px; color: var(--lime); font-size: 12px; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(28px, 4vw, 48px); line-height: 1; letter-spacing: -.045em; }
    .lede { max-width: 620px; margin: 12px 0 0; color: var(--muted); line-height: 1.65; }
    .live-pill { display: inline-flex; align-items: center; gap: 9px; padding: 10px 14px; border: 1px solid var(--line); border-radius: 999px; background: rgba(26,29,25,.82); color: var(--muted); white-space: nowrap; }
    .live-pill::before { content: ""; width: 9px; height: 9px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 5px rgba(105,211,158,.12); }
    .summary-grid { display: grid; grid-template-columns: 1.45fr 1fr 1fr; gap: 16px; margin-bottom: 34px; }
    .panel, .summary-card, .camera-card { border: 1px solid var(--line); background: rgba(26,29,25,.94); box-shadow: var(--shadow); }
    .summary-card { min-height: 145px; padding: 24px; border-radius: var(--radius); }
    .summary-card.primary { background: linear-gradient(145deg, rgba(198,243,106,.14), rgba(26,29,25,.96) 62%); }
    .label { color: var(--muted); font-size: 12px; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
    .value { margin-top: 14px; font-size: clamp(20px, 2.6vw, 31px); font-weight: 760; letter-spacing: -.025em; }
    .subvalue { margin-top: 8px; color: var(--muted); font-size: 14px; line-height: 1.45; }
    section { margin-top: 34px; }
    .section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 18px; margin: 0 2px 15px; }
    h2 { margin: 0; font-size: 18px; letter-spacing: -.02em; }
    .section-note { color: var(--muted); font-size: 13px; }
    .camera-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
    .camera-card { overflow: hidden; border-radius: var(--radius); }
    .thumbnail-placeholder { aspect-ratio: 16 / 9; display: grid; place-items: center; position: relative; overflow: hidden; background: radial-gradient(circle at 50% 30%, #394032, #242820 52%, #191c17); color: #7d8375; }
    .thumbnail-placeholder::before { content: ""; width: 44%; aspect-ratio: 4 / 3; border: 1px solid #596052; border-radius: 12px; background: linear-gradient(135deg, transparent 48%, #596052 49% 51%, transparent 52%); opacity: .65; }
    .thumbnail-placeholder span { position: absolute; bottom: 14px; left: 16px; padding: 5px 9px; border-radius: 999px; background: rgba(10,12,9,.72); color: #bcc1b4; font-size: 11px; }
    .camera-body { padding: 21px; }
    .camera-title { display: flex; justify-content: space-between; align-items: center; gap: 14px; }
    .camera-title strong { font-size: 20px; }
    .ip { margin-top: 5px; color: var(--muted); font-variant-numeric: tabular-nums; }
    .badge { padding: 6px 10px; border-radius: 999px; background: rgba(105,211,158,.12); color: var(--green); font-size: 12px; font-weight: 750; }
    .badge.warn { background: rgba(243,201,106,.13); color: var(--amber); }
    .badge.bad { background: rgba(255,130,121,.13); color: var(--red); }
    .camera-metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-top: 20px; }
    .metric { min-height: 74px; padding: 14px; border-radius: 13px; background: var(--surface-2); }
    .metric b { display: block; margin-top: 8px; font-size: 15px; }
    .two-col { display: grid; grid-template-columns: 1.3fr .7fr; gap: 18px; }
    .panel { padding: 24px; border-radius: var(--radius); }
    .feed { display: grid; gap: 10px; margin-top: 18px; }
    .feed-item { display: grid; grid-template-columns: minmax(110px,.55fr) 1fr auto; gap: 16px; align-items: center; padding: 15px 16px; border-radius: 13px; background: var(--surface-2); }
    .feed-item span { color: var(--muted); font-size: 13px; }
    .empty { padding: 24px; border: 1px dashed var(--line); border-radius: 13px; color: var(--muted); text-align: center; }
    .settings { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-top: 18px; }
    .field { display: grid; gap: 8px; }
    .field.full { grid-column: 1 / -1; }
    .field label { color: var(--muted); font-size: 13px; }
    input, select { width: 100%; padding: 12px 13px; border: 1px solid var(--line); border-radius: 11px; background: #141612; color: var(--text); }
    .checks { display: flex; flex-wrap: wrap; gap: 10px; }
    .check { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 11px; background: #141612; }
    .check input { width: auto; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
    button { cursor: pointer; border: 0; border-radius: 11px; padding: 12px 15px; color: #151910; background: var(--lime); font-weight: 800; }
    button.secondary { border: 1px solid var(--line); color: var(--text); background: var(--surface-2); }
    button:disabled { cursor: not-allowed; opacity: .5; }
    .message { min-height: 20px; margin-top: 12px; color: var(--muted); font-size: 13px; }
    @media (max-width: 980px) {
      .summary-grid, .camera-grid { grid-template-columns: 1fr 1fr; }
      .summary-card.primary { grid-column: 1 / -1; }
      .two-col { grid-template-columns: 1fr; }
    }
    @media (max-width: 640px) {
      .shell { width: min(100% - 24px, 1380px); padding-top: 24px; }
      header { align-items: flex-start; flex-direction: column; }
      .summary-grid, .camera-grid, .settings { grid-template-columns: 1fr; }
      .summary-card.primary, .field.full { grid-column: auto; }
      .feed-item { grid-template-columns: 1fr; gap: 6px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <p class="eyebrow">RAP Academy · Field Recorder</p>
        <h1>야간 녹화 매니저</h1>
        <p class="lede">Mac mini가 카메라 3대의 30분 구간을 독립적으로 관리해. 이 화면을 닫아도 녹화는 계속돼.</p>
      </div>
      <div class="live-pill" id="updated">상태 불러오는 중</div>
    </header>

    <div class="summary-grid">
      <article class="summary-card primary">
        <div class="label">현재 구간</div><div class="value" id="current-slot">—</div>
        <div class="subvalue" id="manager-state">매니저 상태 확인 중</div>
      </article>
      <article class="summary-card">
        <div class="label">외장 저장소</div><div class="value" id="volume-name">—</div>
        <div class="subvalue" id="volume-state">마운트 확인 중</div>
      </article>
      <article class="summary-card">
        <div class="label">R2 · DB 동기화</div><div class="value" id="sync-count">—</div>
        <div class="subvalue">녹화와 분리된 후처리 대기열</div>
      </article>
    </div>

    <section>
      <div class="section-head"><h2>카메라 상태</h2><span class="section-note">3초마다 자동 갱신</span></div>
      <div class="camera-grid" id="camera-grid"></div>
    </section>

    <section class="two-col">
      <article class="panel">
        <div class="section-head"><h2>최근 완료</h2><span class="section-note">로컬 · R2 · DB</span></div>
        <div class="feed" id="completed"></div>
      </article>
      <article class="panel">
        <div class="section-head"><h2>최근 알림</h2><span class="section-note">복구와 조치 필요</span></div>
        <div class="feed" id="incidents"></div>
      </article>
    </section>

    <section class="two-col">
      <article class="panel">
        <div class="section-head"><h2>녹화 설정</h2><span class="section-note">다음 00/30 경계부터 적용</span></div>
        <form id="settings-form">
          <div class="settings">
            <div class="field"><label for="start">시작 시각</label><input id="start" type="time" required></div>
            <div class="field"><label for="end">종료 시각</label><input id="end" type="time" required></div>
            <div class="field full"><label>등록 카메라</label><div class="checks" id="camera-checks"></div></div>
            <div class="field"><label for="volume">외장 저장소</label><select id="volume" required></select></div>
            <div class="field"><label for="retries">자동 재시도 횟수</label><select id="retries"><option>0</option><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></div>
          </div>
          <div class="actions"><button type="submit">저장하고 다음 경계부터 적용</button></div>
          <div class="message" id="settings-message"></div>
        </form>
      </article>
      <article class="panel">
        <div class="section-head"><h2>설치 진단</h2><span class="section-note">프로덕션 중에는 차단</span></div>
        <p class="lede">등록된 카메라 3대를 정확히 60초간 테스트 경로에 녹화하고 썸네일·로그·업로드 결과를 확인해.</p>
        <div class="actions">
          <button class="secondary" id="probe-button" type="button">카메라 연결 점검</button>
          <button id="diagnostic-button" type="button">60초 진단 녹화</button>
        </div>
        <div class="message" id="diagnostic-message"></div>
      </article>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const size = (bytes) => bytes ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : '0 MB';
    const badge = (state) => state === 'failed_terminal' ? 'bad' : state === 'retry_wait' ? 'warn' : '';
    const empty = (text) => `<div class="empty">${esc(text)}</div>`;

    async function loadStatus() {
      const response = await fetch('/api/status', {cache: 'no-store'});
      if (!response.ok) throw new Error('상태 조회 실패');
      const data = await response.json();
      $('updated').textContent = `갱신 ${new Date(data.updated_at).toLocaleTimeString('ko-KR')}`;
      $('current-slot').textContent = data.current_slot ? new Date(data.current_slot).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'}) : '대기 중';
      $('manager-state').textContent = data.manager_state;
      $('volume-name').textContent = data.volume.name || '선택 안 됨';
      $('volume-state').textContent = data.volume.ready ? `정상 · 여유 ${(data.volume.free_bytes / 1024 / 1024 / 1024).toFixed(1)} GB` : `녹화 차단 · ${data.volume.reason || '확인 필요'}`;
      $('sync-count').textContent = `${data.sync.pending || 0} 대기`;
      const cameras = Object.values(data.cameras || {});
      $('camera-grid').innerHTML = cameras.map(cam => `
        <article class="camera-card">
          <div class="thumbnail-placeholder"><span>최신 썸네일 준비 영역</span></div>
          <div class="camera-body">
            <div class="camera-title"><div><strong>${esc(cam.camera_key)}</strong><div class="ip">${esc(cam.ip)}</div></div><span class="badge ${badge(cam.capture_state)}">${esc(cam.capture_state)}</span></div>
            <div class="camera-metrics">
              <div class="metric"><span class="label">RTSP</span><b>${esc(cam.probe_state)}</b></div>
              <div class="metric"><span class="label">현재 파일</span><b>${size(cam.file_bytes)}</b></div>
              <div class="metric"><span class="label">마지막 프레임</span><b>${cam.last_frame_at ? new Date(cam.last_frame_at).toLocaleTimeString('ko-KR') : '—'}</b></div>
              <div class="metric"><span class="label">복구</span><b>${cam.retry_count} / 3</b></div>
            </div>
          </div>
        </article>`).join('') || empty('카메라 상태가 아직 없어');
      $('completed').innerHTML = (data.recent_completed || []).map(item => `<div class="feed-item"><strong>${esc(item.camera_key)}</strong><span>${esc(item.slot)}</span><span>${item.partial ? '부분' : '완료'}</span></div>`).join('') || empty('완료된 구간이 아직 없어');
      $('incidents').innerHTML = (data.incidents || []).map(item => `<div class="feed-item"><strong>${esc(item.camera_key || item.state)}</strong><span>${esc(item.code || item.slot)}</span><span>${esc(item.state)}</span></div>`).join('') || empty('최근 알림 없음');
      $('diagnostic-button').disabled = data.manager_state === 'recording';
    }

    async function loadSettings() {
      const [settingsResponse, volumesResponse] = await Promise.all([fetch('/api/settings'), fetch('/api/volumes')]);
      const settings = await settingsResponse.json();
      const volumes = await volumesResponse.json();
      const plan = settings.pending || settings.active;
      $('start').value = plan.start_local; $('end').value = plan.end_local; $('retries').value = String(plan.max_capture_retries);
      $('camera-checks').innerHTML = settings.registered_cameras.map(key => `<label class="check"><input type="checkbox" name="camera" value="${esc(key)}" ${plan.selected_cameras.includes(key) ? 'checked' : ''}>${esc(key)}</label>`).join('');
      $('volume').innerHTML = volumes.map(v => `<option value="${esc(v.name)}" ${v.name === plan.volume_name ? 'selected' : ''}>${esc(v.name)} · ${v.ready ? '사용 가능' : esc(v.reason)}</option>`).join('');
    }

    $('settings-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const selected = [...document.querySelectorAll('input[name="camera"]:checked')].map(node => node.value);
      const response = await fetch('/api/settings/pending', {method:'PUT', headers:{'content-type':'application/json'}, body:JSON.stringify({start_local:$('start').value,end_local:$('end').value,selected_cameras:selected,volume_name:$('volume').value,max_capture_retries:Number($('retries').value)})});
      $('settings-message').textContent = response.ok ? '저장했어. 다음 00/30 경계부터 적용돼.' : '설정을 저장하지 못했어. 입력값을 확인해.';
    });
    $('probe-button').addEventListener('click', async () => { $('diagnostic-message').textContent = '연결 점검 중…'; const r = await fetch('/api/probes/cameras', {method:'POST'}); const d = await r.json(); $('diagnostic-message').textContent = d.map(x => `${x.camera_key}: ${x.rtsp ? '정상' : x.error_code}`).join(' · '); });
    $('diagnostic-button').addEventListener('click', async () => { $('diagnostic-message').textContent = '60초 진단 녹화 중…'; const r = await fetch('/api/diagnostics/recording', {method:'POST'}); $('diagnostic-message').textContent = r.ok ? '진단 녹화와 동기화를 완료했어.' : '현재 녹화 중이거나 저장소를 사용할 수 없어.'; });
    Promise.all([loadStatus(), loadSettings()]).catch(() => { $('updated').textContent = '상태 연결 실패'; });
    setInterval(() => loadStatus().catch(() => { $('updated').textContent = '상태 연결 실패'; }), 3000);
  </script>
</body>
</html>
"""
