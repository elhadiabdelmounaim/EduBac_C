(() => {
  const root = document.getElementById('privateChat');
  if (!root) return;

  const messagesEl = document.getElementById('privateChatMessages');
  const statusEl = document.getElementById('privateChatStatus');
  const errorEl = document.getElementById('privateChatError');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatInput');
  const sendButton = form.querySelector('.chat-send-btn');
  const currentUser = String(root.dataset.currentUser);
  const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
  const fileInputs = [
    document.getElementById('privateFileInput'),
    document.getElementById('privateImageInput'),
    document.getElementById('privateAudioInput'),
  ];
  const filePreview = document.getElementById('privateFilePreview');
  const filePreviewName = document.getElementById('privateFilePreviewName');
  const emojiPanel = document.getElementById('privateEmojiPanel');
  const emojiGrid = document.getElementById('privateEmojiGrid');
  let lastId = 0;
  let polling = false;
  let selectedFile = null;
  let previewUrl = '';
  let sending = false;

  const emojis = [
    '😀', '😃', '😄', '😁', '😅', '😂', '😊', '😉', '😍', '🥰', '😎', '🤔',
    '👍', '👎', '👏', '🙏', '❤️', '💙', '🔥', '⭐', '🎉', '💯', '📚', '✏️',
  ];

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function scrollBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  async function readJson(response, fallbackMessage) {
    const contentType = (response.headers.get('content-type') || '').toLowerCase();
    if (!contentType.includes('application/json')) {
      if (response.redirected || response.status === 401) {
        throw new Error('Votre session a expiré. Reconnectez-vous, puis actualisez cette page.');
      }
      throw new Error('Réponse inattendue du serveur. Actualisez la conversation et réessayez.');
    }
    let data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error('Réponse invalide du serveur. Actualisez la conversation et réessayez.');
    }
    if (!response.ok) throw new Error(data.error || fallbackMessage);
    return data;
  }

  function makeAttachment(message) {
    if (!message.attachment_url) return null;
    if (message.is_image) {
      const link = document.createElement('a');
      link.href = message.attachment_url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.className = 'chat-att-img-link';
      const image = document.createElement('img');
      image.src = message.attachment_url;
      image.alt = message.attachment_name || 'Image jointe';
      image.loading = 'lazy';
      image.className = 'private-chat-image';
      link.append(image);
      return link;
    }
    if (message.is_voice) {
      const audio = document.createElement('audio');
      audio.src = message.attachment_url;
      audio.controls = true;
      audio.preload = 'metadata';
      audio.className = 'chat-voice-player private-chat-audio';
      audio.setAttribute('aria-label', 'Message audio');
      return audio;
    }
    const link = document.createElement('a');
    link.href = message.attachment_url;
    link.className = 'chat-att-file';
    link.textContent = `📎 ${message.attachment_name || 'Télécharger le fichier'}`;
    return link;
  }

  function appendMessage(message) {
    if (!message || !message.id || document.getElementById(`private-message-${message.id}`)) return;
    const mine = String(message.sender_id) === currentUser;
    const row = document.createElement('div');
    row.className = `chat-bubble-row ${mine ? 'mine' : 'theirs'}`;
    row.id = `private-message-${message.id}`;
    row.dataset.messageId = String(message.id);

    if (!mine) {
      const sender = document.createElement('div');
      sender.className = 'chat-sender-name';
      sender.textContent = message.sender_name || 'Participant';
      row.append(sender);
    }

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    const attachment = makeAttachment(message);
    if (attachment) bubble.append(attachment);

    if (message.body) {
      const body = document.createElement('div');
      body.className = attachment ? 'chat-att-caption' : '';
      body.textContent = message.body;
      bubble.append(body);
    }

    const time = document.createElement('div');
    time.className = 'chat-bubble-time';
    time.textContent = message.time_display;
    if (mine) {
      const receipt = document.createElement('span');
      receipt.className = `chat-ticks private-chat-read${message.is_read ? ' is-read' : ''}`;
      receipt.dataset.readMessageId = String(message.id);
      receipt.textContent = message.is_read ? '✓✓ Lu' : '✓ Envoyé';
      receipt.title = message.is_read ? 'Le destinataire a lu ce message' : 'Message envoyé';
      receipt.setAttribute('aria-label', receipt.title);
      time.append(receipt);
    }

    bubble.append(time);
    row.append(bubble);
    messagesEl.append(row);
    lastId = Math.max(lastId, Number(message.id) || 0);
    if (window.EduBacVoice) window.EduBacVoice.enhance(row);
  }

  function updateReadReceipts(ids) {
    const readIds = new Set((ids || []).map(String));
    readIds.forEach((id) => {
      const receipt = document.querySelector(`[data-read-message-id="${id}"]`);
      if (!receipt) return;
      receipt.textContent = '✓✓ Lu';
      receipt.title = 'Le destinataire a lu ce message';
      receipt.setAttribute('aria-label', receipt.title);
      receipt.classList.add('is-read');
    });
  }

  async function loadMessages(initial = false) {
    if (polling) return;
    polling = true;
    try {
      const url = new URL(root.dataset.messagesUrl, window.location.origin);
      if (!initial && lastId) url.searchParams.set('after_id', String(lastId));
      const response = await fetch(url, { headers: { Accept: 'application/json' } });
      const data = await readJson(response, 'Impossible de charger les messages.');

      if (initial) {
        statusEl.remove();
        (data.messages || []).forEach(appendMessage);
        if (!data.messages || !data.messages.length) {
          const empty = document.createElement('p');
          empty.className = 'text-center text-muted py-3';
          empty.textContent = 'Votre conversation privée avec le professeur commence ici.';
          messagesEl.append(empty);
        }
      } else {
        if (data.messages && data.messages.length) {
          const empty = messagesEl.querySelector('p.text-center');
          if (empty) empty.remove();
          data.messages.forEach(appendMessage);
        }
      }
      updateReadReceipts(data.read_ids);
      if (initial || (data.messages && data.messages.length)) scrollBottom();
      showError('');
    } catch (error) {
      showError(error.message || 'Erreur de connexion. Réessayez.');
    } finally {
      polling = false;
    }
  }

  function clearFile() {
    selectedFile = null;
    fileInputs.forEach((fileInput) => { if (fileInput) fileInput.value = ''; });
    filePreview.hidden = true;
    filePreviewName.textContent = '';
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = '';
    const image = filePreview.querySelector('img');
    if (image) image.remove();
  }

  function chooseFile(file) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      showError('La pièce jointe dépasse la limite de 10 Mo.');
      fileInputs.forEach((fileInput) => { if (fileInput) fileInput.value = ''; });
      return;
    }
    clearFile();
    selectedFile = file;
    filePreviewName.textContent = file.name;
    filePreview.hidden = false;
    if (file.type.startsWith('image/')) {
      previewUrl = URL.createObjectURL(file);
      const image = document.createElement('img');
      image.src = previewUrl;
      image.alt = 'Aperçu de l’image à envoyer';
      image.style.maxWidth = '52px';
      image.style.maxHeight = '52px';
      image.style.objectFit = 'cover';
      image.style.borderRadius = '6px';
      filePreview.prepend(image);
    }
    showError('');
  }

  async function sendMessage(extraFile = null, isVoice = false) {
    if (sending) return false;
    const body = isVoice ? '' : input.value.trim();
    const file = extraFile || selectedFile;
    if (!body && !file) return false;

    sending = true;
    sendButton.disabled = true;
    showError('');
    try {
      let response;
      if (file) {
        const formData = new FormData();
        formData.append('body', body);
        formData.append('attachment', file, file.name || (isVoice ? 'message-vocal.webm' : 'piece-jointe'));
        if (isVoice) formData.append('is_voice', '1');
        response = await fetch(root.dataset.sendUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken, Accept: 'application/json' },
          body: formData,
        });
      } else {
        response = await fetch(root.dataset.sendUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            Accept: 'application/json',
          },
          body: JSON.stringify({ body }),
        });
      }
      const data = await readJson(response, 'Le message n’a pas pu être envoyé.');
      const empty = messagesEl.querySelector('p.text-center');
      if (empty) empty.remove();
      appendMessage(data.message);
      scrollBottom();
      input.value = '';
      input.style.height = 'auto';
      if (file) clearFile();
      return true;
    } catch (error) {
      showError(error.message || 'Erreur de connexion. Réessayez.');
      return false;
    } finally {
      sending = false;
      sendButton.disabled = false;
      if (!isVoice) input.focus();
    }
  }

  function openFilePicker(inputId) {
    const picker = document.getElementById(inputId);
    if (picker) picker.click();
  }

  fileInputs.forEach((fileInput) => {
    if (fileInput) {
      fileInput.addEventListener('change', () => chooseFile(fileInput.files?.[0]));
    }
  });
  document.getElementById('privateFileBtn').addEventListener('click', () => openFilePicker('privateFileInput'));
  document.getElementById('privateImageBtn').addEventListener('click', () => openFilePicker('privateImageInput'));
  document.getElementById('privateAudioBtn').addEventListener('click', () => openFilePicker('privateAudioInput'));
  document.getElementById('privateFileClear').addEventListener('click', clearFile);

  document.getElementById('privateEmojiBtn').addEventListener('click', () => {
    if (emojiGrid.childElementCount === 0) {
      emojis.forEach((emoji) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'chat-emoji-item';
        button.textContent = emoji;
        button.addEventListener('click', () => {
          const start = input.selectionStart ?? input.value.length;
          const end = input.selectionEnd ?? start;
          input.value = input.value.slice(0, start) + emoji + input.value.slice(end);
          input.focus();
          input.setSelectionRange(start + emoji.length, start + emoji.length);
        });
        emojiGrid.append(button);
      });
    }
    emojiPanel.hidden = !emojiPanel.hidden;
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    sendMessage();
  });

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  });

  document.addEventListener('edubac:voice-send', (event) => {
    event.preventDefault();
    const detail = event.detail || {};
    if (!detail.file) {
      if (detail.done) detail.done(false);
      return;
    }
    sendMessage(detail.file, true).then((success) => {
      if (detail.done) detail.done(success);
    });
  });

  loadMessages(true);
  const timer = window.setInterval(() => loadMessages(false), 3000);
  window.addEventListener('pagehide', () => window.clearInterval(timer), { once: true });
})();
