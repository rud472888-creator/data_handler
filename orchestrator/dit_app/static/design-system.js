import {applyCremaPreference, setPalette, setTheme} from './vendor/blurssism/utils.mjs';

const preferences = window.DataHandlerAppearance || {theme: 'dark', density: 'standard', crema: 'auto'};
const systemTheme = matchMedia('(prefers-color-scheme: dark)');
const reducedTransparency = matchMedia('(prefers-reduced-transparency: reduce)');
const root = document.documentElement;
const theme = document.getElementById('appearanceTheme');
const density = document.getElementById('appearanceDensity');
const crema = document.getElementById('appearanceCrema');
const status = document.getElementById('appearanceStatus');

function apply(save = false) {
  const resolved = preferences.theme === 'system' ? (systemTheme.matches ? 'dark' : 'light') : preferences.theme;
  setTheme(resolved);
  setPalette('graphite');
  root.dataset.density = preferences.density;
  // Rich/pointer effects add little to short operational labels. Keep two
  // restrained surfaces and let upstream hardware/accessibility checks win.
  applyCremaPreference(preferences.crema === 'off'
    ? {force: false, rich: false, pointerLight: false}
    : {rich: false, pointerLight: false});
  theme.value = preferences.theme;
  density.value = preferences.density;
  crema.value = preferences.crema;
  window.webkit?.messageHandlers?.appearance?.postMessage({theme: preferences.theme});
  if (save) {
    try {
      localStorage.setItem('dit-workspace-appearance', JSON.stringify(preferences));
      status.textContent = '화면 설정을 저장했어요.';
    } catch { status.textContent = '설정을 적용했어요. 이 환경에서는 저장할 수 없어요.'; }
  }
}

theme.addEventListener('change', () => { preferences.theme = theme.value; apply(true); });
density.addEventListener('change', () => { preferences.density = density.value; apply(true); });
crema.addEventListener('change', () => { preferences.crema = crema.value; apply(true); });
systemTheme.addEventListener('change', () => { if (preferences.theme === 'system') apply(); });
reducedTransparency.addEventListener('change', () => apply());
navigator.connection?.addEventListener('change', () => apply());
document.getElementById('appearanceButton').addEventListener('click', () => {
  status.textContent = '';
  document.getElementById('appearanceDialog').showModal();
});
apply();
