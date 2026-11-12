(() => {
  const root = document.getElementById('messagingRoot')
    || document.getElementById('chatApp')
    || document.getElementById('privateChat');
  if (!root || !root.dataset.presenceUrl) return;

  const csrf = document.querySelector(
    '#messagingCsrfForm [name="csrfmiddlewaretoken"], #chatForm [name="csrfmiddlewaretoken"]',
  )?.value || root.dataset.csrf || '';
  if (!csrf) return;

  const heartbeat = () => {
    fetch(root.dataset.presenceUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-CSRFToken': csrf,
        Accept: 'application/json',
      },
      keepalive: true,
    }).catch(() => {});
  };

  heartbeat();
  const timer = window.setInterval(heartbeat, 30000);
  window.addEventListener('pagehide', () => window.clearInterval(timer), { once: true });
})();
