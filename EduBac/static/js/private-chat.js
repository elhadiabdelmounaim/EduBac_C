(() => {
  const root = document.getElementById('privateChat');
  if (!root) return;

  const messagesEl = document.getElementById('privateChatMessages');
  const statusEl = document.getElementById('privateChatStatus');
  const errorEl = document.getElementById('privateChatError');
  const form = document.getElementById('privateChatForm');
  const input = document.getElementById('privateChatInput');
  const sendButton = document.getElementById('privateChatSend');
  const currentUser = String(root.dataset.currentUser);
  const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]')?.value || root.dataset.csrf;
  let lastId = 0;
  let polling = false;

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function appendMessage(message) {
    const row = document.createElement('div');
    row.className = `d-flex mb-3 ${String(message.sender_id) === currentUser ? 'justify-content-end' : 'justify-content-start'}`;

    const bubble = document.createElement('div');
    bubble.className = 'rounded-3 px-3 py-2 shadow-sm';
    bubble.style.maxWidth = 'min(82%, 620px)';
    bubble.style.background = String(message.sender_id) === currentUser ? '#d8f0ed' : '#ffffff';

    const sender = document.createElement('div');
    sender.className = 'small fw-semibold mb-1';
    sender.textContent = String(message.sender_id) === currentUser ? 'Vous' : message.sender_name;

    const body = document.createElement('div');
    body.style.whiteSpace = 'pre-wrap';
    body.style.overflowWrap = 'anywhere';
    body.textContent = message.body;

    const time = document.createElement('div');
    time.className = 'small text-muted text-end mt-1';
    time.textContent = message.time_display;

    bubble.append(sender, body, time);
    row.append(bubble);
    messagesEl.append(row);
    lastId = Math.max(lastId, Number(message.id) || 0);
  }

  async function loadMessages(initial = false) {
    if (polling) return;
    polling = true;
    try {
      const url = new URL(root.dataset.messagesUrl, window.location.origin);
      if (!initial && lastId) url.searchParams.set('after_id', String(lastId));
      const response = await fetch(url, { headers: { Accept: 'application/json' } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Impossible de charger les messages.');

      if (initial) {
        statusEl.remove();
        data.messages.forEach(appendMessage);
        if (!data.messages.length) {
          const empty = document.createElement('p');
          empty.className = 'text-center text-muted py-3';
          empty.textContent = 'Votre conversation privée avec le professeur commence ici.';
          messagesEl.append(empty);
        }
        messagesEl.scrollTop = messagesEl.scrollHeight;
      } else {
        if (data.messages.length) {
          const empty = messagesEl.querySelector('p.text-center');
          if (empty) empty.remove();
        }
        data.messages.forEach(appendMessage);
        if (data.messages.length) messagesEl.scrollTop = messagesEl.scrollHeight;
      }
      showError('');
    } catch (error) {
      showError(error.message || 'Erreur de connexion. Réessayez.');
    } finally {
      polling = false;
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const body = input.value.trim();
    if (!body) return;

    sendButton.disabled = true;
    showError('');
    try {
      const response = await fetch(root.dataset.sendUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
          Accept: 'application/json',
        },
        body: JSON.stringify({ body }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Le message n’a pas pu être envoyé.');
      const empty = messagesEl.querySelector('p.text-center');
      if (empty) empty.remove();
      appendMessage(data.message);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      input.value = '';
      input.focus();
    } catch (error) {
      showError(error.message || 'Erreur de connexion. Réessayez.');
    } finally {
      sendButton.disabled = false;
    }
  });

  loadMessages(true);
  window.setInterval(() => loadMessages(false), 4000);
})();
