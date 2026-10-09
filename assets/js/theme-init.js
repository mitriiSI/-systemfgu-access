(() => {
  let theme = 'dark';
  try {
    const saved = localStorage.getItem('systemafgu-theme');
    if (['light', 'dark'].includes(saved)) theme = saved;
  } catch { /* The interface also works when browser storage is unavailable. */ }
  document.documentElement.dataset.fguTheme = theme;
  document.documentElement.style.colorScheme = theme;
  document.documentElement.style.backgroundColor = theme === 'dark' ? '#080808' : '#f2f2f2';
})();
