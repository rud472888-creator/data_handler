(() => {
  const el = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const chat = {token:null, connected:false, id:localStorage.getItem('dit-agent-conversation'),
    conversation:null, conversations:[], projects:[], sending:false, pending:false, signature:'', revision:0, retry:null};
  const statusText = {pending:'실행 확인 대기', expired:'유효시간 만료', claimed:'실행 접수됨',
    started:'복제 시작됨', completed:'작업 완료', needs_review:'확인 필요'};
  const active = () => ['agent','blackmagician'].includes(document.body.dataset.mode);
  const shooting = () => document.body.dataset.mode === 'blackmagician';
  function notice(message = '') {
    el('agentError').textContent = message;
    el('agentNotice').hidden = !message;
  }
  function showHealth(health) {
    chat.connected = health.connected;
    const model = !health.inference_connected ? '로컬 AI 연결 안 됨' : health.model_load_error ? '모델 준비 실패 · 다시 연결해 주세요' :
      health.model_loading ? '로컬 모델 불러오는 중' : health.model_loaded ? '로컬 모델 준비됨' : '로컬 모델 대기 중';
    el('agentConnection').textContent = model + ' / ' +
      (health.telegram_connected ? 'Telegram 연결 확인됨' : health.telegram_paired ? 'Telegram 연결 확인 대기' : 'Telegram 미등록');
    controls();
  }
  function controls() {
    el('agentSend').disabled = !chat.connected || chat.pending || chat.sending || !el('agentInput').value.trim();
    el('agentNew').disabled = chat.sending;
    el('agentHistory').disabled = chat.sending;
    el('agentSend').textContent = chat.sending ? '접수 중' : '전송';
    el('agentProject').disabled = shooting() || !!chat.conversation?.turns.length || chat.sending;
    el('agentSend').disabled ||= shooting() && (!state.project || chat.conversation && chat.conversation.project_id !== state.project);
    el('agentSendHint').textContent = chat.pending ? '요청을 처리하고 있습니다. 앱을 닫아도 기록은 유지됩니다.' : shooting() ? '답변에는 확인한 촬영 기록의 시각이 남습니다.' : '경로를 확인한 뒤 복제를 시작합니다.';
  }
  async function request(path, payload) {
    if (!chat.token) {
      const session = await fetch('/api/agent/session');
      if (!session.ok) throw new Error('앱 연결을 초기화하지 못했습니다.');
      chat.token = (await session.json()).token;
    }
    const response = await fetch('/api/agent' + path, {method:payload === undefined ? 'GET' : 'POST',
      headers:{'Content-Type':'application/json','X-DIT-Agent':chat.token},
      body:payload === undefined ? undefined : JSON.stringify(payload)});
    const data = await response.json();
    if (response.status === 401) chat.token = null;
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.');
    return data;
  }
  function historyOptions() {
    el('agentHistory').innerHTML = '<option value="">새 대화</option>' + chat.conversations.map(c =>
      `<option value="${safe(c.id)}">${safe(c.title)}</option>`).join('');
    el('agentHistory').value = chat.id || '';
  }
  function projectOptions() {
    const selected = chat.conversation?.project_id ?? el('agentProject').value ?? '';
    el('agentProject').innerHTML = '<option value="">대화에서 지정</option>' + chat.projects.map(p =>
      `<option value="${safe(p.id)}">${safe(p.name)}</option>`).join('');
    el('agentProject').value = selected;
  }
  function welcome() {
    if (shooting()) return '<div class="agent-welcome"><h2>촬영 기록을 함께 확인합니다</h2><p>현재 카메라와 테이크, 씬 메모를 확인하고 필요한 정보를 물어보세요. 새 촬영 기록은 왼쪽에 자동으로 반영됩니다.</p><div class="agent-suggestions"><button data-prompt="/shooting">현재 촬영 정보</button><button data-prompt="최근 테이크의 씬과 결과를 알려줘">최근 테이크 확인</button><button data-prompt="/script-check">빠진 기록 확인</button></div></div>';
    return '<div class="agent-welcome"><h2>어떤 작업을 준비할까요?</h2>' +
      '<p>프로젝트를 선택하고 원본 카드와 복제 위치를 알려 주세요.<br>경로 확인부터 복제, 검수와 PDF까지 이 대화에서 이어갑니다.</p>' +
      '<div class="agent-suggestions"><button data-prompt="카드를 백업하고 싶어. 필요한 정보를 알려줘.">카드 복제 준비</button>' +
      '<button data-prompt="현재 작업 상태 알려줘">작업 상태 확인</button></div></div>';
  }
  function planMarkup(plan) {
    const available = !plan.status || plan.status === 'pending';
    return `<section class="chat-plan" aria-label="실행 전 경로 확인"><h3>실행 전 경로 확인</h3><dl>` +
      `<div><dt>프로젝트</dt><dd>${safe(plan.project_name)} / ${safe(plan.roll)}</dd></div>` +
      `<div><dt>원본</dt><dd class="path">${safe(plan.source_path)}</dd></div>` +
      `<div><dt>복제 위치</dt><dd>${(plan.destinations || []).map(p => `<p class="path">${safe(p)}</p>`).join('')}</dd></div>` +
      `<div><dt>촬영일 / 카메라</dt><dd>${safe(plan.shoot_date)} / ${safe(plan.camera_unit)}</dd></div></dl>` +
      `<div class="chat-plan-actions"><button class="primary" data-approve="${safe(plan.id)}" ${!available || chat.pending ? 'disabled' : ''}>${available ? '이 경로로 복제 시작' : safe(statusText[plan.status] || '확인 필요')}</button>` +
      `<button data-edit-plan="${safe(plan.id)}">${available ? '경로 수정' : '새 계획 준비'}</button><span class="muted">${available ? '확인 후 검수와 보고까지 자동 진행합니다.' : safe(statusText[plan.status] || '')}</span></div></section>`;
  }
  function executionMarkup(result) {
    const run = result.execution;
    if (!run) return result.run_id ? `<section class="chat-execution"><h3>${safe(statusText[result.status] || '작업 접수')}</h3><p class="path">${safe(result.run_id)}</p><p class="muted">완료 기록이 도착하면 결과를 표시합니다.</p></section>` : '';
    const labels = {waiting:'작업 접수됨',copying:'복제 작업 진행 중',reporting:'복제 검증 완료, 검수 결과 대기',
      reported:'작업 완료',verified:'복제 검증 완료',review:'결과 확인 필요',failed:'작업 실패'};
    const reports = (run.artifacts || []).filter(a => a.path?.toLowerCase().endsWith('.pdf'));
    return `<section class="chat-execution"><h3>${safe(labels[run.phase] || '기록 확인 필요')}</h3>` +
      `<p>${safe(run.roll)} / 체크섬 ${run.verified ? '검증 완료' : '결과 대기'}</p>` +
      (run.error ? `<p class="failed">${safe(run.error)}</p>` : '') +
      reports.map(a => a.available && a.url ? `<a href="${safe(a.url)}" target="_blank" rel="noopener">${safe(a.name || 'PDF 리포트')} 열기</a>` : `<p class="warning">${safe(a.name || 'PDF')} 파일을 사용할 수 없습니다.</p>`).join('') +
      `<p class="path">${safe(run.run_id)}</p></section>`;
  }
  function render(force = false) {
    const turns = chat.conversation?.turns || [];
    chat.pending = turns.some(t => t.status !== 'done');
    const signature = JSON.stringify(turns);
    if (!force && signature === chat.signature) { controls(); return; }
    chat.signature = signature;
    const log = el('agentLog');
    const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 100;
    log.innerHTML = turns.length ? turns.map(turn => {
      const result = turn.result || {};
      const user = turn.text.startsWith('/approve ') ? '확인한 경로로 복제를 시작해줘.' : turn.text;
      return `<article class="chat-turn"><div class="chat-user"><p class="chat-speaker">나</p><p class="chat-text">${safe(user)}</p></div>` +
        '<div class="chat-assistant"><p class="chat-speaker">Data Handler</p>' +
        (turn.status !== 'done' ? '<p class="chat-waiting" role="status">로컬 에이전트가 요청을 처리하고 있습니다…</p>' :
          (result.plan ? '<p class="chat-text">복제 계획을 준비했습니다. 원본과 최종 복제 위치를 확인해 주세요.</p>' :
            `<p class="chat-text ${result.error ? 'failed' : ''}">${safe(result.text || '처리를 마쳤습니다.')}</p>`) +
          (result.plan ? planMarkup(result.plan) : '') + executionMarkup(result) +
          (result.shooting_evidence ? `<p class="muted">촬영 근거: ${safe(result.shooting_evidence.session_id || '연결 없음')} / ${safe(result.shooting_evidence.observed_at ? new Date(result.shooting_evidence.observed_at).toLocaleString('ko-KR') : '수신 기록 없음')} / ${result.shooting_evidence.from_cache ? '마지막 저장 기록' : '수신 기록'} ${safe(result.shooting_evidence.revision || '')}</p>` : '') +
          (result.error ? `<button data-retry-turn="${safe(turn.request_id)}">요청 수정</button>` : '')) +
        '</div></article>';
    }).join('') : welcome();
    if (force || nearBottom) log.scrollTop = log.scrollHeight;
    controls();
  }
  async function loadConversation(id, force = false) {
    const revision = ++chat.revision;
    if (!id) {
      chat.conversation = null; chat.pending = false; render(true); controls(); return;
    }
    const data = await request('/conversations/' + id);
    if (revision !== chat.revision || chat.id !== id) return;
    chat.conversation = data;
    projectOptions(); render(force);
  }
  async function connect() {
    el('agentConnection').textContent = '로컬 에이전트 연결 확인 중';
    try {
      const [health, history, projects] = await Promise.all([request('/state'),request('/conversations'),api('/api/projects')]);
      chat.connected = health.connected; chat.conversations = history.conversations; chat.projects = projects.projects;
      if (chat.id && !chat.conversations.some(c => c.id === chat.id)) chat.id = null;
      historyOptions(); projectOptions();
      showHealth(health);
      if (health.inference_connected && !health.model_loaded) await request('/warmup', {});
      notice(); await loadConversation(chat.id, true);
    } catch (error) {
      chat.connected = false;
      el('agentConnection').textContent = '로컬 에이전트 연결 안 됨';
      notice(error.message); render();
    } finally { controls(); }
  }
  async function send(text, requestId) {
    if (!text.trim() || chat.sending || chat.pending) return;
    chat.sending = true; controls(); notice();
    let accepted = false;
    const targetProject = el('agentProject').value || null;
    const fromShooting = shooting();
    const stillSelected = () => !fromShooting || shooting() && state.project === targetProject;
    let conversationId = chat.id;
    try {
      if (!conversationId) {
        const created = await request('/conversations', {project_id:targetProject});
        conversationId = created.id;
        if (stillSelected()) {
          chat.id = created.id; localStorage.setItem('dit-agent-conversation', chat.id);
        }
      }
      const key = requestId || crypto.randomUUID();
      chat.retry = {text, key};
      await request('/conversations/' + conversationId + '/messages', {text,request_id:'chat:' + key});
      if (!stillSelected()) return;
      accepted = true; chat.pending = true;
      chat.retry = null; el('agentInput').value = '';
      chat.conversations = (await request('/conversations')).conversations;
      historyOptions(); await loadConversation(chat.id, true);
    } catch (error) { notice(error.message + (accepted ? ' 요청은 접수됐습니다. 다시 연결하면 결과를 확인할 수 있습니다.' : ' 입력한 내용은 남겨 두었습니다.')); }
    finally { chat.sending = false; controls(); }
  }
  function mode(value) {
    if (!['workspace','agent','blackmagician'].includes(value)) value = 'workspace';
    document.body.dataset.mode = value;
    const isShooting = value === 'blackmagician';
    el('shootingPanel').hidden = !isShooting;
    if (isShooting) el('shootingAgent').append(el('agentPanel'));
    else document.querySelector('main').prepend(el('agentPanel'));
    el('agentPanel').hidden = !active();
    el('blackmagicianLiveMode').setAttribute('aria-pressed', isShooting);
    el('workspaceMode').setAttribute('aria-pressed', value === 'workspace');
    el('agentMode').setAttribute('aria-pressed', value === 'agent');
    localStorage.setItem('dit-mode', value);
    el('agentContextHint').textContent = isShooting ? '연결된 촬영 기록을 근거로 답합니다.' : '원본과 백업 경로를 1개 이상 알려 주세요.';
    el('agentInput').placeholder = isShooting ? '예: 최근 테이크의 씬과 결과를 알려줘' : '예: 오늘 촬영 카드를 지정한 경로에 백업해줘';
    document.dispatchEvent(new CustomEvent('dit-mode-changed', {detail:{mode:value}}));
    if (isShooting) return connect().then(() => selectShootingProject());
    if (value === 'agent') return connect();
    else refresh();
  }
  el('workspaceMode').onclick = () => mode('workspace');
  el('agentMode').onclick = () => mode('agent');
  el('blackmagicianLiveMode').onclick = () => mode('blackmagician');
  document.addEventListener('dit-open-shooting', () => mode('blackmagician'));
  function selectShootingProject() {
    if (!shooting()) return;
    if (chat.shootingProject !== state.project || chat.conversation && chat.conversation.project_id !== state.project) {
      chat.revision++; chat.id = null; chat.conversation = null; chat.retry = null;
      localStorage.removeItem('dit-agent-conversation');
      el('agentInput').value = '';
      historyOptions();
    }
    chat.shootingProject = state.project;
    if (!chat.projects.some(p => p.id === state.project) && state.project) chat.projects = state.projects;
    projectOptions(); el('agentProject').value = state.project || ''; render(true);
  }
  document.addEventListener('dit-project-changed', selectShootingProject);
  el('agentReconnect').onclick = connect;
  el('agentNew').onclick = () => {
    chat.revision++; chat.id = null; chat.conversation = null; chat.retry = null;
    localStorage.removeItem('dit-agent-conversation'); el('agentInput').value = '';
    historyOptions(); projectOptions(); render(true); el('agentInput').focus();
    if (shooting()) selectShootingProject();
  };
  document.addEventListener('dit-agent-review', async event => {
    const projectId = event.detail?.projectId;
    if (!projectId || chat.sending) return;
    el('agentNew').click();
    await mode('agent');
    if (chat.id) return;
    if (!chat.projects.some(p => p.id === projectId)) {
      // Keep the selected project available even when the local service is offline.
      const projects = await api('/api/projects').catch(() => ({projects:[]}));
      chat.projects = projects.projects;
      projectOptions();
    }
    el('agentProject').value = projectId;
    el('agentInput').value = '/backup-review';
    controls(); el('agentInput').focus();
  });
  el('agentHistory').onchange = async e => {
    chat.id = e.target.value || null; chat.retry = null;
    if (chat.id) localStorage.setItem('dit-agent-conversation',chat.id);
    else localStorage.removeItem('dit-agent-conversation');
    try { await loadConversation(chat.id, true); } catch (error) { notice(error.message); }
    if (shooting()) selectShootingProject();
  };
  el('agentForm').onsubmit = e => {
    e.preventDefault();
    const text = el('agentInput').value.trim();
    send(text,chat.retry?.text === text ? chat.retry.key : undefined);
  };
  el('agentInput').oninput = controls;
  el('agentInput').onkeydown = e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault(); if (!el('agentSend').disabled) el('agentForm').requestSubmit();
    }
  };
  el('agentLog').onclick = e => {
    const button = e.target.closest('button'); if (!button) return;
    if (button.dataset.prompt) { el('agentInput').value = button.dataset.prompt; controls(); el('agentInput').focus(); }
    if (button.dataset.approve) send('/approve ' + button.dataset.approve);
    if (button.dataset.editPlan) {
      const plan = chat.conversation?.turns.map(t => t.result?.plan).find(p => p?.id === button.dataset.editPlan);
      if (plan) {
        el('agentInput').value = `원본 ${plan.source_path}, 복제 위치 ${plan.replica_paths.join(' 및 ')}로 계획을 수정해줘.`;
        el('agentInput').focus(); controls();
      }
    }
    if (button.dataset.retryTurn) {
      const turn = chat.conversation?.turns.find(t => t.request_id === button.dataset.retryTurn);
      if (turn) { el('agentInput').value = turn.text; el('agentInput').focus(); controls(); }
    }
  };
  let polling = false;
  let checkingHealth = false;
  setInterval(async () => {
    if (!active() || document.hidden || checkingHealth) return;
    checkingHealth = true;
    try { showHealth(await request('/state')); }
    catch (_) {
      chat.connected = false;
      el('agentConnection').textContent = '로컬 에이전트 연결 안 됨';
      controls();
    } finally { checkingHealth = false; }
  }, 15000);
  setInterval(async () => {
    if (!active() || document.hidden || !chat.id || polling || chat.sending) return;
    polling = true;
    try { await loadConversation(chat.id); } catch (error) { notice(error.message); }
    finally { polling = false; }
  }, 2500);
  render(true);
  if (['agent','blackmagician'].includes(localStorage.getItem('dit-mode'))) mode(localStorage.getItem('dit-mode'));
})();
