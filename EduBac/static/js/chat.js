/**
 * Prof-Étudiant Chat — reply, pin, voice, notifs
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
  var backBtn = document.getElementById('chatBackBtn');
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
  var pollTimer = null;
  var selectedFile = null;
  var replyToId = null;
  var notifPermissionAsked = false;
  var announcementInput = document.getElementById('chatAnnouncementInput');
  var membersButton = document.getElementById('chatMembersBtn');
  var membersDialog = document.getElementById('chatMembersDialog');
  var membersContent = document.getElementById('chatMembersContent');
  var membersClose = document.getElementById('chatMembersClose');

  var EMOJIS = [
    '😀','😃','😄','😁','😅','😂','😊','😇','🙂','😉','😍','🥰','😘','😋','😜','🤗',
    '🤔','😐','😏','😴','👍','👎','👏','🙏','✌️','🤝','❤️','🧡','💛','💚','💙','💜',
    '🔥','⭐','✨','🎉','💯','✅','❌','❓','📚','📖','✏️','📝','🎓','💪','👋','👀'
  ];

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function scrollBottom() {
    if (!messagesEl) return;
    messagesEl.scrollTop = messagesEl.scrollHeight;
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
    if (!('Notification' in window)) return;
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
    if (replyText) replyText.textContent = (m.body || m.attachment_name || 'Message').slice(0, 80);
    if (input) input.focus();
  }

  function clearReply() {
    replyToId = null;
    if (replyBar) replyBar.hidden = true;
  }

  function renderMessage(m, animate, isNew) {
    if (!messagesEl || !m || !m.id) return;
    if (document.getElementById('msg-' + m.id)) return;
    if (m.id > lastId) lastId = m.id;

    var mine = parseInt(m.sender_id, 10) === userId;
    var row = document.createElement('div');
    row.className = 'chat-bubble-row ' + (mine ? 'mine' : 'theirs');
    row.id = 'msg-' + m.id;
    if (m.is_pinned) row.classList.add('is-pinned');
    if (m.is_announcement) row.classList.add('is-announcement');

    var html = '';
    if (!mine) {
      html += '<div class="chat-sender-name">' + esc(m.sender_name) +
        (m.is_teacher ? ' · Prof' : '') + '</div>';
    }
    if (m.reply_to) {
      html += '<div class="chat-reply-quote"><strong>' + esc(m.reply_to.sender_name) +
        '</strong> · ' + esc(m.reply_to.body) + '</div>';
    }

    var bodyHtml = '';
    if (m.is_voice && m.attachment_url) {
      bodyHtml += '<audio controls preload="metadata" class="chat-voice-player" src="' +
        esc(m.attachment_url) + '"></audio>';
    } else if (m.attachment_url) {
      if (m.is_image) {
        bodyHtml += '<a href="' + esc(m.attachment_url) + '" target="_blank" rel="noopener" class="chat-att-img-link">' +
          '<img src="' + esc(m.attachment_url) + '" alt="" class="chat-att-img"></a>';
      } else {
        bodyHtml += '<a href="' + esc(m.attachment_url) + '" target="_blank" rel="noopener" class="chat-att-file">' +
          '<i class="bi bi-file-earmark"></i> <span>' + esc(m.attachment_name || 'Fichier') + '</span></a>';
      }
    }
    if (m.body) {
      bodyHtml += (bodyHtml ? '<div class="chat-att-caption">' : '') + esc(m.body) + (bodyHtml && m.body ? '</div>' : '');
    }
    if (!bodyHtml) bodyHtml = '<em style="opacity:.7">—</em>';
    if (m.is_announcement) {
      bodyHtml = '<div class="chat-announcement-badge"><i class="bi bi-megaphone-fill"></i> Annonce importante</div>' + bodyHtml;
    }

    var timeHtml = esc(m.time_display || '');
    if (mine) timeHtml += ' <span class="chat-ticks">✓✓</span>';
    if (m.is_pinned) timeHtml += ' <i class="bi bi-pin-angle-fill" title="Épinglé"></i>';

    html += '<div class="chat-bubble">' + bodyHtml +
      '<div class="chat-bubble-time">' + timeHtml + '</div></div>';
    html += '<div class="chat-msg-actions">' +
      '<button type="button" class="chat-act-reply" data-id="' + m.id + '" title="Répondre"><i class="bi bi-reply"></i></button>';
    if (isTeacher) {
      html += '<button type="button" class="chat-act-pin" data-id="' + m.id + '" title="Épingler"><i class="bi bi-pin-angle"></i></button>';
    }
    html += '</div>';

    row.innerHTML = html;
    messagesEl.appendChild(row);
    if (window.EduBacVoice) window.EduBacVoice.enhance(row);

    row.querySelector('.chat-act-reply').addEventListener('click', function () {
      setReply(m);
    });
    var pinBtn = row.querySelector('.chat-act-pin');
    if (pinBtn) {
      pinBtn.addEventListener('click', function () {
        fetch('/chat/api/classe/' + classroomId + '/pin/' + m.id + '/', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRFToken': csrf, Accept: 'application/json' },
        })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.ok) {
              m.is_pinned = d.is_pinned;
              row.classList.toggle('is-pinned', d.is_pinned);
              updatePinnedBar();
            }
          });
      });
    }

    if (isNew && !mine) {
      playNotifSound();
      desktopNotify(m.sender_name || 'EduBac Chat', (m.body || 'Nouveau message').slice(0, 80));
    }
  }

  function updatePinnedBar() {
    if (!pinnedBar || !messagesEl) return;
    var pinned = messagesEl.querySelectorAll('.chat-bubble-row.is-pinned');
    if (!pinned.length) {
      pinnedBar.hidden = true;
      pinnedBar.innerHTML = '';
      return;
    }
    var last = pinned[pinned.length - 1];
    var text = last.querySelector('.chat-bubble');
    pinnedBar.hidden = false;
    pinnedBar.innerHTML = '<i class="bi bi-pin-angle-fill"></i> <span>' +
      esc((text && text.innerText || '').replace(/\s+/g, ' ').slice(0, 100)) + '</span>';
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

  function loadMessages(initial) {
    if (!classroomId || !messagesEl) return;
    var url = '/chat/api/classe/' + classroomId + '/messages/';
    if (!initial && lastId) url += '?after_id=' + lastId;

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
        if (initial) {
          messagesEl.innerHTML = '';
          if (!list.length) {
            messagesEl.innerHTML =
              '<div class="text-center text-muted py-4 small">Aucun message pour le moment.</div>';
          }
        }
        list.forEach(function (m) { renderMessage(m, !initial, !initial); });
        if (!initial && list.length) markReadAfterIncomingMessages(list);
        if (initial || list.length) scrollBottom();
        updatePinnedBar();
      })
      .catch(function (e) {
        if (initial && messagesEl) {
          messagesEl.innerHTML = '<div class="text-center text-danger py-4 small">' + esc(e.message) + '</div>';
        }
      });
  }

  function clearFile() {
    selectedFile = null;
    if (fileInput) fileInput.value = '';
    if (filePreview) filePreview.hidden = true;
  }

  function sendMessage(extraFile, isVoice) {
    if (!classroomId || !input) return Promise.resolve(false);
    var body = isVoice ? '' : (input.value || '').trim();
    var file = extraFile || selectedFile;
    if (!body && !file) return Promise.resolve(false);

    var btn = form && form.querySelector('.chat-send-btn');
    if (btn) btn.disabled = true;

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
          input.style.height = 'auto';
          clearFile();
          closeEmoji();
        }
        if (announcementInput) announcementInput.checked = false;
        clearReply();
        var empty = messagesEl && messagesEl.querySelector('.text-muted');
        if (empty && empty.parentElement === messagesEl) empty.remove();
        renderMessage(res.d.message, true, false);
        scrollBottom();
        updatePinnedBar();
        return true;
      })
      .catch(function () { alert('Erreur réseau'); return false; })
      .finally(function () {
        if (btn) btn.disabled = false;
        if (!isVoice && input) input.focus();
      });
  }

  function openEmoji() {
    if (!emojiPanel || !emojiGrid) return;
    if (!emojiGrid.childElementCount) {
      EMOJIS.forEach(function (em) {
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'chat-emoji-item'; b.textContent = em;
        b.addEventListener('click', function () {
          if (!input) return;
          var start = input.selectionStart || input.value.length;
          var end = input.selectionEnd || start;
          input.value = input.value.slice(0, start) + em + input.value.slice(end);
          input.focus();
        });
        emojiGrid.appendChild(b);
      });
    }
    emojiPanel.hidden = false;
  }
  function closeEmoji() { if (emojiPanel) emojiPanel.hidden = true; }

  if (form) form.addEventListener('submit', function (e) { e.preventDefault(); sendMessage(); });
  if (input) {
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    input.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
  }
  if (backBtn) backBtn.addEventListener('click', function () { location.href = '/chat/'; });
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
      if (filePreviewName) filePreviewName.textContent = (f.type.indexOf('image/') === 0 ? '🖼️ ' : '📎 ') + f.name;
    });
  }
  if (fileClear) fileClear.addEventListener('click', clearFile);
  if (replyCancel) replyCancel.addEventListener('click', clearReply);
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
            var row = document.createElement('div');
            row.className = 'chat-member-row';
            var avatar = document.createElement('span');
            avatar.className = 'chat-member-avatar';
            avatar.textContent = (member.name || '?').slice(0, 1).toUpperCase();
            var details = document.createElement('div');
            details.className = 'chat-member-details';
            var name = document.createElement('strong');
            name.textContent = member.name || 'Membre';
            var activity = document.createElement('span');
            activity.textContent = member.role + ' · ' + member.message_count + ' message(s)'
              + (member.last_message_at ? ' · dernier : ' + member.last_message_at : '');
            details.append(name, activity);
            row.append(avatar, details);
            if (member.is_online) {
              var online = document.createElement('span');
              online.className = 'chat-member-presence';
              online.textContent = 'En ligne';
              row.append(online);
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
  document.addEventListener('edubac:voice-send', function (event) {
    if (event && event.preventDefault) event.preventDefault();
    var detail = (event && event.detail) || {};
    var done = typeof detail.done === 'function' ? detail.done : function () {};
    if (!detail.file) { done(false); return; }
    Promise.resolve(sendMessage(detail.file, true)).then(function (ok) {
      done(!!ok);
    }, function () { done(false); });
  });

  var search = document.getElementById('chatRoomSearch');
  if (search) {
    search.addEventListener('input', function () {
      var q = (this.value || '').toLowerCase().trim();
      document.querySelectorAll('.chat-room-item').forEach(function (el) {
        var name = el.getAttribute('data-name') || '';
        el.style.display = (!q || name.indexOf(q) !== -1) ? '' : 'none';
      });
    });
  }

  function startPolling() {
    pollTimer = setInterval(function () {
      if (classroomId) loadMessages(false);
    }, 3000);
  }

  if (classroomId) {
    var onlineLabel = document.getElementById('chatOnlineCount');
    function refreshOnlineCount() {
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
          var dot = document.querySelector('.chat-online-dot');
          if (dot) dot.title = data.online_count + ' en ligne';
        }
      }).catch(function () {});
    }
    refreshOnlineCount();
    var onlineTimer = setInterval(refreshOnlineCount, 30000);
    window.addEventListener('pagehide', function () { clearInterval(onlineTimer); }, { once: true });
    if ('Notification' in window && Notification.permission === 'default') {
      // demandera au premier message reçu
    }
    loadMessages(true);
    startPolling();
  }
})();
