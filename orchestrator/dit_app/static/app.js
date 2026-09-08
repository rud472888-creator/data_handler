const $ = id => document.getElementById(id);
const state = {projects: [], cards: [], project: localStorage.getItem('dit-project'), day: '', selected: null, tab: 'library', search: '', review: null, loading: false};
const labels = {waiting: '시작 대기', copying: '복사·체크섬 검증 중', verified: '검증 완료', reporting: 'PDF 생성 중', reported: '작업 완료', review: '확인 필요', failed: '작업 실패'};
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const project = () => state.projects.find(p => p.id === state.project);
const tone = phase => ['reported','verified'].includes(phase) ? 'good' : phase === 'failed' ? 'failed' : phase === 'review' ? 'warning' : 'active';
const badge = card => `<span class="status ${tone(card.phase)}">${escape(labels[card.phase] || '상태 확인 필요')}</span>`;
const dateTime = value => value ? new Date(value).toLocaleString('ko-KR') : '기록 없음';
const pickerFields = new Map();
window.DataHandlerPathChooser = {resolve(result) {
  const field = pickerFields.get(result.requestId);
  if (field && result.path) field.value = result.path;
  pickerFields.delete(result.requestId);
}};
if (window.webkit?.messageHandlers?.pathChooser) {
  for (const name of ['source_path','replica1','replica2']) {
    const field = $('importForm').elements[name];
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = '폴더 선택';
    button.onclick = () => { const requestId = crypto.randomUUID(); pickerFields.set(requestId,field); window.webkit.messageHandlers.pathChooser.postMessage({requestId,currentPath:field.value}); };
    field.parentElement.append(button);
  }
}

