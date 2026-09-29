const $ = id => document.getElementById(id);
let storedProject = null;
try { storedProject = localStorage.getItem('dit-project'); } catch {}
const state = {projects: [], cards: [], project: storedProject, day: '', selected: null, tab: 'library', search: '', review: null, loading: false, dayReports: {}, reportNotice: ''};
const remember = value => { try { value ? localStorage.setItem('dit-project', value) : remember(null); } catch {} };
const labels = {waiting: '시작 대기', copying: '복사·체크섬 검증 중', verified: '검증 완료', reporting: 'PDF 생성 중', reported: '작업 완료', review: '확인 필요', failed: '작업 실패'};
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const project = () => state.projects.find(p => p.id === state.project);
const tone = phase => ['reported','verified'].includes(phase) ? 'good' : phase === 'failed' ? 'failed' : phase === 'review' ? 'warning' : 'active';
const badge = card => `<span class="status ${tone(card.phase)}">${escape(labels[card.phase] || '상태 확인 필요')}</span>`;
const dateTime = value => value ? new Date(value).toLocaleString('ko-KR') : '기록 없음';
let renderedProject = undefined;
const pickerFields = new Map();
window.DataHandlerPathChooser = {resolve(result) {
  const field = pickerFields.get(result.requestId);
  if (field?.isConnected && !field.disabled && result.path) field.value = result.path;
  pickerFields.delete(result.requestId);
}};
function attachPathChooser(field, container = field.parentElement) {
  if (window.webkit?.messageHandlers?.pathChooser) {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = '폴더 선택';
    button.onclick = () => { const requestId = crypto.randomUUID(); pickerFields.set(requestId,field); window.webkit.messageHandlers.pathChooser.postMessage({requestId,currentPath:field.value}); };
    container.append(button);
  }
}
attachPathChooser($('importForm').elements.source_path);
let replicaSequence = 0;
function updateReplicaRows() {
  const rows = [...$('replicaPaths').children];
  rows.forEach((row, index) => {
    row.querySelector('label').textContent = `백업 경로 ${index + 1}`;
    const remove = row.querySelector('[data-remove-replica]');
    remove.disabled = rows.length === 1;
    remove.setAttribute('aria-label', `백업 경로 ${index + 1} 삭제`);
  });
  $('replicaCount').textContent = `${rows.length}개 경로`;
}
function addReplicaRow(value = '', focus = false) {
  const row = document.createElement('div');
  row.className = 'replica-row';
  const id = `replica-path-${++replicaSequence}`;
  row.innerHTML = `<div class="replica-row-header"><label for="${id}"></label><button type="button" data-remove-replica>삭제</button></div><div class="replica-row-controls"><input id="${id}" name="replica_roots" required placeholder="/Volumes/BACKUP" list="destinationChoices" autocomplete="off"></div>`;
  const field = row.querySelector('input');
  field.value = value;
  attachPathChooser(field, row.querySelector('.replica-row-controls'));
  row.querySelector('[data-remove-replica]').onclick = () => {
    if ($('replicaPaths').children.length === 1) return;
    const next = row.nextElementSibling || row.previousElementSibling;
    for (const [requestId, target] of pickerFields) if (target === field) pickerFields.delete(requestId);
    row.remove(); updateReplicaRows(); next.querySelector('input').focus();
  };
  $('replicaPaths').append(row); updateReplicaRows();
  if (focus) field.focus();
}
$('addReplica').onclick = () => addReplicaRow('', true);

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
  else if (!state.cards.length) $('content').innerHTML = empty('첫 번째 카드를 가져오세요', '원본 카드와 백업 경로를 선택하세요. 경로는 1개부터 필요한 만큼 추가할 수 있습니다. 복사·검증 결과와 PDF가 이곳에 기록됩니다.', '<button class="primary" data-import>카드 가져오기</button>');
  else if (!cards.length) $('content').innerHTML = empty('일치하는 카드가 없습니다', '검색어나 촬영일 선택을 변경하세요.');
  else if (state.tab === 'reports') {
    const reportDays = [...new Set(cards.map(c => c.shoot_date))].sort().reverse();
    const dayRows = reportDays.map(d => {
      const dayCards = cards.filter(c => c.shoot_date === d);
      const busy = dayCards.filter(c => ['waiting','copying','reporting'].includes(c.phase)).length;
      return `<div class="report-row day-report"><div><strong>${escape(d)} DIT 리포트</strong><small>카드 ${dayCards.length}개 / 검증 완료 ${dayCards.filter(c => c.verified).length}개${busy ? ` / 진행 중 ${busy}개` : ''}</small></div><button data-day-report="${escape(d)}">${state.dayReports[d] ? '다시 생성' : '생성·열기'}</button></div>`;
    });
    const rows = cards.flatMap(c => pdfs(c).map(a => `<div class="report-row"><div><strong>${escape(c.roll)}</strong><small>${escape(c.shoot_date)} / 카메라 ${escape(c.camera_unit)}</small></div>${artifactLink(a)}</div>`));
    $('content').innerHTML = dayRows.join('') + (state.reportNotice ? `<p class="muted report-notice" role="status">${escape(state.reportNotice)}</p>` : '') + (rows.join('') || empty('카드 PDF가 아직 없습니다', '완료 기록에 리포트가 등록되면 이곳에서 열 수 있습니다. 작업 상태와 에이전트 검토에서 결과를 확인하세요.'));
  } else $('content').innerHTML = `<table><thead><tr><th>카드 / 촬영일</th><th>카메라</th><th>작업 상태</th><th>체크섬</th></tr></thead><tbody>${cards.map(c => `<tr class="${c.run_id === state.selected ? 'selected' : ''}"><td data-label="카드"><button data-card="${escape(c.run_id)}" aria-label="${escape(c.roll)} 카드 선택">${escape(c.roll)}</button><small>${escape(c.shoot_date)}</small></td><td data-label="카메라">${escape(c.camera_unit)}</td><td data-label="작업 상태">${badge(c)}</td><td data-label="체크섬"><span class="${c.verified ? 'good' : 'muted'}">${c.verified ? '검증 완료' : '미확인'}</span></td></tr>`).join('')}</tbody></table>`;
  $('librarySummary').textContent = `${cards.length}개 카드 / ${cards.filter(c => c.verified).length}개 검증 완료`;
  document.dispatchEvent(new CustomEvent('dit-card-selected', {detail:{card:state.cards.find(c => c.run_id === state.selected)}}));
  const active = state.cards.filter(c => ['waiting','copying','reporting','review','failed'].includes(c.phase));
  $('queue').innerHTML = active.length ? active.map(c => `<div class="queue-row"><button data-card="${escape(c.run_id)}">${escape(c.roll)}</button>${badge(c)}<span class="muted">마지막 작업 기록 ${escape(dateTime(c.updated_at))}</span></div>`).join('') : '<p>진행 중이거나 확인이 필요한 작업이 없습니다.</p>';
  if (renderedProject !== state.project) {
    renderedProject = state.project;
    document.dispatchEvent(new CustomEvent('dit-project-changed', {detail:{projectId:state.project}}));
  }
}
let revision = 0, lastSignature = '';
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
    const signature = JSON.stringify([data.projects, dataCards.cards]);
    const unchanged = signature === lastSignature && !state.loading;
    lastSignature = signature;
    state.cards = dataCards.cards.reverse();
    if (!state.cards.some(c => c.run_id === state.selected)) state.selected = state.cards[0]?.run_id || null;
    state.loading = false;
    error('error', '');
    $('syncTime').textContent = `기록 확인 ${new Date().toLocaleTimeString('ko-KR')}`;
    if (!unchanged) render();
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
  pickerFields.clear();
  $('replicaPaths').replaceChildren();
  const latest = state.cards.find(c => c.replica_roots?.length);
  const roots = project().replica_roots?.length ? project().replica_roots : latest?.replica_roots || [];
  (roots.length ? roots : ['']).forEach(value => addReplicaRow(value));
  const now = new Date();
  if (latest?.camera_unit) $('importForm').elements.camera_unit.value = latest.camera_unit;
  $('importForm').elements.shoot_date.value = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  $('importProject').textContent = `프로젝트: ${project().name}`;
  back(); error('importError',''); $('importDialog').showModal();
  const results = await Promise.allSettled([api('/api/sources'),api('/api/destinations')]);
  ['sourceChoices','destinationChoices'].forEach((id,i) => { const result = results[i]; $(id).innerHTML = result.status === 'fulfilled' ? (result.value.sources || result.value.destinations || []).map(p => `<option value="${escape(p.path)}"></option>`).join('') : ''; });
}
function openPdf(url, heading = 'PDF 리포트') {
  const dialog = document.createElement('dialog');
  dialog.className = 'pdf-dialog'; dialog.setAttribute('aria-label', `${heading} 미리보기`);
  const header = document.createElement('header');
  const title = document.createElement('h2'); title.textContent = heading;
  const close = document.createElement('button'); close.textContent = '닫기'; close.onclick = () => dialog.close();
  const frame = document.createElement('iframe'); frame.title = heading; frame.src = url;
  header.append(title,close); dialog.append(header,frame); document.body.append(dialog);
  dialog.onclose = () => dialog.remove(); dialog.showModal();
}
async function createDayReport(button) {
  const day = button.dataset.dayReport;
  button.disabled = true; button.textContent = '생성 중…';
  try {
    const result = await api(`/api/library/projects/${encodeURIComponent(state.project)}/dit-report`, {shoot_date: day});
    state.dayReports[day] = result.url;
    state.reportNotice = `${day} DIT 리포트를 백업 ${result.saved_to.length}곳의 00_Master/reports에 저장했습니다.` +
      (result.unavailable.length ? ` 연결되지 않은 백업 ${result.unavailable.length}곳에는 저장하지 못했습니다.` : '');
    render(); openPdf(`${result.url}?t=${Date.now()}`, `${day} DIT 리포트`);
  } catch (err) { state.reportNotice = ''; error('error', `DIT 리포트를 만들지 못했습니다. ${err.message}`); render(); }
}
function back() { state.review = null; $('importFields').hidden = false; $('importReview').hidden = true; $('importBack').hidden = true; $('importSubmit').textContent = '경로 확인'; }
document.addEventListener('click', e => {
  const report = e.target.closest('a[href^="/api/library/reports/"]');
  if (report) { e.preventDefault(); openPdf(report.getAttribute('href')); return; }
  const button = e.target.closest('button'); if (!button) return;
  if ('dayReport' in button.dataset) createDayReport(button);
  if (button.dataset.close) $(button.dataset.close).close();
  if ('newProject' in button.dataset) openProject();
  if ('import' in button.dataset) openImport();
  if ('project' in button.dataset) { state.project = button.dataset.project; state.cards = []; state.dayReports = {}; state.reportNotice = ''; state.day = ''; state.selected = null; state.loading = true; remember(state.project); render(); refresh(); }
  if ('day' in button.dataset) { state.day = button.dataset.day; render(); }
  if ('card' in button.dataset) { state.selected = button.dataset.card; render(); }
});
$('newProject').onclick = openProject;
$('importCard').onclick = openImport;
$('importBack').onclick = back;
$('refresh').onclick = refresh;
$('refreshVolumes').onclick = volumes;
let searchTimer = 0;
$('search').oninput = e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = e.target.value; render(); }, 120); };
$('libraryTab').onclick = () => { state.tab = 'library'; state.reportNotice = ''; render(); };
$('reportsTab').onclick = () => { state.tab = 'reports'; render(); };
$('projectForm').onsubmit = async e => {
  e.preventDefault(); const button = e.submitter; button.disabled = true;
  try { const data = await api('/api/library/projects', {name:e.target.elements.name.value}); state.project = data.project.id; state.day = ''; state.cards = []; remember(state.project); $('projectDialog').close(); await refresh(); }
  catch (err) { error('projectError',err.message); } finally { button.disabled = false; }
};
$('importForm').onsubmit = async e => {
  e.preventDefault(); const button = $('importSubmit'); button.disabled = true; $('importBack').disabled = true; error('importError','');
  try {
    if (!state.review) {
      const form = new FormData(e.target);
      const fields = Object.fromEntries(form);
      const roots = form.getAll('replica_roots').map(value => value.trim());
      if (!roots.length || roots.some(value => !value)) throw new Error('백업 경로를 입력하세요. 사용하지 않는 경로는 삭제할 수 있습니다.');
      if (new Set(roots).size !== roots.length) throw new Error('서로 다른 백업 경로를 선택하세요.');
      const payload = {project_id:state.project, shoot_date:fields.shoot_date, camera_unit:fields.camera_unit, source_path:fields.source_path.trim(), replica_roots:roots, run_mode:'workflow'};
      if (roots.includes(payload.source_path)) throw new Error('원본과 백업 경로는 서로 달라야 합니다.');
      $('importFields').querySelectorAll('input, button').forEach(control => { control.disabled = true; });
      const preview = await api('/api/roll-preview', payload);
      state.review = payload;
      $('importReview').innerHTML = `<h3>${escape(project().name)} / ${escape(preview.roll)}</h3><p>원본</p><p class="path">${escape(payload.source_path)}</p><h3>백업될 최종 경로 · ${preview.replica_destinations.length}개</h3>${preview.replica_destinations.map((d, i) => `<p class="path">${i + 1}. ${escape(d)}</p>`).join('')}<p class="muted">이 프로젝트와 원본·백업 경로를 확인한 뒤 시작하세요.</p>`;
      $('importFields').hidden = true; $('importReview').hidden = false; $('importBack').hidden = false; button.textContent = '확인한 경로로 복사 시작';
    } else {
      const result = await api('/api/runs',state.review);
      state.selected = result.run_id; state.day = ''; state.search = ''; $('search').value = ''; state.tab = 'library'; $('importDialog').close(); back(); await refresh();
    }
  } catch (err) { error('importError', err.message); } finally {
    button.disabled = false; $('importBack').disabled = false;
    $('importFields').querySelectorAll('input, button').forEach(control => { control.disabled = false; });
    updateReplicaRows();
  }
};
refresh(); volumes();
const idle = () => !document.hidden && !$('importDialog').open && !$('projectDialog').open && !$('removeDialog').open && !document.querySelector('.pdf-dialog[open]');
setInterval(() => { if (idle()) refresh(); }, 10000);
document.addEventListener('visibilitychange', () => { if (idle()) refresh(); });

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
    remember(null);
    $('removeDialog').close(); await refresh();
  } catch (err) { error('removeError', err.message); }
  finally { e.submitter.disabled = false; }
};
$('undoRemove').onclick = async () => {
  if (!removedProject) return;
  $('undoRemove').disabled = true;
  try {
    await api(`/api/library/projects/${encodeURIComponent(removedProject.id)}/restore`, {});
    state.project = removedProject.id; remember(state.project);
    $('removedNotice').hidden = true; removedProject = null; await refresh();
  } catch (err) { error('error', err.message); }
  finally { $('undoRemove').disabled = false; }
};
