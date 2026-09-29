(() => {
  const el = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let selected = null, signature = '', sending = false, token = null;
  const status = r => r.state === 'pending' ? '검토 대기' : r.state === 'running' ? '검토 중' :
    ({verified:'확인 완료',review_needed:'확인 필요',skipped:'연결 없음'}[r.status] || '확인 필요');
  function render(card) {
    selected = card;
    const reviews = card?.agent_reviews || [];
    el('reviewContext').textContent = card ? `${card.roll} / ${card.shoot_date} / 카메라 ${card.camera_unit}` : '카드를 선택하세요.';
    el('reviewRetry').disabled = sending || !reviews.length || reviews.some(r => ['running','pending'].includes(r.state));
    const next = JSON.stringify([card?.run_id, reviews]);
    if (next === signature) return;
    signature = next;
    const overviewFocus = document.activeElement?.dataset.jumpReview;
    el('reviewOverview').innerHTML = reviews.map(r => `<button data-jump-review="${safe(r.phase)}" class="${r.status === 'review_needed' ? 'warning' : r.status === 'verified' ? 'good' : 'muted'}">${safe(r.title)}: ${safe(status(r))}</button>`).join('');
    if (overviewFocus) [...el('reviewOverview').querySelectorAll('button')].find(b => b.dataset.jumpReview === overviewFocus)?.focus({preventScroll:true});
    const container = el('reviewMessages');
    const opened = [...container.querySelectorAll('details[open]')].map(d => d.dataset.phase);
    const activePhase = container.contains(document.activeElement) ? document.activeElement.closest('[data-phase]')?.dataset.phase : null;
    const scroll = container.scrollTop;
    container.innerHTML = reviews.length ? reviews.map(r => {
      const findings = r.findings || [];
      const total = r.finding_count ?? findings.length;
      const shade = r.status === 'verified' ? 'good' : r.status === 'review_needed' ? 'warning' : 'muted';
      return `<article class="review-message" id="review-${safe(r.phase)}"><header><h3>${safe(r.title)}</h3><span class="${shade}">${safe(status(r))}</span></header>` +
        `<p>${safe(r.summary)}</p>` + (r.scope ? `<p class="muted">릴 ${safe(r.scope.reel)} / ${safe(r.scope.shootDayKey)} / ${safe(r.scope.cameraId)}</p>` : '') +
        (r.analysis ? `<p class="muted">에이전트 의견</p><p class="review-analysis">${safe(r.analysis)}</p>` : '') +
        (r.model_notice ? `<p class="muted">${safe(r.model_notice)}</p>` : '') +
        (findings.length ? `<details data-phase="${safe(r.phase)}" ${opened.includes(r.phase) ? 'open' : ''}><summary>확인할 항목 ${total}개와 추천 행동</summary>${findings.slice(0,100).map(f =>
          `<dl class="review-finding">${f.file ? `<dt>파일</dt><dd class="path">${safe(f.file)}</dd>` : ''}<dt>확인된 근거</dt><dd>${safe(f.evidence)}</dd><dt>원인 판단</dt><dd>${safe(f.cause)}</dd><dt>추천 행동</dt><dd>${safe(f.action)}</dd></dl>`).join('')}${total > 100 ? '<p>나머지 항목은 전체 검토 기록에서 확인하세요.</p>' : ''}</details>` : '') +
        (r.limitations || []).map(t => `<p class="muted">${safe(t)}</p>`).join('') +
        (r.finished_at ? `<p class="muted">검토 시각 ${safe(new Date(r.finished_at).toLocaleString('ko-KR'))}</p><a href="/api/agent/reviews/${encodeURIComponent(card.run_id)}/${encodeURIComponent(r.phase)}" target="_blank" rel="noopener">전체 검토 기록</a>` : '') + '</article>';
    }).join('') : '<p class="muted">복제와 보고서 작업이 끝나면 검토 결과가 여기에 표시됩니다.</p>';
    container.scrollTop = scroll;
    if (activePhase) [...container.querySelectorAll('details')].find(d => d.dataset.phase === activePhase)?.querySelector('summary')?.focus({preventScroll:true});
    el('reviewAnnouncement').textContent = reviews.map(r => `${r.title}: ${status(r)}`).join(', ');
  }
  document.addEventListener('dit-card-selected', event => {
    if (selected?.run_id !== event.detail.card?.run_id) { el('reviewError').hidden = true; }
    render(event.detail.card);
  });
  el('reviewRetry').onclick = async () => {
    if (!selected || sending) return;
    const card = selected;
    sending = true; render(selected); el('reviewRetry').textContent = '접수 중';
    try {
      if (!token) {
        const session = await fetch('/api/agent/session');
        if (!session.ok) throw new Error('앱 연결을 확인해 주세요.');
        token = (await session.json()).token;
      }
      const response = await fetch(`/api/agent/reviews/${encodeURIComponent(card.run_id)}/retry`, {
        method:'POST', headers:{'Content-Type':'application/json','X-DIT-Agent':token},
        body:JSON.stringify({phases:(card.agent_reviews || []).map(r => r.phase)})
      });
      if (!response.ok) { if (response.status === 401) token = null; throw new Error((await response.json()).detail || '검토를 접수하지 못했습니다.'); }
      el('reviewError').hidden = true;
      await refresh();
    } catch (error) {
      if (selected?.run_id === card.run_id) { el('reviewError').textContent = error.message; el('reviewError').hidden = false; }
    } finally {sending = false; el('reviewRetry').textContent = '다시 검토'; render(selected);}
  };
  el('reviewOverview').onclick = event => {
    const phase = event.target.closest('[data-jump-review]')?.dataset.jumpReview;
    if (phase) el(`review-${phase}`)?.scrollIntoView({block:'nearest'});
  };
  render(state.cards.find(c => c.run_id === state.selected));
})();
