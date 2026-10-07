/* Apply saved workspace preferences before first paint, including in WKWebView. */
(() => {
  let saved;
  try { saved = JSON.parse(localStorage.getItem('dit-workspace-appearance')); } catch {}
  const preferences = {
    theme: ['dark', 'light', 'system'].includes(saved?.theme) ? saved.theme : 'dark',
    density: saved?.density === 'compact' ? 'compact' : 'standard',
  };
  const resolved = preferences.theme === 'system'
    ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : preferences.theme;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.density = preferences.density;
  window.DataHandlerAppearance = preferences;
})();
