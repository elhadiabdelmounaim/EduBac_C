/**
 * Salon de classe : messages, réponses, épingles, annonces, vocal,
 * modération, membres et réglages.
 */
(function () {
  'use strict';

  var app = document.getElementById('chatApp');
  if (!app) return;

  var userId = parseInt(app.getAttribute('data-user-id'), 10);
  var classroomId = app.getAttribute('data-classroom-id') || '';
  var csrf = app.getAttribute('data-csrf') || '';
  var isTeacher = app.getAttribute('data-is-teacher') === '1';
  var messagesEl = document.getElementById('chatMessages');
  var form = document.getElementById('chatForm');
  var input = document.getElementById('chatInput');
  var emojiBtn = document.getElementById('chatEmojiBtn');
  var emojiPanel = document.getElementById('chatEmojiPanel');
  var emojiGrid = document.getElementById('chatEmojiGrid');
  var attachBtn = document.getElementById('chatAttachBtn');
  var fileInput = document.getElementById('chatFileInput');
  var filePreview = document.getElementById('chatFilePreview');
  var filePreviewName = document.getElementById('chatFilePreviewName');
  var fileClear = document.getElementById('chatFileClear');
  var replyBar = document.getElementById('chatReplyBar');
  var replyName = document.getElementById('chatReplyName');
  var replyText = document.getElementById('chatReplyText');
  var replyCancel = document.getElementById('chatReplyCancel');
  var pinnedBar = document.getElementById('chatPinnedBar');
  var lastId = 0;
  var lastMarkedReadMessageId = 0;
  var selectedFile = null;
  var replyToId = null;
  var notifPermissionAsked = false;
  var announcementInput = document.getElementById('chatAnnouncementInput');
  var membersButton = document.getElementById('chatMembersBtn');
  var membersDialog = document.getElementById('chatMembersDialog');
  var membersContent = document.getElementById('chatMembersContent');
  var membersClose = document.getElementById('chatMembersClose');
  var restrictionEl = document.getElementById('chatRestriction');
  var settingsButton = document.getElementById('chatSettingsBtn');
  var settingsDialog = document.getElementById('chatSettingsDialog');
  var pinnedButton = document.getElementById('chatPinnedListBtn');
  var pinnedDialog = document.getElementById('chatPinnedDialog');
  var pinnedList = document.getElementById('chatPinnedList');
  var Chat = window.EduBacChat;
  var messagesById = {};
  var serverTime = '';
  var roomState = { can_post: true, can_moderate: isTeacher, restriction: '' };
  var scroll = messagesEl ? Chat.scroller(messagesEl, document.getElementById('chatJumpBtn')) : null;
  var compose = form && input ? Chat.composer(form, input, function () { return !!selectedFile; }) : null;

  var EMOJIS = [
    '😀','😃','😄','😁','😅','😂','😊','😇','🙂','😉','😍','🥰','😘','😋','😜','🤗',
    '🤔','😐','😏','😴','👍','👎','👏','🙏','✌️','🤝','❤️','🧡','💛','💚','💙','💜',
    '🔥','⭐','✨','🎉','💯','✅','❌','❓','📚','📖','✏️','📝','🎓','💪','👋','👀'
  ];

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function icon(name) {
    var i = el('i', 'bi ' + name);
    i.setAttribute('aria-hidden', 'true');
    return i;
  }

  function playNotifSound() {
    try {
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      var o = ctx.createOscillator();
      var g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.frequency.value = 880;
      g.gain.value = 0.08;
      o.start();
      setTimeout(function () { o.stop(); ctx.close(); }, 120);
    } catch (e) {}
  }

  function desktopNotify(title, body) {
    if (!('Notification' in window) || !document.hidden) return;
    if (Notification.permission === 'granted') {
      try { new Notification(title, { body: body, icon: '/static/img/edubac-logo.png' }); } catch (e) {}
    } else if (Notification.permission !== 'denied' && !notifPermissionAsked) {
      notifPermissionAsked = true;
      Notification.requestPermission();
    }
  }

  function setReply(m) {
    replyToId = m.id;
    if (replyBar) replyBar.hidden = false;
    if (replyName) replyName.textContent = m.sender_name || '';
    if (replyText) replyText.textContent = (m.body || m.attachment_name || (m.is_voice ? 'Message vocal' : 'Message')).slice(0, 80);
    if (input) input.focus();
  }

  function clearReply() {
    replyToId = null;
    if (replyBar) replyBar.hidden = true;
  }

  function actionButton(cls, iconName, title) {
    var button = el('button', cls);
    button.type = 'button';
    button.title = title;
    button.setAttribute('aria-label', title);
    button.append(icon(iconName));
    return button;
  }

  function attachmentNode(m) {
    if (m.is_voice && m.attachment_url) {
      var audio = el('audio', 'chat-voice-player');
      audio.controls = true;
      audio.preload = 'none';
      audio.src = m.attachment_url;
      return audio;
    }
    if (!m.attachment_url) return null;
    if (m.is_image) {
      var link = el('a', 'chat-att-img-link');
      link.href = m.attachment_url;
      link.target = '_blank';
      link.rel = 'noopener';
      var img = el('img', 'chat-att-img');
      img.src = m.attachment_url;
      img.alt = m.attachment_name || 'Image jointe';
      img.loading = 'lazy';
      link.append(img);
      return link;
    }
    var file = el('a', 'chat-att-file');
    file.href = m.attachment_url;
    var badge = el('span', 'chat-att-file-icon');
    badge.append(icon('bi-file-earmark-text'));
    var name = el('span', 'chat-att-file-name', m.attachment_name || 'Fichier');
    var hint = el('span', 'chat-att-file-hint', 'Télécharger');
    var text = el('span', 'chat-att-file-text');
    text.append(name, hint);
    file.append(badge, text, icon('bi-download'));
    return file;
  }

  function renderMessage(m, animate, isNew) {
    if (!messagesEl || !m || !m.id) return;
    var existing = document.getElementById('msg-' + m.id);
    if (existing && isNew) return;
    if (m.id > lastId) lastId = m.id;
    messagesById[m.id] = m;

    var mine = parseInt(m.sender_id, 10) === userId;
    m.mine = mine;
    var tone = String(Chat.avatarTone(m.sender_name));
    var row = el('div', 'chat-bubble-row ' + (mine ? 'mine' : 'theirs'));
    row.id = 'msg-' + m.id;
    if (m.is_pinned) row.classList.add('is-pinned');
    if (m.is_announcement) row.classList.add('is-announcement');
    if (m.is_deleted) row.classList.add('is-deleted');
    if (m.is_voice && !m.is_deleted) row.classList.add('is-voice');

    if (!mine) {
      var avatar = el('span', 'chat-row-avatar', (m.sender_name || '?').slice(0, 1).toUpperCase());
      avatar.setAttribute('data-tone', tone);
      avatar.setAttribute('aria-hidden', 'true');
      row.append(avatar);
    }

    var stack = el('div', 'chat-bubble-stack');
    var bubble = el('div', 'chat-bubble');
    if (!mine) {
      var sender = el('div', 'chat-sender-name', m.sender_name || 'Membre');
      sender.setAttribute('data-tone', tone);
      if (m.is_teacher) sender.append(el('span', 'chat-role-badge', 'Prof'));
      bubble.append(sender);
    }

    if (m.is_deleted) {
      var deleted = el('em', 'chat-deleted-text');
      deleted.append(icon('bi-slash-circle'), ' ',
        m.deleted_by_moderator ? 'Message supprimé par la modération' : 'Message supprimé');
      bubble.append(deleted);
    } else {
      if (m.is_announcement) {
        var badge = el('div', 'chat-announcement-badge');
        badge.append(icon('bi-megaphone-fill'), ' Annonce importante');
        bubble.append(badge);
      }
      if (m.reply_to) {
        var quote = el('button', 'chat-reply-quote');
        quote.type = 'button';
        quote.title = 'Voir le message d’origine';
        var quoteText = el('span', '', m.reply_to.body);
        quote.append(el('strong', '', m.reply_to.sender_name), quoteText);
        // Formule rendue seulement si la citation n'a pas coupé un « $…$ ».
        if (((m.reply_to.body || '').match(/\$/g) || []).length % 2 === 0) Chat.renderMath(quoteText);
        quote.addEventListener('click', function () {
          var original = document.getElementById('msg-' + m.reply_to.id);
          if (!original) return;
          original.scrollIntoView({ behavior: 'smooth', block: 'center' });
          original.classList.add('is-highlighted');
          setTimeout(function () { original.classList.remove('is-highlighted'); }, 1600);
        });
        bubble.append(quote);
      }
      if (m.whiteboard_share) {
        var share = el('a', 'chat-share-card');
        share.href = m.whiteboard_share.view_url;
        var shot = el('img');
        shot.src = m.whiteboard_share.image_url;
        shot.alt = m.whiteboard_share.title;
        shot.loading = 'lazy';
        var caption = el('span');
        caption.append(icon('bi-easel'), ' ', m.whiteboard_share.title);
        share.append(shot, caption);
        bubble.append(share);
      }
      var attachment = attachmentNode(m);
      if (attachment) bubble.append(attachment);
      if (m.body && !m.whiteboard_share) {
        var text = el('div', 'chat-message-text' + (attachment ? ' chat-att-caption' : ''));
        Chat.renderText(text, m.body);
        bubble.append(text);
      }
    }

    var meta = el('span', 'chat-bubble-meta');
    if (m.is_pinned) {
      var pin = icon('bi-pin-angle-fill');
      pin.title = 'Épinglé';
      meta.append(pin);
    }
    if (m.is_edited && !m.is_deleted) meta.append(el('span', 'chat-edited', 'modifié'));
    meta.append(el('time', 'chat-bubble-time', Chat.timeLabel(m.created_at, m.time_display)));
    // Le salon ne suit pas la lecture par destinataire : seul « envoyé » est affiché.
    if (mine && !m.is_deleted) meta.append(Chat.receipt('sent'));
    bubble.append(meta);
    stack.append(bubble);
    var onReacted = function (updated) { afterAction(updated); };
    var chips = Chat.reactionChips('class', m, onReacted, roomState.can_react);
    if (chips) stack.append(chips);

    if (!m.is_deleted) {
      var actions = el('div', 'chat-msg-actions');
      if (roomState.can_react) actions.append(Chat.reactionButton('class', m, onReacted));
      if (roomState.can_post) actions.append(actionButton('chat-act-reply', 'bi-reply', 'Répondre'));
      if (Chat.canEdit(m, userId)) actions.append(actionButton('chat-act-edit', 'bi-pencil', 'Modifier'));
      if (mine || roomState.can_moderate) actions.append(actionButton('chat-act-delete', 'bi-trash', 'Supprimer'));
      if (!mine) actions.append(actionButton('chat-act-report', 'bi-flag', 'Signaler'));
      if (roomState.can_moderate) {
        actions.append(actionButton('chat-act-pin', m.is_pinned ? 'bi-pin-angle-fill' : 'bi-pin-angle',
          m.is_pinned ? 'Désépingler' : 'Épingler (FAQ de la classe)'));
      }
      if (actions.childElementCount) stack.append(actions);
    }
    row.append(stack);

    Chat.placeMessage(messagesEl, row, m, existing, animate && !existing);
    if (window.EduBacVoice) window.EduBacVoice.enhance(row);
    // Formules uniquement dans le texte : une citation tronquée ne doit pas casser le rendu.
    var mathTarget = bubble.querySelector('.chat-message-text');
    if (mathTarget) Chat.renderMath(mathTarget);
    bindActions(row, m);

    if (isNew && !mine && !m.is_deleted) {
      playNotifSound();
      desktopNotify(m.sender_name || 'EduBac Chat', (m.body || 'Nouveau message').slice(0, 80));
    }
  }

  function afterAction(updated) {
    if (updated) { renderMessage(updated, false, false); updatePinnedBar(); }
  }

  function showActionError(error) { window.alert(error.message || 'Action impossible.'); }

  function bindActions(row, m) {
    var on = function (selector, handler) {
      var button = row.querySelector(selector);
      if (button) button.addEventListener('click', handler);
    };
    on('.chat-act-reply', function () { setReply(m); });
    on('.chat-act-edit', function () {
      Chat.editMessage('class', m).then(afterAction).catch(showActionError);
    });
    on('.chat-act-delete', function () {
      Chat.deleteMessage('class', m, roomState.can_moderate).then(afterAction).catch(showActionError);
    });
    on('.chat-act-report', function () { Chat.reportMessage('class', m); });
    on('.chat-act-pin', function () {
      Chat.api('/chat/api/classe/' + classroomId + '/pin/' + m.id + '/')
        .then(function (d) { afterAction(d.message); })
        .catch(showActionError);
    });
  }

  function applyRoomState(state) {
    if (!state) return;
    var changed = state.can_post !== roomState.can_post || state.can_moderate !== roomState.can_moderate;
    roomState = state;
    if (restrictionEl) {
      restrictionEl.textContent = state.restriction || '';
      restrictionEl.hidden = !state.restriction;
    }
    if (form) {
      form.querySelectorAll('textarea, button').forEach(function (node) { node.disabled = !state.can_post; });
      if (input) input.placeholder = state.can_post ? 'Écrire un message…' : 'Écriture désactivée';
    }
    var voiceBtn = document.getElementById('chatVoiceBtn');
    if (voiceBtn) voiceBtn.disabled = !state.can_post;
    if (settingsDialog) fillSettings(state);
    if (changed) {
      Object.keys(messagesById).forEach(function (id) { renderMessage(messagesById[id], false, false); });
    }
  }

  function updatePinnedBar() {
    if (!pinnedBar || !messagesEl) return;
    var pinned = messagesEl.querySelectorAll('.chat-bubble-row.is-pinned');
    if (!pinned.length) {
      pinnedBar.hidden = true;
      pinnedBar.replaceChildren();
      return;
    }
    var last = pinned[pinned.length - 1];
    var text = last.querySelector('.chat-message-text') || last.querySelector('.chat-bubble');
    pinnedBar.hidden = false;
    pinnedBar.replaceChildren(
      icon('bi-pin-angle-fill'),
      el('span', 'chat-pinned-text', (text && text.innerText || '').replace(/\s+/g, ' ').slice(0, 100))
    );
    if (pinned.length > 1) pinnedBar.append(el('span', 'chat-pinned-count', '+' + (pinned.length - 1)));
    pinnedBar.setAttribute('aria-label', 'Aller au message épinglé');
    pinnedBar.onclick = function () { last.scrollIntoView({ behavior: 'smooth', block: 'center' }); };
  }

  function openPinnedList() {
    if (!pinnedDialog || !pinnedList) return;
    pinnedList.replaceChildren();
    var pinned = Object.keys(messagesById).map(function (id) { return messagesById[id]; })
      .filter(function (m) { return m.is_pinned && !m.is_deleted; });
    if (!pinned.length) {
      pinnedList.append(el('p', 'chat-dialog-empty', 'Aucun message épinglé. Le professeur peut épingler les réponses utiles.'));
    }
    pinned.forEach(function (m) {
      var item = el('button', 'chat-pinned-item');
      item.type = 'button';
      item.append(
        el('strong', '', m.sender_name + ' · ' + Chat.timeLabel(m.created_at, m.time_display)),
        el('span', '', (m.body || m.attachment_name || 'Pièce jointe').slice(0, 300))
      );
      item.addEventListener('click', function () {
        pinnedDialog.close();
        var row = document.getElementById('msg-' + m.id);
        if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      pinnedList.append(item);
    });
    Chat.renderMath(pinnedList);
    pinnedDialog.showModal();
  }

  function markReadAfterIncomingMessages(list) {
    var newestIncomingId = (list || []).reduce(function (newestId, message) {
      var messageId = parseInt(message.id, 10) || 0;
      var senderId = parseInt(message.sender_id, 10);
      return senderId !== userId ? Math.max(newestId, messageId) : newestId;
    }, 0);
    if (newestIncomingId <= lastMarkedReadMessageId) return;

    var previousMarkedId = lastMarkedReadMessageId;
    lastMarkedReadMessageId = newestIncomingId;
    fetch('/chat/api/classe/' + classroomId + '/read/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf, Accept: 'application/json' },
    })
      .then(function (response) {
        if (!response.ok) throw new Error('Impossible de marquer les messages comme lus.');
      })
      .catch(function () {
        if (lastMarkedReadMessageId === newestIncomingId) {
          lastMarkedReadMessageId = previousMarkedId;
        }
      });
  }

  function clearStatus() {
    var status = messagesEl && messagesEl.querySelector(':scope > .chat-messages-status');
    if (status) status.remove();
  }

  function showStatus(text, isError) {
    messagesEl.replaceChildren(el('div', 'chat-messages-status' + (isError ? ' is-error' : ''), text));
  }

  function loadMessages(initial) {
    if (!classroomId || !messagesEl) return;
    var url = '/chat/api/classe/' + classroomId + '/messages/';
    if (!initial && lastId) {
      url += '?after_id=' + lastId + (serverTime ? '&since=' + encodeURIComponent(serverTime) : '');
    }

    fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(function (r) {
        if (r.status === 403) throw new Error('Accès refusé');
        if (!(r.headers.get('content-type') || '').toLowerCase().includes('application/json')) {
          throw new Error(r.redirected
            ? 'Votre session a expiré. Reconnectez-vous puis réessayez.'
            : 'Réponse inattendue du serveur. Actualisez la page et réessayez.');
        }
        return r.json();
      })
      .then(function (data) {
        var list = data.messages || [];
        if (data.server_time) serverTime = data.server_time;
        applyRoomState(data.room);
        if (initial) {
          messagesEl.replaceChildren();
          if (!list.length) showStatus('Aucun message pour le moment. Lancez la discussion !');
        }
        var fresh = list.filter(function (m) { return !document.getElementById('msg-' + m.id); });
        var settle = scroll && !initial ? scroll.follow(fresh.length, false) : null;
        if (list.length) clearStatus();
        list.forEach(function (m) {
          var known = !!document.getElementById('msg-' + m.id);
          renderMessage(m, !initial && !known, !initial && !known);
        });
        if (!initial && list.length) markReadAfterIncomingMessages(list);
        if (initial && scroll) scroll.toBottom(false);
        else if (settle && fresh.length) settle();
        updatePinnedBar();
      })
      .catch(function (e) {
        if (initial && messagesEl) showStatus(e.message, true);
      });
  }

  function clearFile() {
    selectedFile = null;
    if (fileInput) fileInput.value = '';
    if (filePreview) filePreview.hidden = true;
    if (compose) compose.refresh();
  }

  function sendMessage(extraFile, isVoice) {
    if (!classroomId || !input) return Promise.resolve(false);
    var body = isVoice ? '' : (input.value || '').trim();
    var file = extraFile || selectedFile;
    if (!body && !file) return Promise.resolve(false);

    var btn = form && form.querySelector('.chat-send-btn');
    if (btn) btn.disabled = true;
    if (form) form.classList.add('is-sending');

    var req;
    if (file) {
      var fd = new FormData();
      fd.append('body', body);
      fd.append('attachment', file, file.name || (isVoice ? 'voice.webm' : 'file'));
      if (isVoice) fd.append('is_voice', '1');
      if (replyToId) fd.append('reply_to', replyToId);
      if (announcementInput && announcementInput.checked) fd.append('is_announcement', '1');
      req = fetch('/chat/api/classe/' + classroomId + '/send/', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf, Accept: 'application/json' }, body: fd,
      });
    } else {
      req = fetch('/chat/api/classe/' + classroomId + '/send/', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
        body: JSON.stringify({
          body: body,
          reply_to: replyToId,
          is_announcement: !!(announcementInput && announcementInput.checked),
        }),
      });
    }

    return req.then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { alert(res.d.error || 'Erreur'); return false; }
        if (!isVoice) {
          input.value = '';
          clearFile();
          closeEmoji();
        }
        if (announcementInput) announcementInput.checked = false;
        clearReply();
        clearStatus();
        renderMessage(res.d.message, true, false);
        if (scroll) scroll.toBottom(true);
        updatePinnedBar();
        return true;
      })
      .catch(function () { alert('Erreur réseau'); return false; })
      .finally(function () {
        if (btn) btn.disabled = !roomState.can_post;
        if (form) form.classList.remove('is-sending');
        if (compose) compose.refresh();
        if (!isVoice && input) input.focus();
      });
  }

  function openEmoji() {
    if (!emojiPanel || !emojiGrid) return;
    if (!emojiGrid.childElementCount) {
      EMOJIS.forEach(function (em) {
        var b = el('button', 'chat-emoji-item', em);
        b.type = 'button';
        b.addEventListener('click', function () {
          if (!input) return;
          var start = input.selectionStart || input.value.length;
          var end = input.selectionEnd || start;
          input.value = input.value.slice(0, start) + em + input.value.slice(end);
          input.focus();
          if (compose) compose.refresh();
        });
        emojiGrid.appendChild(b);
      });
    }
    emojiPanel.hidden = false;
  }
  function closeEmoji() { if (emojiPanel) emojiPanel.hidden = true; }

  if (form) form.addEventListener('submit', function (e) { e.preventDefault(); sendMessage(); });
  if (emojiBtn) emojiBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    if (emojiPanel && emojiPanel.hidden) openEmoji(); else closeEmoji();
  });
  document.addEventListener('click', function (e) {
    if (!emojiPanel || emojiPanel.hidden) return;
    if (emojiPanel.contains(e.target) || (emojiBtn && emojiBtn.contains(e.target))) return;
    closeEmoji();
  });
  if (attachBtn && fileInput) {
    attachBtn.addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () {
      var f = fileInput.files && fileInput.files[0];
      if (!f) return;
      if (f.size > 10 * 1024 * 1024) { alert('Max 10 Mo'); return; }
      selectedFile = f;
      if (filePreview) filePreview.hidden = false;
      if (filePreviewName) filePreviewName.textContent = (f.type.indexOf('image/') === 0 ? '🖼️ ' : '') + f.name;
      if (compose) compose.refresh();
    });
  }
  if (fileClear) fileClear.addEventListener('click', clearFile);
  if (replyCancel) replyCancel.addEventListener('click', clearReply);
  if (messagesEl) Chat.enableTapActions(messagesEl);

  if (membersButton && membersDialog && membersContent) {
    membersButton.addEventListener('click', function () {
      membersContent.textContent = 'Chargement des membres…';
      membersDialog.showModal();
      fetch('/chat/api/classe/' + classroomId + '/members/', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      })
        .then(function (response) {
          if (!(response.headers.get('content-type') || '').toLowerCase().includes('application/json')) {
            throw new Error('Réponse inattendue du serveur. Actualisez la page et réessayez.');
          }
          return response.json().then(function (data) {
            if (!response.ok) throw new Error(data.error || 'Impossible de charger les membres.');
            return data;
          });
        })
        .then(function (data) {
          membersContent.replaceChildren();
          (data.members || []).forEach(function (member) {
            var row = el('div', 'chat-member-row');
            var avatar = el('span', 'chat-avatar is-small', (member.name || '?').slice(0, 1).toUpperCase());
            avatar.setAttribute('data-tone', String(Chat.avatarTone(member.name)));
            avatar.setAttribute('aria-hidden', 'true');
            if (member.is_online) avatar.append(el('span', 'chat-presence-dot'));
            var details = el('div', 'chat-member-details');
            details.append(
              el('strong', '', member.name || 'Membre'),
              el('span', '', member.role + ' · ' + member.message_count + ' message(s)'
                + (member.last_message_at ? ' · dernier : ' + member.last_message_at : ''))
            );
            row.append(avatar, details);
            if (member.is_online) row.append(el('span', 'chat-member-presence', 'En ligne'));
            if (data.can_moderate && member.role === 'Élève') {
              var slot = el('div');
              var refreshControls = function () {
                slot.replaceChildren(muteControls(member, refreshControls));
              };
              refreshControls();
              row.append(slot);
            }
            membersContent.append(row);
          });
          if (!(data.members || []).length) {
            membersContent.textContent = 'Aucun membre dans cette classe.';
          }
        })
        .catch(function (error) {
          membersContent.textContent = error.message || 'Impossible de charger les membres.';
        });
    });
    if (membersClose) membersClose.addEventListener('click', function () { membersDialog.close(); });
  }

  function fillSettings(state) {
    var f = settingsDialog && settingsDialog.querySelector('form');
    if (!f || settingsDialog.open) return;
    f.elements.is_locked.checked = !!state.is_locked;
    f.elements.allow_student_direct.checked = !!state.allow_student_direct;
    f.elements.quiet_hours_start.value = state.quiet_hours_start || '';
    f.elements.quiet_hours_end.value = state.quiet_hours_end || '';
  }

  if (settingsButton && settingsDialog) {
    var settingsForm = settingsDialog.querySelector('form');
    var settingsError = settingsDialog.querySelector('.chat-settings-error');
    settingsButton.addEventListener('click', function () {
      if (settingsError) settingsError.hidden = true;
      fillSettings(roomState);
      settingsDialog.showModal();
    });
    settingsDialog.querySelectorAll('[data-close]').forEach(function (button) {
      button.addEventListener('click', function () { settingsDialog.close(); });
    });
    settingsForm.addEventListener('submit', function (event) {
      event.preventDefault();
      Chat.api('/chat/api/classe/' + classroomId + '/settings/', {
        is_locked: settingsForm.elements.is_locked.checked,
        allow_student_direct: settingsForm.elements.allow_student_direct.checked,
        quiet_hours_start: settingsForm.elements.quiet_hours_start.value,
        quiet_hours_end: settingsForm.elements.quiet_hours_end.value,
      }).then(function (data) {
        settingsDialog.close();
        applyRoomState(data.room);
      }).catch(function (error) {
        if (settingsError) { settingsError.textContent = error.message; settingsError.hidden = false; }
      });
    });
  }

  if (pinnedButton) pinnedButton.addEventListener('click', openPinnedList);
  if (pinnedDialog) {
    var pinnedClose = pinnedDialog.querySelector('[data-close]');
    if (pinnedClose) pinnedClose.addEventListener('click', function () { pinnedDialog.close(); });
  }

  var MUTE_CHOICES = [[15, '15 min'], [60, '1 h'], [1440, '24 h'], [10080, '7 jours']];

  function muteControls(member, onDone) {
    var wrap = el('div', 'chat-member-mute');
    if (member.muted_until) {
      var unmute = el('button', 'btn btn-sm btn-outline-secondary', 'Lever');
      unmute.type = 'button';
      unmute.addEventListener('click', function () { mute(member, 0, onDone); });
      wrap.append(el('span', 'chat-member-muted', 'En sourdine jusqu’au ' + member.muted_until), unmute);
      return wrap;
    }
    var select = el('select', 'form-select form-select-sm');
    select.setAttribute('aria-label', 'Mettre ' + member.name + ' en sourdine');
    var placeholder = el('option', '', 'Sourdine…');
    placeholder.value = '';
    select.append(placeholder);
    MUTE_CHOICES.forEach(function (choice) {
      var option = el('option', '', choice[1]);
      option.value = String(choice[0]);
      select.append(option);
    });
    select.addEventListener('change', function () {
      if (select.value) mute(member, parseInt(select.value, 10), onDone);
    });
    wrap.append(select);
    return wrap;
  }

  function mute(member, minutes, onDone) {
    Chat.api('/chat/api/classe/' + classroomId + '/mute/', { user_id: member.id, minutes: minutes })
      .then(function (data) { member.muted_until = data.muted_until; onDone(); })
      .catch(showActionError);
  }

  document.addEventListener('edubac:voice-send', function (event) {
    if (event && event.preventDefault) event.preventDefault();
    var detail = (event && event.detail) || {};
    var done = typeof detail.done === 'function' ? detail.done : function () {};
    if (!detail.file) { done(false); return; }
    Promise.resolve(sendMessage(detail.file, true)).then(function (ok) {
      done(!!ok);
    }, function () { done(false); });
  });

  function startLiveUpdates() {
    Chat.liveUpdates('/ws/chat/' + classroomId + '/', function (event) {
      if (event.type === 'message' && event.message) {
        var known = !!document.getElementById('msg-' + event.message.id);
        var mine = parseInt(event.message.sender_id, 10) === userId;
        var settle = scroll && !known ? scroll.follow(1, mine) : null;
        clearStatus();
        renderMessage(event.message, true, !known);
        if (settle) { settle(); markReadAfterIncomingMessages([event.message]); }
        updatePinnedBar();
      } else if (event.type === 'update' && event.message) {
        // Le message diffusé ne connaît pas le lecteur (ses réactions, ses droits) : on relit
        // les changements depuis la dernière synchronisation.
        if (document.getElementById('msg-' + event.message.id)) loadMessages(false);
      } else if (event.type === 'room') {
        loadMessages(false);
      }
    }, function () { loadMessages(false); });
  }

  if (classroomId) {
    var onlineLabel = document.getElementById('chatOnlineCount');
    var refreshOnlineCount = function () {
      if (document.hidden || !onlineLabel) return;
      fetch('/chat/api/classe/' + classroomId + '/members/', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      }).then(function (response) {
        if (!response.ok || !(response.headers.get('content-type') || '').toLowerCase().includes('application/json')) return null;
        return response.json();
      }).then(function (data) {
        if (data && typeof data.online_count === 'number') {
          onlineLabel.textContent = data.online_count + ' en ligne';
        }
      }).catch(function () {});
    };
    refreshOnlineCount();
    var onlineTimer = setInterval(refreshOnlineCount, 30000);
    window.addEventListener('pagehide', function () { clearInterval(onlineTimer); }, { once: true });
    loadMessages(true);
    startLiveUpdates();
  }
})();
