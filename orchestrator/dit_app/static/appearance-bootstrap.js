/* Apply saved workspace preferences before first paint, including in WKWebView. */
(() => {
  let saved;
  try { saved = JSON.parse(localStorage.getItem('dit-workspace-appearance')); } catch {}
  const preferences = {
    theme: ['dark', 'light', 'system'].includes(saved?.theme) ? saved.theme : 'dark',
    density: saved?.density === 'compact' ? 'compact' : 'standard',
    crema: saved?.crema === 'off' ? 'off' : 'auto',
  };
  const resolved = preferences.theme === 'system'
    ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : preferences.theme;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.density = preferences.density;
  // Stay opaque until the device-aware 1.5 helper resolves the material.
  document.documentElement.dataset.crema = 'off';
  window.DataHandlerAppearance = preferences;
})();
