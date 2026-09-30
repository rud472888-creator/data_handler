(() => {
  const el = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const LABEL = {queued:'대기 중', running:'검사 중', completed:'검사 완료', partial:'일부만 검사', failed:'검사 실패', blocked:'시작할 수 없음', cancelled:'취소됨', disabled:'사용 안 함'};
  const TONE = {completed:'good', running:'active', queued:'active', partial:'warning', failed:'failed', blocked:'warning', cancelled:'muted'};
  const REASON = {
    existing_processing_not_finished:'복제·보고서 작업이 끝난 뒤에 시작할 수 있습니다.',
    backup_not_verified:'복제본 체크섬 검증이 끝나지 않아 검사하지 않습니다.',
    manifest_missing:'복제 manifest가 없어 검사할 클립을 확정할 수 없습니다.',
    replica_links_missing:'복제본 위치 기록이 없어 검사하지 않습니다.',
    no_video_files:'검사할 영상 파일이 없습니다.',
    model_not_installed:'Qwen3.5-4B 모델이 설치되어 있지 않습니다. 설치 후 다시 시작하세요.',
    unsupported_platform:'이 컴퓨터에서는 MLX 추론을 실행할 수 없습니다 (Apple Silicon macOS 필요).',
    runtime_missing:'추론 런타임(mlx-vlm)을 불러오지 못했습니다.',
    model_changed:'다른 모델로 시작된 검사입니다. 결과를 섞지 않으려면 새로 검사하세요.',
    incomplete_coverage:'미지원·실패·누락된 항목이 있어 전체 검사가 끝나지 않았습니다.',
    no_inspectable_clips:'검사할 수 있는 클립이 없었습니다.',
    backend_stopped:'모델 추론이 응답하지 않아 중단했습니다.',
    worker_crashed:'검사 프로세스가 오류로 종료되었습니다.',
    spawn_failed:'검사 프로세스를 시작하지 못했습니다.'
  };
  let selected = null, token = null, busy = false, pollTimer = null;
  const latest = card => (card?.visual_qa?.runs || []).at(-1) || null;
  function summaryText(run) {
    const c = run.counts || {};
    if (['running','queued'].includes(run.status) && !run.interrupted) {
      const parts = [];
      if (c.clips_total != null) parts.push(`클립 ${c.clips_done ?? 0}/${c.clips_total}`);
      // Total frame count is not trusted, so only what was processed is shown.
      parts.push(`처리한 프레임 ${c.frames_analyzed ?? 0}개`);
      if (c.frames_failed) parts.push(`분석 실패 ${c.frames_failed}개`);
      return parts.join(' · ') + (run.current_clip ? ` — ${run.current_clip}` : '');
    }
    return `클립 ${c.clips_total ?? 0}개 · 분석한 프레임 ${c.frames_analyzed ?? 0}개 · 분석 실패 ${c.frames_failed ?? 0}개 · 미지원 ${c.clips_unsupported ?? 0}개 · 의심 구간 ${run.events_total ?? c.events_total ?? 0}건`;
  }
  function render(card) {
    selected = card;
    const qa = card?.visual_qa, run = latest(card);
    el('visualQaContext').textContent = card ? `${card.roll} / ${card.shoot_date}${run?.revision > 1 ? ` / 리비전 ${run.revision}` : ''}` : '카드를 선택하세요.';
    const status = run?.interrupted ? '중단됨' : run ? (LABEL[run.status] || run.status) : qa?.status === 'blocked' ? '시작할 수 없음' : '미실행';
    el('visualQaStatus').textContent = status;
    el('visualQaStatus').className = `status ${run?.interrupted ? 'warning' : TONE[run?.status || qa?.status] || 'muted'}`;
    el('visualQaSummary').textContent = run ? summaryText(run) : (qa?.blocked ? (REASON[qa.blocked.reason] || qa.blocked.message) : card ? '이 카드는 아직 영상 QA를 실행하지 않았습니다.' : '');
    const notes = [];
    if (run?.mock_backend) notes.push('테스트용 MOCK 결과입니다. 실제 모델 검사가 아닙니다.');
    if (run?.limited) notes.push(`제한 범위 검사입니다 (${run.limits}). 전체 클립 검사가 아닙니다.`);
    if (run?.interrupted) notes.push('검사 프로세스가 중단되었습니다. 재시도하면 완료된 프레임은 재사용합니다.');
    if (run && ['partial','failed','blocked','cancelled'].includes(run.status) && !run.interrupted) notes.push(REASON[run.reason] || run.message || run.reason || '');
    if (run?.status === 'completed' && !run.interrupted) notes.push('검사한 범위의 자동 결과이며 사람이 확인해야 합니다.');
    if (run?.report_error) notes.push(`보고서 생성 오류: ${run.report_error}`);
    el('visualQaNotice').textContent = notes.filter(Boolean).join(' ');
    el('visualQaNotice').hidden = !el('visualQaNotice').textContent;
    const active = run && ['queued','running'].includes(run.status) && !run.interrupted;
    const start = el('visualQaStart');
    const needsNewRevision = run?.status === 'completed' || run?.reason === 'model_changed';
    start.textContent = !run ? '영상 QA 시작' : active ? '검사 중' : needsNewRevision ? '다시 검사 (새 리비전)' : '재시도';
    start.dataset.action = !run ? 'start' : needsNewRevision ? 'rerun' : 'retry';
    start.disabled = !card || busy || active;
    el('visualQaCancel').hidden = !active;
    const link = el('visualQaReport');
    link.hidden = !(run?.report_ready);
    if (run?.report_ready) link.href = `/api/library/visual-qa/${encodeURIComponent(card.run_id)}/${encodeURIComponent(run.qa_id)}/report.html`;
    const project = state.projects.find(p => p.id === state.project);
    el('visualQaAuto').checked = !!project?.visual_qa;
    el('visualQaAuto').disabled = !project;
    el('visualQaAnnouncement').textContent = run ? `영상 QA ${status}` : '';
    clearTimeout(pollTimer);
    if (active && card) pollTimer = setTimeout(() => poll(card), 3000);
  }
  async function poll(card) {
    if (selected?.run_id !== card.run_id) return;
    try {
      const response = await fetch(`/api/library/cards/${encodeURIComponent(card.run_id)}/visual-qa`);
      if (response.ok) {
        const summary = await response.json();
        if (selected?.run_id === card.run_id) render({...selected, visual_qa: summary});
      }
    } catch {}
  }
  async function session() {
    if (!token) {
      const response = await fetch('/api/visual-qa/session');
      if (!response.ok) throw new Error('앱 연결을 확인해 주세요.');
      token = (await response.json()).token;
    }
    return token;
  }
  async function post(path, body) {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-DIT-Visual-QA':await session()}, body:JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { if (response.status === 401) token = null; throw new Error(typeof data.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.'); }
    return data;
  }
  const showError = message => { el('visualQaError').textContent = message || ''; el('visualQaError').hidden = !message; };
  el('visualQaStart').onclick = async () => {
    if (!selected || busy) return;
    const card = selected;
    busy = true; showError(''); render(card);
    try {
      const result = await post(`/api/library/cards/${encodeURIComponent(card.run_id)}/visual-qa`, {action: el('visualQaStart').dataset.action});
      if (selected?.run_id === card.run_id) render({...selected, visual_qa: result.summary});
    } catch (error) { showError(error.message); }
    finally { busy = false; if (selected) render(selected); }
  };
  el('visualQaCancel').onclick = async () => {
    const run = latest(selected);
    if (!run) return;
    try { await post(`/api/library/cards/${encodeURIComponent(selected.run_id)}/visual-qa/${encodeURIComponent(run.qa_id)}/cancel`, {}); showError(''); }
    catch (error) { showError(error.message); }
  };
  el('visualQaAuto').onchange = async event => {
    const project = state.projects.find(p => p.id === state.project);
    if (!project) return;
    const enabled = event.target.checked;
    try { await post(`/api/library/projects/${encodeURIComponent(project.id)}/visual-qa`, {enabled}); project.visual_qa = enabled; showError(''); }
    catch (error) { event.target.checked = !enabled; showError(error.message); }
  };
  document.addEventListener('dit-card-selected', event => { if (selected?.run_id !== event.detail.card?.run_id) showError(''); render(event.detail.card); });
  render(state.cards.find(c => c.run_id === state.selected));
})();
