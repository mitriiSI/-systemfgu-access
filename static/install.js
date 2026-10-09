// No private API responses or uploaded files are stored by the service worker.
if ('serviceWorker' in navigator && !window.Telegram?.WebApp?.initData) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
