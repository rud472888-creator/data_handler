const preferences = window.DataHandlerAppearance || {theme: 'dark', density: 'standard'};
const systemTheme = matchMedia('(prefers-color-scheme: dark)');
const root = document.documentElement;
const theme = document.getElementById('appearanceTheme');
const density = document.getElementById('appearanceDensity');
const status = document.getElementById('appearanceStatus');

function apply(save = false) {
  const resolved = preferences.theme === 'system' ? (systemTheme.matches ? 'dark' : 'light') : preferences.theme;
  root.dataset.theme = resolved;
  root.dataset.density = preferences.density;
  theme.value = preferences.theme;
  density.value = preferences.density;
  window.webkit?.messageHandlers?.appearance?.postMessage({theme: preferences.theme});
  if (save) {
    try {
      localStorage.setItem('dit-workspace-appearance', JSON.stringify(preferences));
      status.textContent = '화면 설정을 저장했습니다.';
    } catch { status.textContent = '설정이 적용되었습니다. 이 환경에서는 저장할 수 없습니다.'; }
  }
}

theme.addEventListener('change', () => { preferences.theme = theme.value; apply(true); });
density.addEventListener('change', () => { preferences.density = density.value; apply(true); });
systemTheme.addEventListener('change', () => { if (preferences.theme === 'system') apply(); });
document.getElementById('appearanceButton').addEventListener('click', () => {
  status.textContent = '';
  document.getElementById('appearanceDialog').showModal();
});
apply();