async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result));
  return result;
}
function error(id, message) { $(id).textContent = message || ''; $(id).hidden = !message; }
function empty(title, body, button = '') { return `<div class="empty"><h2>${title}</h2><p>${body}</p>${button}</div>`; }
function visibleCards() { return state.cards.filter(c => (!state.day || c.shoot_date === state.day) && `${c.roll} ${c.camera_unit} ${c.source_path}`.toLowerCase().includes(state.search.toLowerCase())); }
function pdfs(card) { return card.artifacts.filter(a => a.kind === 'pdf' || /\.pdf$/i.test(a.path)); }
function artifactLink(a) {
  const replica = a.name.match(/path(\d+)/);
  const label = /checksum/i.test(a.name) ? '체크섬 검증 PDF' : replica ? `복제본 ${replica[1]} 검수 PDF` : a.name;
  if (!a.available || !a.url) return `<span class="warning">${escape(label)}<small>${a.availability === 'destination_offline' ? '저장 볼륨 연결 필요' : '파일을 찾을 수 없음'}</small></span>`;
  return `<a href="${escape(a.url)}" target="_blank" rel="noopener">${escape(label)} 열기 ↗</a>`;
}
function render() {
  $('projects').innerHTML = state.projects.length ? state.projects.map(p => `<button data-project="${escape(p.id)}" aria-current="${p.id === state.project}">${escape(p.name)}</button>`).join('') : '<p class="muted">등록된 프로젝트 없음</p>';
  const days = [...new Set(state.cards.map(c => c.shoot_date))].sort().reverse();
  $('days').innerHTML = days.length ? `<button data-day="" aria-current="${!state.day}">전체 촬영일</button>${days.map(d => `<button data-day="${escape(d)}" aria-current="${d === state.day}">${escape(d)} <span class="muted">${state.cards.filter(c => c.shoot_date === d).length}</span></button>`).join('')}` : '';
  $('projectTitle').textContent = project()?.name || '프로젝트 라이브러리';
  $('projectSubtitle').textContent = project() ? (state.day || '전체 촬영일') + ' / 카드와 검증 기록' : '프로젝트를 만들고 촬영 카드를 관리하세요.';
  $('importCard').disabled = !project();
  $('removeProject').disabled = !project();
  $('libraryTab').setAttribute('aria-pressed', state.tab === 'library');
  $('reportsTab').setAttribute('aria-pressed', state.tab === 'reports');
  const cards = visibleCards();
  if (state.loading) $('content').innerHTML = empty('기록을 불러오는 중', '프로젝트의 카드와 완료 기록을 확인하고 있습니다.');
  else if (!project()) $('content').innerHTML = empty('촬영 프로젝트부터 시작하세요', '카드, 복사본과 리포트를 하나의 프로젝트에 모읍니다. 디스크는 카드를 가져올 때 연결하면 됩니다.', '<button class="primary" data-new-project>새 프로젝트</button>');
  else if (!state.cards.length) $('content').innerHTML = empty('첫 번째 카드를 가져오세요', '원본 카드와 두 복제 위치를 선택하세요. 복사·검증 결과와 PDF가 이곳에 기록됩니다.', '<button class="primary" data-import>카드 가져오기</button>');
  else if (!cards.length) $('content').innerHTML = empty('일치하는 카드가 없습니다', '검색어나 촬영일 선택을 변경하세요.');
  else if (state.tab === 'reports') {
    const rows = cards.flatMap(c => pdfs(c).map(a => `<div class="report-row"><div><strong>${escape(c.roll)}</strong><small>${escape(c.shoot_date)} / 카메라 ${escape(c.camera_unit)}</small></div>${artifactLink(a)}</div>`));
    $('content').innerHTML = rows.join('') || empty('PDF가 아직 없습니다', '완료 기록에 리포트가 등록되면 이곳에서 열 수 있습니다. 생성 중이거나 실패한 작업은 카드 상세에서 확인하세요.');
  } else $('content').innerHTML = `<table><thead><tr><th>카드 / 촬영일</th><th>카메라</th><th>작업 상태</th><th>체크섬</th></tr></thead><tbody>${cards.map(c => `<tr class="${c.run_id === state.selected ? 'selected' : ''}"><td data-label="카드"><button data-card="${escape(c.run_id)}" aria-label="${escape(c.roll)} 카드 상세">${escape(c.roll)}</button><small>${escape(c.shoot_date)}</small></td><td data-label="카메라">${escape(c.camera_unit)}</td><td data-label="작업 상태">${badge(c)}</td><td data-label="체크섬"><span class="${c.verified ? 'good' : 'muted'}">${c.verified ? '검증 완료' : '미확인'}</span></td></tr>`).join('')}</tbody></table>`;
  $('librarySummary').textContent = `${cards.length}개 카드 / ${cards.filter(c => c.verified).length}개 검증 완료`;
  renderInspector();
  const active = state.cards.filter(c => ['waiting','copying','reporting','review','failed'].includes(c.phase));
  $('queue').innerHTML = active.length ? active.map(c => `<div class="queue-row"><button data-card="${escape(c.run_id)}">${escape(c.roll)}</button>${badge(c)}<span class="muted">마지막 작업 기록 ${escape(dateTime(c.updated_at))}</span></div>`).join('') : '<p>진행 중이거나 확인이 필요한 작업이 없습니다.</p>';
}
function renderInspector() {
  const c = state.cards.find(c => c.run_id === state.selected);
  if (!c) { $('inspector').innerHTML = '<h2>카드 상세</h2><p class="muted">카드를 선택하면 원본, 복제 위치와 리포트를 확인할 수 있습니다.</p>'; return; }
  $('inspector').innerHTML = `<h2>${escape(c.roll)}</h2><p>${badge(c)}</p><p class="muted">${escape(c.shoot_date)} / 카메라 ${escape(c.camera_unit)}</p><section><h3>원본</h3><p class="path">${escape(c.source_path)}</p><p class="muted">${c.file_count == null ? '파일 수 확인 대기' : `${escape(c.file_count)}개 파일`}</p></section><section><h3>복제본과 체크섬</h3>${c.destinations.map((d,i) => `<div class="destination"><p>복제본 ${i+1} <span class="${c.verified ? 'good' : 'muted'}">${c.verified ? '검증 완료' : '검증 결과 대기'}</span></p><p class="path">${escape(d)}</p></div>`).join('') || '<p class="muted">복제 경로 기록 대기</p>'}</section><section><h3>PDF 리포트</h3>${pdfs(c).map(a => `<p>${artifactLink(a)}</p>`).join('') || '<p class="muted">생성된 PDF 없음</p>'}</section>${c.error ? `<section><h3>확인할 내용</h3><p class="failed">${escape(c.error)}</p></section>` : ''}${c.failed_files.length ? `<section><h3>실패 파일</h3>${c.failed_files.map(f => `<p class="path">${escape(f)}</p>`).join('')}</section>` : ''}<section><h3>마지막 작업 기록</h3><p>${escape(dateTime(c.updated_at))}</p><p class="muted">이 시각 이후의 진행률은 확인되지 않았습니다. 검증 결과는 완료 기록을 기준으로 표시합니다.</p><p class="path">${escape(c.run_id)}</p></section>`;
}
let revision = 0;
async function refresh() {
  const current = ++revision;
  try {
    const data = await api('/api/projects');
    if (current !== revision) return;
    state.projects = data.projects;
    if (!project()) state.project = state.projects[0]?.id || null;
    const id = state.project;
    const dataCards = id ? await api(`/api/library/projects/${encodeURIComponent(id)}/cards`) : {cards:[]};
    if (current !== revision || id !== state.project) return;
    state.cards = dataCards.cards.reverse();
    if (!state.cards.some(c => c.run_id === state.selected)) state.selected = state.cards[0]?.run_id || null;
    state.loading = false;
    error('error', '');
    $('syncTime').textContent = `기록 확인 ${new Date().toLocaleTimeString('ko-KR')}`;
    render();
  } catch (e) { if (current === revision) { state.loading = false; error('error', `기록을 불러오지 못했습니다. ${e.message} 새로고침으로 다시 시도하세요.`); } }
}
async function volumes() {
  try {
    const data = await api('/api/disks');
    $('volumes').innerHTML = data.disks.length ? data.disks.map(d => `<div class="volume">${escape(d.name || d.label || d.path)}<small>${escape(d.path || d.mount_point || '')}</small></div>`).join('') : '<p class="muted">연결된 외장 볼륨 없음</p>';
  } catch (e) { $('volumes').textContent = `볼륨 조회 실패: ${e.message}`; }
}
function openProject() { $('projectForm').reset(); error('projectError',''); $('projectDialog').showModal(); }
async function openImport() {
  if (!project()) return;
  $('importForm').reset();
  const now = new Date();
  $('importForm').elements.shoot_date.value = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  $('importProject').textContent = `프로젝트: ${project().name}`;
  back(); error('importError',''); $('importDialog').showModal();
  const results = await Promise.allSettled([api('/api/sources'),api('/api/destinations')]);
  ['sourceChoices','destinationChoices'].forEach((id,i) => { const result = results[i]; $(id).innerHTML = result.status === 'fulfilled' ? (result.value.sources || result.value.destinations || []).map(p => `<option value="${escape(p.path)}"></option>`).join('') : ''; });
}
function back() { state.review = null; $('importFields').hidden = false; $('importReview').hidden = true; $('importBack').hidden = true; $('importSubmit').textContent = '경로 확인'; }
document.addEventListener('click', e => {
  const report = e.target.closest('a[href^="/api/library/reports/"]');
  if (report) {
    e.preventDefault();
    const dialog = document.createElement('dialog');
    dialog.className = 'pdf-dialog'; dialog.setAttribute('aria-label','PDF 리포트 미리보기');
    const header = document.createElement('header');
    const title = document.createElement('h2'); title.textContent = 'PDF 리포트';
    const close = document.createElement('button'); close.textContent = '닫기'; close.onclick = () => dialog.close();
    const frame = document.createElement('iframe'); frame.title = 'PDF 리포트'; frame.src = report.getAttribute('href');
    header.append(title,close); dialog.append(header,frame); document.body.append(dialog);
    dialog.onclose = () => dialog.remove(); dialog.showModal(); return;
  }
  const button = e.target.closest('button'); if (!button) return;
  if (button.dataset.close) $(button.dataset.close).close();
  if ('newProject' in button.dataset) openProject();
  if ('import' in button.dataset) openImport();
  if ('project' in button.dataset) { state.project = button.dataset.project; state.cards = []; state.day = ''; state.selected = null; state.loading = true; localStorage.setItem('dit-project',state.project); render(); refresh(); }
  if ('day' in button.dataset) { state.day = button.dataset.day; render(); }
  if ('card' in button.dataset) { state.selected = button.dataset.card; render(); }
});
$('newProject').onclick = openProject;
$('importCard').onclick = openImport;
$('importBack').onclick = back;
$('refresh').onclick = refresh;
$('refreshVolumes').onclick = volumes;
$('search').oninput = e => { state.search = e.target.value; render(); };
$('libraryTab').onclick = () => { state.tab = 'library'; render(); };
$('reportsTab').onclick = () => { state.tab = 'reports'; render(); };
$('projectForm').onsubmit = async e => {
  e.preventDefault(); const button = e.submitter; button.disabled = true;
  try { const data = await api('/api/library/projects', {name:e.target.elements.name.value}); state.project = data.project.id; state.day = ''; state.cards = []; localStorage.setItem('dit-project', state.project); $('projectDialog').close(); await refresh(); }
  catch (err) { error('projectError',err.message); } finally { button.disabled = false; }
};
$('importForm').onsubmit = async e => {
  e.preventDefault(); const button = $('importSubmit'); button.disabled = true; error('importError','');
  try {
    if (!state.review) {
      const fields = Object.fromEntries(new FormData(e.target));
      const payload = {project_id:state.project, shoot_date:fields.shoot_date, camera_unit:fields.camera_unit, source_path:fields.source_path.trim(), replica_roots:[fields.replica1.trim(),fields.replica2.trim()], run_mode:'workflow'};
      if (payload.replica_roots[0] === payload.replica_roots[1]) throw new Error('서로 다른 복제 위치를 선택하세요.');
      const preview = await api('/api/roll-preview', payload);
      state.review = payload;
      $('importReview').innerHTML = `<h3>${escape(project().name)} / ${escape(preview.roll)}</h3><p>원본</p><p class="path">${escape(payload.source_path)}</p><h3>복제될 최종 경로</h3>${preview.replica_destinations.map(d => `<p class="path">${escape(d)}</p>`).join('')}<p class="muted">이 프로젝트와 원본·복제 위치를 확인한 뒤 시작하세요.</p>`;
      $('importFields').hidden = true; $('importReview').hidden = false; $('importBack').hidden = false; button.textContent = '확인한 경로로 복사 시작';
    } else {
      const result = await api('/api/runs',state.review);
      state.selected = result.run_id; state.day = ''; state.search = ''; $('search').value = ''; state.tab = 'library'; $('importDialog').close(); back(); await refresh();
    }
  } catch (err) { error('importError', err.message); } finally { button.disabled = false; }
};
refresh(); volumes();
setInterval(() => { if (!document.hidden && !$('importDialog').open && !$('projectDialog').open && !$('removeDialog').open) refresh(); }, 10000);

