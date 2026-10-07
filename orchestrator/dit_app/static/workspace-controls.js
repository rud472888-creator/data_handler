/* Native controls and keyboard equivalents for the DIT panel layout. */
(() => {
  const el = id => document.getElementById(id);
  const narrow = matchMedia('(max-width: 1099px)');
  const mobile = matchMedia('(max-width: 767px)');
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem('dit-workspace-panels')) || {}; } catch {}
  const panels = {
    navigator: Number.isFinite(stored.navigator) ? Math.max(180, Math.min(320, stored.navigator)) : 216,
    inspector: Number.isFinite(stored.inspector) ? Math.max(240, Math.min(420, stored.inspector)) : 304,
    open: typeof stored.open === 'boolean' ? stored.open : !narrow.matches,
  };
  const save = () => { try { localStorage.setItem('dit-workspace-panels', JSON.stringify(panels)); } catch {} };
  function showInspector(open, restore = false) {
    panels.open = open;
    document.body.dataset.inspector = open ? 'open' : 'closed';
    el('inspectorToggle').setAttribute('aria-pressed', String(open));
    el('inspectorToggle').setAttribute('aria-expanded', String(open));
    if (!open && (restore || el('cardInspector').contains(document.activeElement))) el('inspectorToggle').focus();
  }
  el('inspectorToggle').onclick = () => { showInspector(!panels.open); save(); };
  el('inspectorClose').onclick = () => { showInspector(false, true); save(); };
  narrow.addEventListener('change', () => showInspector(!narrow.matches));
  showInspector(panels.open);

  function resizePanel(name, minimum, maximum, reverse = false) {
    const splitter = el(`${name}Splitter`);
    function update(value) {
      panels[name] = Math.round(Math.max(minimum, Math.min(maximum, value)));
      document.documentElement.style.setProperty(`--${name}-width`, `${panels[name]}px`);
      splitter.setAttribute('aria-valuenow', panels[name]);
      splitter.setAttribute('aria-valuetext', `${panels[name]}픽셀`);
    }
    update(panels[name]);
    splitter.addEventListener('keydown', event => {
      const step = event.shiftKey ? 40 : 10;
      let value;
      if (event.key === 'ArrowLeft') value = panels[name] + (reverse ? step : -step);
      if (event.key === 'ArrowRight') value = panels[name] + (reverse ? -step : step);
      if (event.key === 'Home') value = minimum;
      if (event.key === 'End') value = maximum;
      if (value !== undefined) { event.preventDefault(); update(value); save(); }
    });
    let drag;
    splitter.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      drag = {x: event.clientX, width: panels[name], id: event.pointerId};
      splitter.setPointerCapture(event.pointerId);
      splitter.focus(); event.preventDefault();
    });
    splitter.addEventListener('pointermove', event => {
      if (drag && event.pointerId === drag.id) update(drag.width + (event.clientX - drag.x) * (reverse ? -1 : 1));
    });
    splitter.addEventListener('lostpointercapture', () => { if (drag) { drag = null; save(); } });
    splitter.addEventListener('pointerup', event => {
      if (drag && event.pointerId === drag.id) splitter.releasePointerCapture(event.pointerId);
    });
  }
  resizePanel('navigator', 180, 320);
  resizePanel('inspector', 240, 420, true);

  function navigator(open, restore = false) {
    document.body.dataset.navigator = open ? 'open' : 'closed';
    el('navigatorToggle').setAttribute('aria-expanded', String(open));
    if (!open && restore) el('navigatorToggle').focus();
    if (open) el('projects').querySelector('button[aria-current="true"], button')?.focus();
  }
  el('navigatorToggle').onclick = () => navigator(document.body.dataset.navigator !== 'open');
  mobile.addEventListener('change', () => navigator(false));
  document.addEventListener('click', event => {
    if (!mobile.matches || document.body.dataset.navigator !== 'open') return;
    if (event.target.closest('[data-project], [data-day]')) navigator(false, true);
    else if (!event.target.closest('#navigator, #navigatorToggle')) navigator(false);
  });

  const inspectorTabs = [el('detailsTab'), el('reviewTab')];
  function inspectorTab(button, focus = false) {
    inspectorTabs.forEach(tab => {
      const selected = tab === button;
      tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
      el(tab.getAttribute('aria-controls')).hidden = !selected;
    });
    if (focus) button.focus();
  }
  inspectorTabs.forEach(button => { button.onclick = () => inspectorTab(button); });
  function arrowGroup(container, selector, vertical = false) {
    container.addEventListener('keydown', event => {
      const button = event.target.closest(selector);
      if (!button) return;
      const buttons = [...container.querySelectorAll(selector)].filter(b => !b.disabled);
      const index = buttons.indexOf(button);
      let next;
      if (event.key === (vertical ? 'ArrowDown' : 'ArrowRight')) next = Math.min(index + 1, buttons.length - 1);
      if (event.key === (vertical ? 'ArrowUp' : 'ArrowLeft')) next = Math.max(index - 1, 0);
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = buttons.length - 1;
      if (next !== undefined) {
        event.preventDefault(); const target = buttons[next];
        if (!target) return;
        const card = target.dataset.card, day = target.dataset.day, projectId = target.dataset.project;
        target.focus(); target.click();
        // Selecting a card/day can render a fresh table or navigator.
        if (card !== undefined || day !== undefined || projectId !== undefined) {
          const key = card !== undefined ? 'card' : day !== undefined ? 'day' : 'project';
          const value = card ?? day ?? projectId;
          [...container.querySelectorAll(selector)].find(b => b.dataset[key] === value)?.focus({preventScroll: true});
        }
      }
    });
  }
  arrowGroup(document.querySelector('.inspector-tabs'), 'button');
  arrowGroup(document.querySelector('.mode-switch'), 'button');
  arrowGroup(document.querySelector('.library-toolbar .tabs'), 'button');
  arrowGroup(el('content'), 'button[data-card]', true);
  arrowGroup(el('projects'), 'button[data-project]', true);
  arrowGroup(el('days'), 'button[data-day]', true);

  let detailSignature = '';
  const announcement = document.createElement('p');
  announcement.id = 'cardAnnouncement'; announcement.className = 'sr-only'; announcement.setAttribute('role', 'status');
  el('cardInspector').append(announcement);
  function cardDetails(card) {
    const signature = JSON.stringify(card || null);
    if (signature === detailSignature) return;
    detailSignature = signature;
    const pane = el('cardDetails');
    const scroll = pane.scrollTop;
    const focusedLink = pane.contains(document.activeElement) ? document.activeElement.closest('a')?.getAttribute('href') : null;
    if (!card) {
      pane.innerHTML = '<p class="muted">카드를 선택하면 원본·백업 경로와 검증 결과를 볼 수 있어요.</p>';
      announcement.textContent = ''; return;
    }
    const destinations = card.destinations || [];
    const reports = pdfs(card);
    const count = card.file_count == null ? '완료 기록 없음' : `${Number(card.file_count).toLocaleString('ko-KR')}개`;
    pane.innerHTML = `<div class="card-identity"><strong>${escape(card.roll)}</strong>${badge(card)}</div>` +
      `<dl class="metadata-list"><div><dt>촬영일</dt><dd>${escape(card.shoot_date)}</dd></div><div><dt>카메라</dt><dd>${escape(card.camera_unit)}</dd></div><div><dt>파일 수</dt><dd>${escape(count)}</dd></div><div><dt>체크섬</dt><dd class="${card.verified ? 'good' : 'muted'}">${card.verified ? '검증 완료' : '검증 완료 기록 없음'}</dd></div><div><dt>최근 기록</dt><dd>${escape(dateTime(card.updated_at))}</dd></div></dl>` +
      `<section class="inspector-section"><h3>${icon('folder')}원본 경로</h3><p class="path">${escape(card.source_path)}</p></section>` +
      `<section class="inspector-section"><h3>${icon('hard-drive')}백업 경로 · ${destinations.length}개</h3>${destinations.map((path, i) => `<div class="destination"><small class="muted">백업 ${i + 1}</small><p class="path">${escape(path)}</p></div>`).join('') || '<p class="muted">등록된 경로 없음</p>'}</section>` +
      (card.error || card.failed_files?.length ? `<section class="inspector-section"><h3>${icon('triangle-alert')}확인할 항목</h3>${card.error ? `<p class="failed">${escape(card.error)}</p>` : ''}${(card.failed_files || []).slice(0, 100).map(file => `<p class="path">${escape(typeof file === 'string' ? file : JSON.stringify(file))}</p>`).join('')}</section>` : '') +
      `<section class="inspector-section"><h3>${icon('file-text')}검증 리포트</h3>${reports.map(artifactLink).join('') || '<p class="muted">완료 기록에 등록된 PDF 없음</p>'}</section>`;
    pane.scrollTop = scroll;
    if (focusedLink) [...pane.querySelectorAll('a')].find(link => link.getAttribute('href') === focusedLink)?.focus({preventScroll: true});
    announcement.textContent = `${card.roll} 카드 선택. ${labels[card.phase] || '상태 확인 필요'}.`;
  }
  document.addEventListener('dit-card-selected', event => cardDetails(event.detail.card));
  cardDetails(state.cards.find(card => card.run_id === state.selected));

  // <dialog> supplies focus containment and Escape. Restore a surviving opener
  // even when a refresh replaced the original project/card button.
  let lastOutsideFocus = null;
  document.addEventListener('focusin', event => { if (!event.target.closest('dialog')) lastOutsideFocus = event.target; });
  // Safari and AXPress can activate a button without first focusing it.
  // Capture that opener before the button's handler shows the dialog.
  document.addEventListener('click', event => {
    const opener = event.target.closest('button, a[href]');
    if (opener && !opener.closest('dialog')) lastOutsideFocus = opener;
  }, true);
  const openers = new WeakMap();
  const watched = new WeakSet();
  function watchDialogs() {
    document.querySelectorAll('dialog').forEach(dialog => {
      if (watched.has(dialog)) return;
      watched.add(dialog);
      dialog.addEventListener('close', () => {
        const opener = openers.get(dialog);
        queueMicrotask(() => {
          if (document.querySelector('dialog[open]')) return;
          if (opener?.isConnected && opener.getClientRects().length) opener.focus({preventScroll: true});
          else if (!document.activeElement || document.activeElement === document.body || dialog.contains(document.activeElement)) el('mainContent').focus({preventScroll: true});
        });
      });
    });
  }
  const observer = new MutationObserver(records => {
    watchDialogs();
    records.forEach(record => {
      if (record.type === 'attributes' && record.target.open) openers.set(record.target, lastOutsideFocus);
    });
  });
  observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['open']});
  watchDialogs();
  document.addEventListener('keydown', event => {
    const dialog = document.querySelector('dialog[open]');
    if (event.key === 'Tab' && dialog) {
      // Keep all native controls reachable even when a macOS webview's default
      // tab policy skips buttons. Escape remains the native dialog action.
      const targets = [...dialog.querySelectorAll('button, a[href], input, select, textarea, summary, iframe, [tabindex]')]
        .filter(target => !target.disabled && target.tabIndex >= 0 && target.getClientRects().length);
      if (targets.length) {
        const current = targets.indexOf(document.activeElement);
        const next = current < 0 ? (event.shiftKey ? targets.length - 1 : 0)
          : (current + (event.shiftKey ? -1 : 1) + targets.length) % targets.length;
        event.preventDefault(); targets[next].focus();
      }
    }
    if (event.key === 'Escape' && !document.querySelector('dialog[open]')) {
      if (mobile.matches && document.body.dataset.navigator === 'open') { event.preventDefault(); navigator(false, true); }
      else if (narrow.matches && panels.open && el('cardInspector').contains(document.activeElement)) { event.preventDefault(); showInspector(false, true); save(); }
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f' && document.body.dataset.mode === 'workspace' && !document.querySelector('dialog[open]')) {
      event.preventDefault(); el('search').focus(); el('search').select();
    }
  });
})();
