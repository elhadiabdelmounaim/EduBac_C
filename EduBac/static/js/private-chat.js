/**
 * Conversations privées (consultation professeur ↔ élève et messages directs).
 */
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
    document.getElementById('privateCameraInput'),
    document.getElementById('privateAudioInput'),
  ];
  const filePreview = document.getElementById('privateFilePreview');
  const filePreviewName = document.getElementById('privateFilePreviewName');
  const emojiPanel = document.getElementById('privateEmojiPanel');
  const emojiGrid = document.getElementById('privateEmojiGrid');
  const attachToggle = document.getElementById('privateAttachToggle');
  const attachMenu = document.getElementById('privateAttachMenu');
  const Chat = window.EduBacChat;
  const messageKind = root.dataset.messageKind || 'consultation';
  const contextSelect = document.getElementById('privateContextSelect');
  const aiDraftButton = document.getElementById('privateAiDraftBtn');
  const blockButton = document.getElementById('privateBlockBtn');
  const messagesById = new Map();
  const scroll = Chat.scroller(messagesEl, document.getElementById('chatJumpBtn'));
  let serverTime = '';
  let lastId = 0;
  let polling = false;
  let selectedFile = null;
  let previewUrl = '';
  let sending = false;
  const compose = Chat.composer(form, input, () => !!selectedFile);

  const emojis = [
    '😀', '😃', '😄', '😁', '😅', '😂', '😊', '😉', '😍', '🥰', '😎', '🤔',
    '👍', '👎', '👏', '🙏', '❤️', '💙', '🔥', '⭐', '🎉', '💯', '📚', '✏️',
  ];

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function icon(name) {
    const i = el('i', `bi ${name}`);
    i.setAttribute('aria-hidden', 'true');
    return i;
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
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
      const link = el('a', 'chat-att-img-link');
      link.href = message.attachment_url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      const image = el('img', 'chat-att-img');
      image.src = message.attachment_url;
      image.alt = message.attachment_name || 'Image jointe';
      image.loading = 'lazy';
      link.append(image);
      return link;
    }
    if (message.is_voice) {
      const audio = el('audio', 'chat-voice-player');
      audio.src = message.attachment_url;
      audio.controls = true;
      audio.preload = 'none';
      audio.setAttribute('aria-label', 'Message audio');
      return audio;
    }
    const link = el('a', 'chat-att-file');
    link.href = message.attachment_url;
    const badge = el('span', 'chat-att-file-icon');
    badge.append(icon('bi-file-earmark-text'));
    const text = el('span', 'chat-att-file-text');
    text.append(
      el('span', 'chat-att-file-name', message.attachment_name || 'Télécharger le fichier'),
      el('span', 'chat-att-file-hint', 'Télécharger'),
    );
    link.append(badge, text, icon('bi-download'));
    return link;
  }

  function actionButton(cls, iconName, title, handler) {
    const button = el('button', cls);
    button.type = 'button';
    button.title = title;
    button.setAttribute('aria-label', title);
    button.append(icon(iconName));
    button.addEventListener('click', handler);
    return button;
  }

  function contextCard(context) {
    const card = el('a', 'chat-context-card');
    card.href = context.url;
    const label = el('strong');
    label.append(icon(context.kind === 'question' ? 'bi-question-circle-fill' : 'bi-journal-bookmark-fill'), ` ${context.label}`);
    card.append(label);
    if (context.text) card.append(el('span', '', context.text));
    return card;
  }

  function onUpdated(updated) {
    if (updated) appendMessage(updated);
  }

  function showActionError(error) {
    showError(error.message || 'Action impossible.');
  }

  function appendMessage(message, animate = false) {
    if (!message || !message.id) return;
    const existing = document.getElementById(`private-message-${message.id}`);
    messagesById.set(message.id, message);
    const mine = String(message.sender_id) === currentUser;
    message.mine = mine;
    const row = el('div', `chat-bubble-row ${mine ? 'mine' : 'theirs'}`);
    if (message.is_deleted) row.classList.add('is-deleted');
    if (message.is_voice && !message.is_deleted) row.classList.add('is-voice');
    row.id = `private-message-${message.id}`;
    row.dataset.messageId = String(message.id);

    const stack = el('div', 'chat-bubble-stack');
    const bubble = el('div', 'chat-bubble');
    if (message.is_deleted) {
      const deleted = el('em', 'chat-deleted-text');
      deleted.append(icon('bi-slash-circle'), ' ', message.deleted_by_moderator
        ? 'Message supprimé par la modération'
        : 'Message supprimé');
      bubble.append(deleted);
    } else {
      if (message.context) bubble.append(contextCard(message.context));
      const attachment = makeAttachment(message);
      if (attachment) bubble.append(attachment);
      if (message.body) {
        const body = el('div', `chat-message-text${attachment ? ' chat-att-caption' : ''}`);
        Chat.renderText(body, message.body);
        bubble.append(body);
      }
    }

    const meta = el('span', 'chat-bubble-meta');
    if (message.is_edited && !message.is_deleted) meta.append(el('span', 'chat-edited', 'modifié'));
    meta.append(el('time', 'chat-bubble-time', Chat.timeLabel(message.created_at, message.time_display)));
    if (mine && !message.is_deleted) {
      const receipt = Chat.receipt(message.is_read ? 'read' : 'sent');
      receipt.classList.add('private-chat-read');
      receipt.dataset.readMessageId = String(message.id);
      meta.append(receipt);
    }
    bubble.append(meta);
    stack.append(bubble);
    const chips = Chat.reactionChips(messageKind, message, onUpdated, true);
    if (chips) stack.append(chips);

    if (!message.is_deleted) {
      const actions = el('div', 'chat-msg-actions');
      actions.append(Chat.reactionButton(messageKind, message, onUpdated));
      if (Chat.canEdit(message, currentUser)) {
        actions.append(actionButton('chat-act-edit', 'bi-pencil', 'Modifier', () => {
          Chat.editMessage(messageKind, message).then(onUpdated).catch(showActionError);
        }));
      }
      if (mine) {
        actions.append(actionButton('chat-act-delete', 'bi-trash', 'Supprimer', () => {
          Chat.deleteMessage(messageKind, message, false).then(onUpdated).catch(showActionError);
        }));
      } else {
        actions.append(actionButton('chat-act-report', 'bi-flag', 'Signaler', () => {
          Chat.reportMessage(messageKind, message);
        }));
      }
      if (actions.childElementCount) stack.append(actions);
    }
    row.append(stack);

    Chat.placeMessage(messagesEl, row, message, existing, animate && !existing);
    lastId = Math.max(lastId, Number(message.id) || 0);
    if (window.EduBacVoice) window.EduBacVoice.enhance(row);
    const mathTarget = bubble.querySelector('.chat-message-text');
    if (mathTarget) Chat.renderMath(mathTarget);
  }

  function updateReadReceipts(ids) {
    (ids || []).map(String).forEach((id) => {
      const receipt = messagesEl.querySelector(`[data-read-message-id="${id}"]`);
      if (!receipt || receipt.classList.contains('is-read')) return;
      const fresh = Chat.receipt('read');
      fresh.classList.add('private-chat-read');
      fresh.dataset.readMessageId = id;
      receipt.replaceWith(fresh);
      const known = messagesById.get(Number(id));
      if (known) known.is_read = true;
    });
  }

  function emptyNote() {
    return el('div', 'chat-messages-status', root.dataset.conversationKind === 'direct'
      ? 'Cette conversation privée commence ici.'
      : 'Votre conversation privée avec le professeur commence ici.');
  }

  function clearEmptyNote() {
    messagesEl.querySelector(':scope > .chat-messages-status')?.remove();
  }

  async function loadMessages(initial = false) {
    if (polling) return;
    polling = true;
    try {
      const url = new URL(root.dataset.messagesUrl, window.location.origin);
      if (!initial && lastId) {
        url.searchParams.set('after_id', String(lastId));
        if (serverTime) url.searchParams.set('since', serverTime);
      }
      const response = await fetch(url, { headers: { Accept: 'application/json' } });
      const data = await readJson(response, 'Impossible de charger les messages.');
      if (data.server_time) serverTime = data.server_time;
      const list = data.messages || [];

      if (initial) {
        statusEl?.remove();
        list.forEach((message) => appendMessage(message));
        if (!list.length) messagesEl.append(emptyNote());
        scroll.toBottom(false);
      } else if (list.length) {
        const fresh = list.filter((m) => !document.getElementById(`private-message-${m.id}`));
        const settle = scroll.follow(fresh.length, false);
        clearEmptyNote();
        list.forEach((message) => appendMessage(message, true));
        if (fresh.length) settle();
      }
      updateReadReceipts(data.read_ids);
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
    filePreview.querySelector('img')?.remove();
    compose.refresh();
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
      const image = el('img', 'chat-file-thumb');
      image.src = previewUrl;
      image.alt = 'Aperçu de l’image à envoyer';
      filePreview.prepend(image);
    }
    showError('');
    compose.refresh();
  }

  async function sendMessage(extraFile = null, isVoice = false) {
    if (sending) return false;
    const body = isVoice ? '' : input.value.trim();
    const file = extraFile || selectedFile;
    if (!body && !file) return false;

    sending = true;
    sendButton.disabled = true;
    form.classList.add('is-sending');
    showError('');
    try {
      let response;
      if (file) {
        const formData = new FormData();
        formData.append('body', body);
        formData.append('attachment', file, file.name || (isVoice ? 'message-vocal.webm' : 'piece-jointe'));
        if (isVoice) formData.append('is_voice', '1');
        Object.entries(selectedContext()).forEach(([key, value]) => formData.append(key, value));
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
          body: JSON.stringify({ body, ...selectedContext() }),
        });
      }
      const data = await readJson(response, 'Le message n’a pas pu être envoyé.');
      clearEmptyNote();
      appendMessage(data.message, true);
      scroll.toBottom(true);
      if (!isVoice) input.value = '';
      if (file && !isVoice) clearFile();
      if (contextSelect) contextSelect.value = '';
      return true;
    } catch (error) {
      showError(error.message || 'Erreur de connexion. Réessayez.');
      return false;
    } finally {
      sending = false;
      sendButton.disabled = blockButton?.dataset.blocked === '1';
      form.classList.remove('is-sending');
      compose.refresh();
      if (!isVoice) input.focus();
    }
  }

  function selectedContext() {
    const value = contextSelect ? contextSelect.value : '';
    const [kind, id] = value.split(':');
    if (kind === 'question' && id) return { question_id: id };
    if (kind === 'lesson' && id) return { lesson_id: id };
    return {};
  }

  if (aiDraftButton) {
    aiDraftButton.addEventListener('click', async () => {
      if (input.value.trim() && !window.confirm('Remplacer le texte en cours par un brouillon IA ?')) return;
      aiDraftButton.disabled = true;
      const label = aiDraftButton.querySelector('span');
      const original = label ? label.textContent : '';
      if (label) label.textContent = 'Rédaction…';
      showError('');
      try {
        const data = await Chat.api(root.dataset.aiDraftUrl);
        input.value = data.draft;
        input.dispatchEvent(new Event('input'));
        input.focus();
      } catch (error) {
        showError(error.message);
      } finally {
        aiDraftButton.disabled = false;
        if (label) label.textContent = original;
      }
    });
  }

  function setComposerBlocked(blocked) {
    form.querySelectorAll('textarea, button').forEach((node) => { node.disabled = blocked; });
    input.placeholder = blocked ? 'Conversation bloquée' : 'Écrire un message…';
  }

  if (blockButton) {
    blockButton.addEventListener('click', async () => {
      const blocked = blockButton.dataset.blocked === '1';
      const question = blocked
        ? 'Débloquer ce camarade ? Vous pourrez de nouveau échanger des messages.'
        : 'Bloquer ce camarade ? Aucun de vous deux ne pourra plus envoyer de message ici.';
      if (!window.confirm(question)) return;
      try {
        const data = await Chat.api(root.dataset.blockUrl, {
          user_id: Number(root.dataset.contactId),
          blocked: !blocked,
        });
        blockButton.dataset.blocked = data.blocked ? '1' : '0';
        blockButton.querySelector('span').textContent = data.blocked ? 'Débloquer' : 'Bloquer';
        setComposerBlocked(data.blocked);
      } catch (error) {
        showError(error.message);
      }
    });
    if (blockButton.dataset.blocked === '1') setComposerBlocked(true);
  }

  /* ---- Menu « Joindre » : document, photo, audio ---- */
  function closeAttachMenu() {
    if (!attachMenu || attachMenu.hidden) return;
    attachMenu.hidden = true;
    attachToggle.setAttribute('aria-expanded', 'false');
  }
  if (attachToggle && attachMenu) {
    attachToggle.addEventListener('click', (event) => {
      event.stopPropagation();
      const open = attachMenu.hidden;
      attachMenu.hidden = !open;
      attachToggle.setAttribute('aria-expanded', String(open));
      if (open) attachMenu.querySelector('button')?.focus();
    });
    document.addEventListener('click', (event) => {
      if (!attachMenu.contains(event.target)) closeAttachMenu();
    });
    attachMenu.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { closeAttachMenu(); attachToggle.focus(); }
    });
  }

  function openFilePicker(inputId) {
    closeAttachMenu();
    document.getElementById(inputId)?.click();
  }

  fileInputs.forEach((fileInput) => {
    if (fileInput) fileInput.addEventListener('change', () => chooseFile(fileInput.files?.[0]));
  });
  document.getElementById('privateFileBtn').addEventListener('click', () => openFilePicker('privateFileInput'));
  document.getElementById('privateImageBtn').addEventListener('click', () => openFilePicker('privateImageInput'));
  document.getElementById('privateCameraBtn')?.addEventListener('click', () => openFilePicker('privateCameraInput'));
  document.getElementById('privateAudioBtn').addEventListener('click', () => openFilePicker('privateAudioInput'));
  document.getElementById('privateFileClear').addEventListener('click', clearFile);

  const emojiButton = document.getElementById('privateEmojiBtn');
  emojiButton.addEventListener('click', (event) => {
    event.stopPropagation();
    if (emojiGrid.childElementCount === 0) {
      emojis.forEach((emoji) => {
        const button = el('button', 'chat-emoji-item', emoji);
        button.type = 'button';
        button.addEventListener('click', () => {
          const start = input.selectionStart ?? input.value.length;
          const end = input.selectionEnd ?? start;
          input.value = input.value.slice(0, start) + emoji + input.value.slice(end);
          input.focus();
          input.setSelectionRange(start + emoji.length, start + emoji.length);
          compose.refresh();
        });
        emojiGrid.append(button);
      });
    }
    emojiPanel.hidden = !emojiPanel.hidden;
  });
  document.addEventListener('click', (event) => {
    if (emojiPanel.hidden || emojiPanel.contains(event.target) || emojiButton.contains(event.target)) return;
    emojiPanel.hidden = true;
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    sendMessage();
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

  Chat.enableTapActions(messagesEl);
  loadMessages(true);
  Chat.liveUpdates(root.dataset.wsPath, () => loadMessages(false), () => loadMessages(false));
})();
