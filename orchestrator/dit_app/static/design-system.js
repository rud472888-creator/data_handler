import {
  palettes, setPalette, setTheme, applyCremaPreference, shouldReduceCrema,
} from './vendor/blurssism/utils.mjs';

const $ = id => document.getElementById(id);
const key = 'dit-appearance';
const defaults = {theme: 'system', palette: 'espresso', crema: 'auto'};
const themeNames = {system: '시스템', light: '라이트', dark: '다크'};

function normalize(value) {
  return {
    theme: ['system', 'light', 'dark'].includes(value?.theme) ? value.theme : defaults.theme,
    palette: palettes.some(p => p.id === value?.palette) ? value.palette : defaults.palette,
    crema: ['auto', 'on', 'off'].includes(value?.crema) ? value.crema : defaults.crema,
  };
}

let preferences = normalize(window.DataHandlerAppearance);
const paletteSelect = $('appearancePalette');
for (const [group, label] of [['caffeine', '카페인'], ['web', '기본 색상']]) {
  const options = document.createElement('optgroup');
  options.label = label;
  for (const palette of palettes.filter(p => p.group === group)) {
    const option = document.createElement('option');
    option.value = palette.id;
    option.textContent = palette.name;
    options.append(option);
  }
  paletteSelect.append(options);
}

function applyEffects() {
  const reduce = shouldReduceCrema() || preferences.crema === 'off';
  applyCremaPreference({
    ...(reduce ? {force: false} : {}),
    rich: preferences.crema === 'on' ? false : 'auto',
    pointerLight: false,
  });
}

function apply() {
  setTheme(preferences.theme);
  setPalette(preferences.palette);
  applyEffects();
  $('appearanceTheme').value = preferences.theme;
  paletteSelect.value = preferences.palette;
  $('appearanceCrema').value = preferences.crema;
  const palette = palettes.find(p => p.id === preferences.palette);
  $('appearanceSummary').textContent = `${palette.name} · ${themeNames[preferences.theme]}`;
}

$('appearanceButton').addEventListener('click', () => {
  $('appearanceStatus').textContent = '';
  $('appearanceDialog').showModal();
});
$('appearanceForm').addEventListener('change', () => {
  preferences = normalize({
    theme: $('appearanceTheme').value,
    palette: paletteSelect.value,
    crema: $('appearanceCrema').value,
  });
  apply();
  try {
    localStorage.setItem(key, JSON.stringify(preferences));
    $('appearanceStatus').textContent = '화면 설정을 저장했어요.';
  } catch {
    $('appearanceStatus').textContent = '이 창에 적용했어요. 설정을 저장할 수 없어 다음 실행에는 기본값을 사용해요.';
  }
});

window.addEventListener('storage', event => {
  if (event.key !== key) return;
  let value;
  try { value = JSON.parse(event.newValue); } catch {}
  preferences = normalize(value);
  apply();
});
window.matchMedia('(prefers-reduced-transparency: reduce)').addEventListener('change', applyEffects);
navigator.connection?.addEventListener('change', applyEffects);
apply();