let removalTarget = null;
let removedProject = null;
$('removeProject').onclick = () => {
  if (!project()) return;
  removalTarget = {...project()};
  $('removeName').textContent = removalTarget.name;
  error('removeError', '');
  $('removeDialog').showModal();
};
$('removeForm').onsubmit = async e => {
  e.preventDefault(); e.submitter.disabled = true;
  try {
    await api(`/api/library/projects/${encodeURIComponent(removalTarget.id)}/remove`, {});
    removedProject = removalTarget;
    $('removedMessage').textContent = `${removedProject.name} 프로젝트를 목록에서 제거했습니다.`;
    $('removedNotice').hidden = false;
    state.project = null; state.day = ''; state.cards = []; state.selected = null;
    localStorage.removeItem('dit-project');
    $('removeDialog').close(); await refresh();
  } catch (err) { error('removeError', err.message); }
  finally { e.submitter.disabled = false; }
};
$('undoRemove').onclick = async () => {
  if (!removedProject) return;
  $('undoRemove').disabled = true;
  try {
    await api(`/api/library/projects/${encodeURIComponent(removedProject.id)}/restore`, {});
    state.project = removedProject.id; localStorage.setItem('dit-project', state.project);
    $('removedNotice').hidden = true; removedProject = null; await refresh();
  } catch (err) { error('error', err.message); }
  finally { $('undoRemove').disabled = false; }
};
