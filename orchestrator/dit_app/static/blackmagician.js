(() => {
  const el = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const localProject = () => typeof state !== 'undefined' ? state.project : null;
  const localProjectName = () => typeof project === 'function' ? project()?.name : '';
  const bm = {token:null, localProject:null, data:null, loading:null, matches:[], revision:0};
  const timeText = value => value ? new Date(value).toLocaleString('ko-KR') : '기록 없음';

  function messageFrom(error) {
    const detail = error?.detail;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return detail.message;
    return error?.message || '요청을 처리하지 못했습니다.';
  }
  async function sessionToken() {
    if (bm.token) return bm.token;
    const response = await fetch('/api/blackmagician/session');
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(messageFrom(data)), {detail:data.detail});
    bm.token = data.token;
    return bm.token;
  }
  async function request(path, payload) {
    const headers = {'X-DIT-Blackmagician':await sessionToken()};
    if (payload !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch('/api/blackmagician' + path, {
      method:payload === undefined ? 'GET' : 'POST',
      headers,
      body:payload === undefined ? undefined : JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) bm.token = null;
    if (!response.ok) throw Object.assign(new Error(messageFrom(data)), {detail:data.detail});
    return data;
  }
  function apiProject() {
    return `/projects/${encodeURIComponent(bm.localProject)}`;
  }
  function showError(message = '') {
    el('blackmagicianError').textContent = message;
    el('blackmagicianError').hidden = !message;
    el('shootingError').textContent = message;
    el('shootingError').hidden = !message;
  }
  function setLoading(value) {
    bm.loading = value;
    renderBlackmagician();
  }
  function hasConnection() {
    return !!bm.data?.connection;
  }
  function controls() {
    const hasProject = !!localProject();
    el('blackmagicianButton').disabled = !hasProject;
    const code = el('blackmagicianCode')?.value.trim();
    const busy = !!bm.loading;
    el('blackmagicianConnect').disabled = !bm.localProject || !code || busy;
    el('blackmagicianRefresh').disabled = !bm.localProject || busy || !hasConnection();
    el('blackmagicianReview').disabled = !bm.localProject || busy || !hasConnection();
    el('blackmagicianAgent').disabled = !bm.localProject || busy || !bm.data?.review;
    el('blackmagicianDisconnect').disabled = !bm.localProject || busy || !hasConnection();
    for (const button of el('blackmagicianDialog').querySelectorAll('button')) {
      button.setAttribute('aria-busy', busy && button.id.toLowerCase().includes(bm.loading || '') ? 'true' : 'false');
    }
    el('blackmagicianConnect').textContent = bm.loading === 'connect' ? '연결 중' : '연결';
    el('blackmagicianRefresh').textContent = bm.loading === 'refresh' ? '가져오는 중' : '스냅샷 새로고침';
    el('blackmagicianReview').textContent = bm.loading === 'review' ? '검토 중' : '백업 검토';
    el('blackmagicianDisconnect').textContent = bm.loading === 'disconnect' ? '해제 중' : '연결 해제';
  }
  function connectionStatus() {
    const connection = bm.data?.connection;
    const snapshot = bm.data?.snapshot;
    if (!connection) return '<span class="blackmagician-pill muted">연결 없음</span>';
    const status = connection.status || 'connected';
    const cls = status === 'error' || status === 'reauth_required' || connection.last_error ? 'failed' : status === 'stale' || status === 'connecting' ? 'warning' : 'good';
    const ended = snapshot?.camera?.isSessionEnded;
    const stale = status === 'stale' || snapshot?.stale || connection.stale;
    return `<span class="blackmagician-pill ${cls}">${safe(statusText(status))}</span>` +
      (ended ? '<span class="blackmagician-pill warning">종료된 세션</span>' : '') +
      (!ended && snapshot?.access?.sessionActive === false ? '<span class="blackmagician-pill warning">참여 비활성</span>' : '') +
      (stale ? '<span class="blackmagician-pill warning">스냅샷 확인 필요</span>' : '');
  }
  function statusText(value) {
    return {connected:'연결됨',connecting:'연결 중',ready:'연결됨',refreshing:'새로고침 중',stale:'오래된 스냅샷',reauth_required:'재접속 필요',error:'오류',ended:'종료됨'}[value] || value;
  }
  function metadata() {
    const connection = bm.data?.connection;
    if (!connection) return '<p class="muted">초대 코드나 세션 ID를 입력해 연결하세요. 이전에 받은 기록이 있으면 마지막 저장 상태로 표시됩니다.</p>';
    return `<dl>
      <div><dt>방식</dt><dd>${safe({invite:'초대 코드',session:'세션 ID'}[connection.mode] || '기록 없음')}</dd></div>
      <div><dt>프로젝트 ID</dt><dd class="path">${safe(connection.project_id)}</dd></div>
      <div><dt>세션 ID</dt><dd class="path">${safe(connection.session_id)}</dd></div>
      <div><dt>스냅샷</dt><dd>${safe(timeText(connection.snapshot_at || bm.data?.snapshot?.fetched_at))}</dd></div>
      ${connection.last_error ? `<div><dt>오류</dt><dd class="failed">${safe(connection.last_error)}</dd></div>` : ''}
    </dl>`;
  }
  function compactValue(value) {
    if (value == null || value === '') return '기록 없음';
    if (typeof value === 'boolean') return value ? '예' : '아니요';
    return String(value);
  }
  function cameraMarkup(camera) {
    if (!camera) return '<p class="muted">현재 카메라 상태 없음</p>';
    return `<dl>
      <div><dt>카메라</dt><dd>${safe(compactValue(camera.cameraName || camera.cameraId || camera.cameraModel))}</dd></div>
      <div><dt>릴</dt><dd>${safe(compactValue(camera.reel))}</dd></div>
      <div><dt>씬</dt><dd>${safe(compactValue(camera.scene))}</dd></div>
      <div><dt>테이크</dt><dd>${safe(compactValue(camera.take ?? camera.recordCounter))}</dd></div>
      <div><dt>FPS</dt><dd>${safe(compactValue(bm.data?.snapshot?.display_fps))}</dd></div>
      <div><dt>녹화</dt><dd>${safe(camera.isRecording == null ? '기록 없음' : camera.isRecording ? '진행 중' : '대기')}</dd></div>
    </dl>`;
  }
  function scriptMarkup(script) {
    if (!script) return '<p class="muted">현재 Script 상태 없음</p>';
    return `<dl>
      <div><dt>씬 메모</dt><dd>${safe(compactValue(script.sceneInfo))}</dd></div>
      <div><dt>컷</dt><dd>${safe(compactValue(script.cutNumber))}</dd></div>
      <div><dt>스크립트 테이크</dt><dd>${safe(compactValue(script.scriptTake))}</dd></div>
      <div><dt>결과</dt><dd>${safe(compactValue(script.takeResult))}</dd></div>
      <div><dt>기록자</dt><dd>${safe(compactValue(script.scripterName))}</dd></div>
    </dl>`;
  }
  function entryTitle(entry) {
    const data = entry?.data || {};
    return data.clipName || data.clip_name || data.takeId || entry.key || '기록';
  }
  function entryMeta(entry) {
    const data = entry?.data || {};
    return [
      data.scene ? `씬 ${data.scene}` : '',
      data.cutNumber ? `컷 ${data.cutNumber}` : '',
      data.scriptTake ? `스크립트 ${data.scriptTake}` : '',
      data.cameraTake || data.take ? `카메라 ${data.cameraTake || data.take}` : '',
      data.takeResult ? `결과 ${data.takeResult}` : '',
      data.reel ? `릴 ${data.reel}` : '',
    ].filter(Boolean).join(' / ') || '상세 메타데이터 없음';
  }
  function entriesMarkup(entries = []) {
    if (!entries.length) return '<p class="muted">수신된 촬영 기록 없음</p>';
    return `<div class="blackmagician-list">${entries.map(entry => {
      const conflicts = (entry.conflicts || []).map(c => safe(`${c.field}: ${JSON.stringify(c.preferred)} / ${JSON.stringify(c.other)}`)).join(', ');
      const paths = (entry.paths || []).map(safe).join(', ');
      return `<div class="blackmagician-entry"><strong>${safe(entryTitle(entry))}</strong><small>${safe(entryMeta(entry))}</small>` +
        (entry.data?.sceneInfo ? `<small>${safe(entry.data.sceneInfo)}</small>` : '') +
        (paths ? `<small>경로 ${paths}</small>` : '') +
        (conflicts ? `<small class="warning">충돌 ${conflicts}</small>` : '') +
      '</div>';
    }).join('')}</div>`;
  }
  function evidenceText(value) {
    if (!value) return '';
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(evidenceText).filter(Boolean).join(' / ');
    if (typeof value === 'object') {
      return [value.source_relpath, value.file_id, value.completion_artifact].filter(Boolean).join(' / ') || JSON.stringify(value);
    }
    return String(value);
  }
  function reviewMarkup(review) {
    if (!review) return '<p class="muted">백업 검토를 실행하면 클립별 대조 결과가 이곳에 표시됩니다.</p>';
    const labels = {total:'촬영 기록',verified:'검증 근거 일치',missing:'누락',unknown:'판단 불가',ambiguous:'이름 중복',conflict:'기록 충돌',unverified:'검증 미완료',unavailable:'파일 접근 불가',backup_files:'백업 파일',extra_files:'기록 외 파일',unverified_backup_files:'백업 확인 필요'};
    const counts = review.counts ? Object.entries(review.counts).filter(([key]) => ['total','verified','missing','unknown','ambiguous','conflict','unverified','unavailable'].includes(key)).map(([key,value]) =>
      `<span class="blackmagician-pill">${safe(labels[key] || key)} ${safe(value)}</span>`).join('') : '';
    const tone = status => status === 'verified' ? 'good' : ['missing','unverified','unavailable','conflict'].includes(status) ? 'failed' : 'warning';
    const clips = (review.clips || []).map(clip => `<div class="blackmagician-clip"><strong>${safe(clip.clip_name || clip.clipName || '클립')}</strong>` +
      `<small class="${tone(clip.status)}">${safe(labels[clip.status] || '판단 불가')} ${clip.reason ? `/ ${safe(clip.reason)}` : ''}</small>` +
      (clip.evidence ? `<small>${safe(evidenceText(clip.evidence))}</small>` : '') + '</div>').join('');
    const limitations = (review.limitations || []).map(item => `<p class="muted">${safe(item)}</p>`).join('');
    const issues = (review.issues || []).map(item => `<p class="warning">${safe(item.reason)} (${safe(item.run_id)})</p>`).join('');
    return `<p>${safe(review.summary || '검토 완료')}</p><div class="blackmagician-counts">${counts}</div>${issues}${clips ? `<div class="blackmagician-list">${clips}</div>` : ''}${limitations ? `<div class="blackmagician-limitations">${limitations}</div>` : ''}`;
  }
  function matchesMarkup() {
    const box = el('blackmagicianMatches');
    if (!bm.matches.length) { box.hidden = true; box.innerHTML = ''; return; }
    el('blackmagicianProjectIdField').hidden = false;
    box.hidden = false;
    box.innerHTML = '<p class="muted">같은 세션 ID가 여러 프로젝트에 있습니다. 연결할 프로젝트를 선택하세요.</p>' +
      bm.matches.map(match => `<button type="button" data-blackmagician-match="${safe(match.project_id)}" data-session="${safe(match.session_id || '')}"><span class="path">${safe(match.project_id)}</span><small>${safe(match.session_id || '')}</small></button>`).join('');
  }
  function renderBlackmagician() {
    bm.localProject = localProject();
    renderShooting();
    el('blackmagicianButton').disabled = !bm.localProject;
    el('blackmagicianProject').textContent = bm.localProject ? `Data Handler 프로젝트: ${localProjectName() || bm.localProject}` : '프로젝트 선택 필요';
    const content = el('blackmagicianContent');
    if (!bm.localProject) {
      content.innerHTML = '<div class="blackmagician-empty"><h3>프로젝트를 먼저 선택하세요</h3><p class="muted">Blackmagician 세션은 Data Handler 프로젝트에 연결됩니다.</p></div>';
      controls();
      return;
    }
    if (bm.loading === 'load') {
      content.innerHTML = '<div class="blackmagician-empty"><h3>상태를 불러오는 중</h3><p class="muted">저장된 연결 정보를 확인하고 있습니다.</p></div>';
      controls();
      return;
    }
    const snapshot = bm.data?.snapshot;
    content.innerHTML = `<section class="blackmagician-section"><div class="blackmagician-status">${connectionStatus()}</div>${metadata()}</section>` +
      `<div class="blackmagician-grid"><section class="blackmagician-section"><h3>현재 카메라</h3>${cameraMarkup(snapshot?.camera)}</section>` +
      `<section class="blackmagician-section"><h3>현재 Script</h3>${scriptMarkup(snapshot?.script)}</section></div>` +
      `<section class="blackmagician-section"><h3>촬영 기록</h3>${entriesMarkup(snapshot?.entries || [])}</section>` +
      (snapshot?.conflicts?.length ? `<section class="blackmagician-section"><h3>기록 충돌</h3>${snapshot.conflicts.map(item => `<p class="warning">${safe(item.key)}: ${safe(item.differences.map(d => d.field).join(', '))}</p>`).join('')}</section>` : '') +
      `<section class="blackmagician-section"><h3>백업 검토 결과</h3>${reviewMarkup(bm.data?.review)}</section>`;
    matchesMarkup();
    controls();
  }
  async function loadState() {
    if (!localProject()) { renderBlackmagician(); return; }
    const projectId = localProject();
    const rev = ++bm.revision;
    setLoading('load');
    showError();
    try {
      const data = await request(`/projects/${encodeURIComponent(projectId)}`);
      if (rev !== bm.revision || projectId !== localProject()) return;
      bm.data = data;
      bm.matches = [];
    } catch (error) {
      if (rev === bm.revision) showError(messageFrom(error));
    } finally {
      if (rev === bm.revision) setLoading(null);
    }
  }
  async function action(name, fn) {
    const actionProject = localProject();
    if (!actionProject || bm.loading) return;
    bm.localProject = actionProject;
    const rev = ++bm.revision;
    setLoading(name);
    showError();
    try {
      const data = await fn();
      if (rev !== bm.revision || actionProject !== localProject()) return;
      bm.data = data;
      bm.matches = [];
      if (name === 'connect') {
        el('blackmagicianCode').value = '';
        el('blackmagicianDialog').close();
        document.dispatchEvent(new CustomEvent('dit-open-shooting'));
      }
    } catch (error) {
      if (rev !== bm.revision || actionProject !== localProject()) return;
      if (error.detail?.matches) bm.matches = error.detail.matches;
      // A successful join can precede a failed initial read; expose Refresh rather
      // than making the operator consume a second invitation.
      if (!error.detail?.matches?.length) {
        const latest = await request(`/projects/${encodeURIComponent(actionProject)}`).catch(() => null);
        if (rev !== bm.revision || actionProject !== localProject()) return;
        if (latest) bm.data = latest;
      }
      showError(messageFrom(error));
      matchesMarkup();
    } finally {
      if (rev === bm.revision) setLoading(null);
    }
  }
  function selectedBlackmagicianProjectId() {
    return el('blackmagicianProjectId').value.trim() || null;
  }
  const liveActive = () => document.body.dataset.mode === 'blackmagician';
  function replaceMarkup(id, markup) {
    const target = el(id);
    if (target.dataset.markup !== markup) {
      target.innerHTML = markup;
      target.dataset.markup = markup;
    }
  }
  function renderShooting() {
    const live = bm.data?.live || {};
    const snapshot = bm.data?.snapshot;
    const options = '<option value="">프로젝트 선택</option>' + (state.projects || []).map(p => `<option value="${safe(p.id)}">${safe(p.name)}</option>`).join('');
    replaceMarkup('shootingProjectSelect', options);
    el('shootingProjectSelect').value = localProject() || '';
    el('shootingProject').textContent = localProjectName() ? `${localProjectName()} / ${bm.data?.connection?.session_id || '연결된 세션 없음'}` : '왼쪽에서 프로젝트를 선택하세요';
    const labels = {live:'촬영 정보 실시간 수신 중',polling:'촬영 정보 3초마다 동기화',connecting:'촬영 연결 준비 중',
      reconnecting:'연결 중단, 자동 재연결 중',reauth_required:'접속 권한 확인 필요, 다시 연결하세요',
      paused:'수신 일시정지, 마지막 저장 기록',ended:'촬영 세션 종료, 후속 메모 동기화',disconnected:'연결 해제됨'};
    el('shootingStatus').textContent = (bm.loading === 'load' ? '연결 정보 불러오는 중' : labels[live.status] || '세션을 연결하면 촬영 정보를 자동으로 받습니다.') +
      (live.last_observed_at ? ` / 기록 확인 ${timeText(live.last_observed_at)}` : '');
    el('shootingSettings').textContent = hasConnection() ? '연결 상세' : '세션 연결';
    el('shootingSettings').disabled = !localProject();
    el('shootingPause').disabled = !hasConnection() || !!bm.loading;
    el('shootingPause').textContent = live.enabled ? '수신 일시정지' : '수신 재개';
    replaceMarkup('shootingOverview', snapshot ?
      `<section class="shooting-section"><h2>현재 카메라</h2>${cameraMarkup(snapshot.camera)}</section><section class="shooting-section"><h2>현재 Script</h2>${scriptMarkup(snapshot.script)}</section>` :
      '<section class="shooting-section"><h2>촬영 세션을 연결하세요</h2><p class="muted">초대 코드로 연결하면 카메라 상태와 촬영 기록을 계속 받습니다. 세션 ID 연결은 3초마다 확인합니다.</p></section>');
    const questions = bm.data?.questions || [];
    const notes = bm.data?.confirmations || [];
    const markup = questions.filter(q => q.status !== 'answered').map(q =>
      `<div class="shooting-question"><p>${safe(q.question)}</p>` + (q.kind === 'missing' ?
        `<form data-question="${safe(q.id)}" data-revision="${safe(q.entry_revision)}"><label for="note-${safe(q.id)}">확인 내용</label><input id="note-${safe(q.id)}" name="value" maxlength="1000" required autocomplete="off"><button type="submit">확인 내용 저장</button></form>` : '<p class="warning">연결 상세에서 충돌 필드를 확인하세요.</p>') + '</div>').join('') +
      notes.map(n => `<div class="shooting-question"><p>${safe(n.entry_key.split('/').pop())} / ${safe({scene:'씬',takeResult:'테이크 결과'}[n.field] || n.field)}: ${safe(n.value)}</p><small class="${n.status === 'conflict' ? 'warning' : 'muted'}">${safe({local:'로컬 확인 메모 저장됨, 원격 반영 대기',reflected:'원격 기록에서 같은 값 확인됨',conflict:'원격 기록이 바뀌었습니다. 다시 확인하세요.',obsolete:'원격 기록이 삭제되었습니다.'}[n.status] || n.status)}</small></div>`).join('');
    // Background updates must preserve an operator's partially typed reply.
    if (!el('shootingQuestions').contains(document.activeElement)) {
      replaceMarkup('shootingQuestions', markup || '<p class="muted">현재 확인할 항목이 없습니다. 새 기록이 오면 다시 확인합니다.</p>');
    }
    replaceMarkup('shootingEntries', `<p class="muted">총 ${snapshot?.entries?.length || 0}개 / 최근 20개 표시</p>` + entriesMarkup([...(snapshot?.entries || [])].reverse().slice(0,20)));
    if (live.last_error) showError(live.last_error);
  }
  el('shootingSettings').onclick = () => el('blackmagicianButton').click();
  el('shootingProjectSelect').onchange = event => {
    const button = [...el('projects').querySelectorAll('[data-project]')].find(b => b.dataset.project === event.target.value);
    button?.click();
  };
  function subView(value) {
    el('shootingPanel').dataset.view = value;
    el('shootingShowDetails').setAttribute('aria-pressed', value === 'details');
    el('shootingShowAgent').setAttribute('aria-pressed', value === 'agent');
  }
  el('shootingShowDetails').onclick = () => subView('details');
  el('shootingShowAgent').onclick = () => subView('agent');
  subView('details');
  el('shootingPause').onclick = () => action('live', () => request(apiProject() + '/live', {enabled:!bm.data?.live?.enabled}));
  el('shootingQuestions').addEventListener('submit', async event => {
    const form = event.target.closest('form[data-question]');
    if (!form) return;
    event.preventDefault();
    const value = new FormData(form).get('value').trim();
    if (!value) return;
    const button = form.querySelector('button'); button.disabled = true;
    await action('note', () => request(apiProject() + '/questions/' + form.dataset.question, {value,entry_revision:form.dataset.revision}));
    button.disabled = false;
    if (bm.data?.questions?.find(q => q.id === form.dataset.question)?.status === 'answered') {
      document.activeElement?.blur(); renderShooting();
    }
  });
  document.addEventListener('dit-mode-changed', event => {
    if (event.detail.mode === 'blackmagician') { renderShooting(); if (!bm.loading) loadState(); }
  });
  let checking = false;
  setInterval(async () => {
    if (checking || bm.loading || document.hidden || !localProject() || (!liveActive() && !el('blackmagicianDialog').open)) return;
    const pid = localProject(), rev = bm.revision;
    checking = true;
    try {
      const data = await request(`/projects/${encodeURIComponent(pid)}`);
      if (pid !== localProject() || rev !== bm.revision) return;
      const previousError = bm.data?.live?.last_error;
      bm.data = data;
      if (previousError && el('shootingError').textContent === previousError && !data.live?.last_error) showError();
      if (el('blackmagicianDialog').open) renderBlackmagician(); else renderShooting();
    } catch (error) { if (pid === localProject() && rev === bm.revision) showError(messageFrom(error)); }
    finally { checking = false; }
  }, 1000);
  function openAgentReview() {
    if (!bm.localProject) return;
    el('blackmagicianDialog').close();
    document.dispatchEvent(new CustomEvent('dit-agent-review', {detail:{projectId:bm.localProject}}));
  }
  el('blackmagicianButton').onclick = () => {
    bm.localProject = localProject();
    el('blackmagicianDialog').showModal();
    renderBlackmagician();
    loadState();
  };
  el('blackmagicianMode').onchange = () => {
    bm.matches = [];
    matchesMarkup();
    el('blackmagicianProjectIdField').hidden = el('blackmagicianMode').value === 'invite';
  };
  el('blackmagicianCode').oninput = controls;
  el('blackmagicianProjectId').oninput = controls;
  el('blackmagicianConnectForm').onsubmit = event => {
    event.preventDefault();
    action('connect', () => request(apiProject() + '/connect', {
      mode:el('blackmagicianMode').value,
      code:el('blackmagicianCode').value.trim(),
      project_id:selectedBlackmagicianProjectId(),
    }));
  };
  el('blackmagicianRefresh').onclick = () => action('refresh', () => request(apiProject() + '/refresh', {}));
  el('blackmagicianReview').onclick = () => action('review', () => request(apiProject() + '/review', {}));
  el('blackmagicianDisconnect').onclick = () => action('disconnect', () => request(apiProject() + '/disconnect', {}));
  el('blackmagicianAgent').onclick = openAgentReview;
  el('blackmagicianMatches').onclick = event => {
    const button = event.target.closest('button[data-blackmagician-match]');
    if (!button) return;
    el('blackmagicianProjectId').value = button.dataset.blackmagicianMatch;
    bm.matches = [];
    matchesMarkup();
    controls();
  };
  document.addEventListener('dit-project-changed', () => {
    bm.revision++;
    bm.loading = null;
    showError();
    el('blackmagicianCode').value = '';
    el('blackmagicianProjectId').value = '';
    bm.localProject = localProject();
    bm.data = null;
    bm.matches = [];
    if (el('blackmagicianDialog').open || liveActive()) loadState();
    else renderBlackmagician();
  });
  el('blackmagicianProjectIdField').hidden = true;
  renderBlackmagician();
})();
