#!/usr/bin/env node
/* Browser regression check. API fixtures never create a copy job or touch media. */
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const url = process.env.UI_QA_URL || 'http://127.0.0.1:8876';
const output = resolve(process.env.UI_QA_OUTPUT || '.pipeline/uiux-qa');
await mkdir(output, {recursive: true});
const browser = await chromium.launch({channel: 'chrome', headless: true});
const context = await browser.newContext({viewport: {width: 1440, height: 900}, colorScheme: 'light'});
const errors = [], external = [], checks = [];
const fixture = {projects: [], cards: [], runs: 0, failProjects: false};

async function attach(page) {
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!request.url().startsWith(url + '/')) external.push(request.url()); });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    let body = {}, status = 200;
    if (path === '/api/projects') {
      body = {projects: fixture.projects, runs: []};
      if (fixture.failProjects) { status = 503; body = {detail: 'UI 검증용 일시적 연결 오류'}; }
    } else if (path === '/api/library/projects' && request.method() === 'POST') {
      const project = {id: 'ui-qa-project', name: request.postDataJSON().name, replica_roots: []};
      fixture.projects.push(project); body = {project}; status = 201;
    } else if (/\/api\/library\/projects\/[^/]+\/cards$/.test(path)) body = {cards: fixture.cards};
    else if (path.endsWith('/remove')) {
      fixture.removed = fixture.projects.shift(); body = {removed: true};
    } else if (path.endsWith('/restore')) {
      fixture.projects.unshift(fixture.removed); body = {project: fixture.removed};
    } else if (path === '/api/disks') body = {disks: [{name: 'CAMERA_CARD', path: '/Volumes/CAMERA_CARD'}, {name: 'BACKUP_A', path: '/Volumes/BACKUP_A'}]};
    else if (path === '/api/sources') body = {sources: []};
    else if (path === '/api/destinations') body = {destinations: []};
    else if (path === '/api/roll-preview') {
      const data = request.postDataJSON();
      body = {roll: 'R#8', replica_destinations: data.replica_roots.map(root => root + '/야간 촬영/001_Footage/R#8')};
    } else if (path === '/api/runs') { fixture.runs++; status = 403; body = {detail: '실제 복제는 UI 검증에서 실행하지 않아요.'}; }
    else if (path === '/api/agent/session' || path === '/api/blackmagician/session') body = {token: 'ui-qa'};
    else if (path === '/api/agent/state') body = {connected: true, inference_connected: true, model_loaded: true, telegram_connected: false};
    else if (path === '/api/agent/conversations') body = {conversations: []};
    else if (path.startsWith('/api/blackmagician/projects/')) body = {connection: null, snapshot: null, live: {}, questions: [], confirmations: []};
    else if (/\/api\/library\/cards\/[^/]+\/reviews$/.test(path)) body = {agent_reviews: fixture.cards[0]?.agent_reviews || []};
    await route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
  });
}
function check(name, detail = true) { checks.push({name, detail}); console.log('PASS', name); }
async function screenshot(page, name, fullPage = false) { await page.screenshot({path: resolve(output, name + '.png'), fullPage}); }
async function noOverflow(page, label) {
  const geometry = await page.evaluate(() => ({width: innerWidth, body: document.body.scrollWidth, document: document.documentElement.scrollWidth}));
  assert.ok(geometry.body <= geometry.width + 1 && geometry.document <= geometry.width + 1, `${label}: ${JSON.stringify(geometry)}`);
}
async function settings(page) {
  await page.locator('#appearanceButton').click();
  await page.locator('#appearanceDialog').waitFor({state: 'visible'});
}
async function primaryCount(page) {
  return page.locator('button.primary:visible').count();
}
async function contrast(page, selector) {
  return page.locator(selector).first().evaluate(element => {
    const style = getComputedStyle(element);
    const luminance = color => {
      const rgb = color.match(/[\d.]+/g).slice(0, 3).map(v => Number(v) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
      return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
    };
    let background = style.backgroundColor, ancestor = element;
    while (background === 'rgba(0, 0, 0, 0)' || background === 'transparent') {
      ancestor = ancestor.parentElement; if (!ancestor) break;
      background = getComputedStyle(ancestor).backgroundColor;
    }
    const a = luminance(style.color), b = luminance(background);
    return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  });
}

try {
  const page = await context.newPage();
  await attach(page);
  await page.goto(url);
  await page.locator('[data-new-project]').waitFor();
  await page.locator('#appearanceDensity option').first().waitFor({state: 'attached'});
  assert.equal(await primaryCount(page), 1);
  await screenshot(page, 'empty-light');
  check('Empty library offers one primary action');

  await page.locator('[data-new-project]').click();
  await page.locator('#projectForm input[name="name"]').fill('야간 촬영');
  await page.locator('#projectForm button[type="submit"]').click();
  await page.locator('#importCard').waitFor({state: 'visible'});
  assert.equal(await primaryCount(page), 1);
  check('Project creation reaches the import empty state');

  const phases = ['reported', 'verified', 'reporting', 'copying', 'waiting', 'review', 'failed'];
  fixture.cards = phases.map((phase, index) => ({
    run_id: 'ui-qa-card-' + index, roll: 'R#' + (index + 1), shoot_date: index > 3 ? '2026-10-06' : '2026-10-07',
    camera_unit: index % 2 ? 'B' : 'A', phase, verified: index < 3, source_path: '/Volumes/CAMERA_CARD/' + (index + 1),
    file_count: index < 3 ? 48 + index : null, destinations: ['/Volumes/BACKUP_A/야간 촬영/001_Footage/R#' + (index + 1)], artifacts: [], updated_at: '2026-10-07T05:00:00Z', agent_reviews: index ? [] : [
      {phase: 'copy', title: '복제 검토', state: 'done', status: 'verified', summary: '원본과 두 백업 경로의 체크섬이 일치해요.', finding_count: 0},
      {phase: 'report', title: '리포트 검토', state: 'done', status: 'verified', summary: '완료 기록의 카드 정보와 보고서가 일치해요.', finding_count: 0},
    ],
  }));
  await page.locator('#refresh').click();
  await page.locator('[data-card="ui-qa-card-0"]').first().waitFor();
  await page.locator('[data-card="ui-qa-card-0"]').first().click();
  assert.equal(await page.locator('[data-card="ui-qa-card-0"]').first().getAttribute('aria-pressed'), 'true');
  assert.equal(await page.evaluate(() => document.activeElement.dataset.card), 'ui-qa-card-0');
  assert.equal(await primaryCount(page), 1);
  await page.evaluate(() => document.fonts.ready);
  assert.ok(await page.evaluate(() => document.fonts.check('400 14px "Pretendard Variable"', '카드')));
  await screenshot(page, 'workspace-light');
  const header = await page.locator('.library thead').boundingBox();
  const content = await page.locator('#content').boundingBox();
  assert.ok(header.y >= content.y - 1);
  check('Library, selection, review and seven operational states render with local fonts');

  await settings(page);
  await page.locator('#appearanceTheme').selectOption('system');
  await page.emulateMedia({colorScheme: 'dark', reducedMotion: 'reduce'});
  assert.equal(await page.locator('#appearanceForm button.primary').evaluate(el => getComputedStyle(el).transitionDuration), '0s');
  const darkBackground = await page.locator('body').evaluate(el => getComputedStyle(el).getPropertyValue('--paper').trim());
  await page.emulateMedia({colorScheme: 'light', reducedMotion: 'no-preference'});
  assert.notEqual(await page.locator('body').evaluate(el => getComputedStyle(el).getPropertyValue('--paper').trim()), darkBackground);
  check('System theme follows OS changes and reduced motion removes transitions');
  let minimum = Infinity;
  for (const theme of ['light', 'dark']) {
    await page.locator('#appearanceTheme').selectOption(theme);
    const ratio = await contrast(page, '#appearanceForm button.primary');
    minimum = Math.min(minimum, ratio);
    assert.ok(ratio >= 4.5, `${theme}: ${ratio}`);
    for (const state of ['good', 'warning', 'failed', 'active']) assert.ok(await contrast(page, `.status.${state}`) >= 4.5, `${theme}/${state}`);
  }
  await page.locator('#appearanceDensity').selectOption('compact');
  await page.locator('#appearanceCrema').selectOption('off');
  await page.locator('#appearanceForm button[type="submit"]').click();
  assert.equal(await page.locator('#content tbody tr').first().evaluate(el => el.getBoundingClientRect().height), 32);
  assert.equal(await page.locator('.mode-switch').evaluate(el => getComputedStyle(el).backdropFilter), 'none');
  await page.reload(); await page.locator('table').waitFor();
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  assert.equal(await page.locator('html').getAttribute('data-density'), 'compact');
  assert.equal(await page.locator('html').getAttribute('data-crema'), 'off');
  for (const surface of ['.mode-switch', '.library-toolbar .tabs']) assert.equal(await page.locator(surface).evaluate(el => getComputedStyle(el).backdropFilter), 'none');
  await settings(page);
  await page.locator('#appearanceCrema').selectOption('auto');
  await page.locator('#appearanceForm button[type="submit"]').click();
  assert.equal(await page.locator('html').getAttribute('data-palette'), 'graphite');
  await page.locator('#content [data-card="ui-qa-card-0"]').click();
  await page.locator('#content [data-card="ui-qa-card-0"]').press('ArrowUp');
  assert.equal(await page.evaluate(() => document.activeElement.dataset.card), 'ui-qa-card-1');
  assert.ok((await page.locator('#cardDetails').textContent()).includes('R#2'));
  await page.locator('#detailsTab').press('ArrowRight');
  assert.equal(await page.locator('#reviewTab').getAttribute('aria-selected'), 'true');
  await page.locator('#reviewTab').press('ArrowLeft');
  const oldWidth = Number(await page.locator('#navigatorSplitter').getAttribute('aria-valuenow'));
  await page.locator('#navigatorSplitter').press('ArrowRight');
  assert.equal(Number(await page.locator('#navigatorSplitter').getAttribute('aria-valuenow')), oldWidth + 10);
  check('Keyboard selection, inspector tabs, splitters and compact rows stay usable');
  await screenshot(page, 'workspace-dark');
  check('Achromatic themes keep actions and status text at 4.5:1', {minimumActionContrast: minimum});
  check('Saved theme, density and effect settings survive reload');

  await settings(page);
  await page.locator('#appearanceTheme').selectOption('light');
  await screenshot(page, 'appearance');
  assert.equal(await page.locator('.bl-crema:visible, .bl-crema-thick:visible').count(), 3);
  assert.equal(await page.locator('.library').evaluate(el => getComputedStyle(el).backdropFilter), 'none');
  assert.equal(await page.locator('#cardInspector').evaluate(el => getComputedStyle(el).backdropFilter), 'none');
  await page.keyboard.press('Escape');
  await page.locator('#importCard').click();
  await page.locator('#importForm input[name="source_path"]').fill('/Volumes/CAMERA_CARD');
  await page.locator('#replicaPaths input').first().fill('/Volumes/BACKUP_0');
  for (let i = 1; i < 100; i++) {
    await page.locator('#addReplica').click();
    await page.locator('#replicaPaths input').last().fill('/Volumes/BACKUP_' + i);
  }
  await page.locator('#importSubmit').click();
  await page.locator('#importReview').waitFor({state: 'visible'});
  assert.ok((await page.locator('#importReview').textContent()).includes('100. /Volumes/BACKUP_99/야간 촬영/001_Footage/R#8'));
  await page.locator('#importReview').evaluate(el => { el.scrollTop = el.scrollHeight; });
  await noOverflow(page, '100-path review');
  const footer = await page.locator('#importSubmit').boundingBox();
  assert.ok(footer.y + footer.height <= 900);
  await screenshot(page, 'import-review-100');
  await page.locator('#importBack').click();
  assert.equal(await page.locator('#replicaPaths input').count(), 100);
  await page.keyboard.press('Escape');
  assert.equal(fixture.runs, 0);
  check('100 destinations remain scrollable, editable and require explicit start');

  for (const width of [320, 390, 600, 767, 768, 1000, 1120, 1440]) {
    await page.setViewportSize({width, height: 900});
    await noOverflow(page, 'workspace ' + width);
  }
  await page.locator('#agentMode').click();
  await page.locator('.agent-welcome').waitFor();
  await noOverflow(page, 'agent desktop');
  await screenshot(page, 'agent-desktop');
  await page.locator('#blackmagicianLiveMode').click();
  await page.locator('#shootingPanel').waitFor({state: 'visible'});
  await noOverflow(page, 'shooting desktop');
  await screenshot(page, 'shooting-desktop');
  await page.locator('#workspaceMode').click();
  check('Workspace and modes fit responsive breakpoint boundaries');

  fixture.failProjects = true;
  await page.locator('#refresh').click();
  await page.locator('#error').waitFor({state: 'visible'});
  await screenshot(page, 'recoverable-error');
  fixture.failProjects = false;
  await page.locator('#refresh').click();
  await page.locator('#error').waitFor({state: 'hidden'});
  check('A failed refresh preserves the library and recovers');

  await page.locator('#removeProject').click();
  await page.locator('#removeForm button[type="submit"]').click();
  await page.locator('#undoRemove').waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem('dit-project')), null);
  await page.locator('#undoRemove').click();
  await page.locator('#projectTitle').filter({hasText: '야간 촬영'}).waitFor();
  check('Project removal and undo do not recurse in local storage');

  const mobileContext = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true, colorScheme: 'light'});
  const mobile = await mobileContext.newPage();
  await attach(mobile); await mobile.goto(url); await mobile.locator('table').waitFor();
  await noOverflow(mobile, 'touch workspace');
  await screenshot(mobile, 'mobile-workspace', true);
  assert.ok((await mobile.locator('#workspaceMode').boundingBox()).height >= 44);
  await mobile.locator('#agentMode').click(); await mobile.locator('.agent-welcome').waitFor();
  await noOverflow(mobile, 'touch agent'); await screenshot(mobile, 'mobile-agent');
  await mobile.locator('#appearanceButton').click();
  await noOverflow(mobile, 'touch settings');
  const sheet = await mobile.locator('#appearanceDialog').boundingBox();
  assert.ok(sheet.height <= 844 * .9 + 1);
  await screenshot(mobile, 'mobile-settings');
  await mobile.keyboard.press('Escape'); await mobile.locator('#workspaceMode').click();
  await mobile.locator('#importCard').click();
  await noOverflow(mobile, 'touch import');
  await screenshot(mobile, 'mobile-import');
  await mobileContext.close();
  check('Touch navigation, composer and sheets stay reachable');

  const restricted = await context.newPage();
  await restricted.addInitScript(() => {
    for (const method of ['getItem', 'setItem', 'removeItem']) Storage.prototype[method] = () => { throw new DOMException('Storage unavailable', 'SecurityError'); };
    Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 2});
  });
  await attach(restricted); await restricted.goto(url); await restricted.locator('table').waitFor();
  assert.equal(await restricted.locator('html').getAttribute('data-crema'), 'off');
  await settings(restricted); await restricted.locator('#appearanceTheme').selectOption('dark');
  assert.ok((await restricted.locator('#appearanceStatus').textContent()).includes('저장할 수 없'));
  await restricted.keyboard.press('Escape'); await restricted.locator('#agentMode').click();
  await restricted.locator('.agent-welcome').waitFor();
  await restricted.close();
  check('Unavailable storage and low-end hardware leave the app usable');

  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  assert.equal(fixture.runs, 0);
  check('No script errors, external font requests or real copy jobs');
  await writeFile(resolve(output, 'result.json'), JSON.stringify({status: 'passed', checks, errors, externalRequests: external, productionRuns: fixture.runs}, null, 2) + '\n');
} catch (error) {
  await writeFile(resolve(output, 'result.json'), JSON.stringify({status: 'failed', checks, error: error.stack, errors, externalRequests: external, productionRuns: fixture.runs}, null, 2) + '\n');
  throw error;
} finally { await browser.close(); }
