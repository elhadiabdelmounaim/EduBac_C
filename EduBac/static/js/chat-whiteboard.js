/** Partage d'un tableau en direct depuis une conversation (enseignant). */
(function () {
  'use strict';
  var button = document.getElementById('chatBoardBtn');
  var dialog = document.getElementById('chatBoardDialog');
  if (!button || !dialog || !window.EduBacChat) return;
  var list = document.getElementById('chatBoardList');
  var error = document.getElementById('chatBoardError');
  var form = dialog.querySelector('form');

  function showError(text) { error.textContent = text || ''; error.hidden = !text; }

  function render(boards) {
    list.replaceChildren();
    if (!boards.length) { list.textContent = 'Aucun tableau pour le moment.'; return; }
    boards.forEach(function (board) {
      var label = document.createElement('label');
      label.className = 'chat-board-item';
      var radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'board_id'; radio.value = String(board.id);
      var text = document.createElement('span');
      var title = document.createElement('strong'); title.textContent = board.title;
      var meta = document.createElement('small');
      meta.textContent = (board.classroom ? board.classroom + ' · ' : '') + 'modifié ' + board.updated;
      text.append(title, meta);
      label.append(radio, text);
      list.append(label);
    });
  }

  button.addEventListener('click', function () {
    showError('');
    form.reset();
    list.textContent = 'Chargement…';
    dialog.showModal();
    fetch(dialog.dataset.boardsUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (data) { render(data.boards || []); })
      .catch(function () { list.textContent = 'Impossible de charger vos tableaux.'; });
  });
  form.title.addEventListener('input', function () {
    if (form.title.value.trim()) form.querySelectorAll('input[name="board_id"]').forEach(function (r) { r.checked = false; });
  });
  list.addEventListener('change', function () { form.title.value = ''; });
  dialog.querySelectorAll('[data-close]').forEach(function (b) { b.addEventListener('click', function () { dialog.close(); }); });
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var chosen = form.querySelector('input[name="board_id"]:checked');
    var title = form.title.value.trim();
    if (!chosen && !title) { showError('Donnez un titre au nouveau tableau ou choisissez-en un.'); return; }
    window.EduBacChat.api(dialog.dataset.shareUrl, {
      kind: button.dataset.kind,
      conversation_id: Number(button.dataset.conversationId),
      board_id: chosen ? Number(chosen.value) : null,
      title: title,
    }).then(function (data) {
      window.location.assign(data.url);
    }).catch(function (err) { showError(err.message); });
  });
})();
