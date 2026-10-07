/* Apply saved colors before CSS paints. Storage may be unavailable in a webview. */
(() => {
  let saved;
  try { saved = JSON.parse(localStorage.getItem('dit-appearance')); } catch {}
  const preferences = {
    theme: ['light', 'dark'].includes(saved?.theme) ? saved.theme : 'system',
    palette: typeof saved?.palette === 'string' && /^[a-z]{2,12}$/.test(saved.palette) ? saved.palette : 'espresso',
    crema: ['on', 'off'].includes(saved?.crema) ? saved.crema : 'auto',
  };
  const root = document.documentElement;
  if (preferences.theme !== 'system') root.dataset.theme = preferences.theme;
  root.dataset.palette = preferences.palette;
  root.dataset.crema = preferences.crema === 'off' ? 'off' : 'on';
  window.DataHandlerAppearance = preferences;
})();
