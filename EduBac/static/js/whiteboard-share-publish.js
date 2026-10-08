/**
 * Partage du canvas courant vers une seule classe (PNG).
 */
(function () {
  'use strict';
  var button = document.getElementById('wbShare');
  var dialog = document.getElementById('wbShareDialog');
  var app = document.getElementById('wbApp');
  var canvas = document.getElementById('wbCanvas');
  if (!button || !dialog || !app || !canvas) return;

  var classesEl = document.getElementById('wbShareClasses');
  var classes = [];
  try { classes = classesEl ? JSON.parse(classesEl.textContent || '[]') : []; }
  catch (err) { classes = []; }

  var select = document.getElementById('wbShareClass');
  var titleInput = document.getElementById('wbShareName');
  var choose = dialog.querySelector('[data-step="choose"]');
  var confirmStep = dialog.querySelector('[data-step="confirm"]');
  var confirmText = document.getElementById('wbShareConfirmText');
  var errorEl = document.getElementById('wbShareError');
  var sendBtn = document.getElementById('wbShareSend');
  var nextBtn = dialog.querySelector('[data-share-next]');
  var backBtn = dialog.querySelector('[data-share-back]');
  var chosen = null;

  function setError(text) {
    if (errorEl) errorEl.textContent = text || '';
  }
  function showStep(name) {
    if (choose) choose.hidden = name !== 'choose';
    if (confirmStep) confirmStep.hidden = name !== 'confirm';
    if (nextBtn) nextBtn.hidden = name !== 'choose';
    if (backBtn) backBtn.hidden = name !== 'confirm';
    if (sendBtn) sendBtn.hidden = name !== 'confirm';
  }

  classes.forEach(function (item) {
    var option = document.createElement('option');
    option.value = String(item.id);
    option.textContent = item.name;
    select.appendChild(option);
  });
  if (!classes.length) {
    var empty = document.createElement('option');
    empty.value = '';
    empty.textContent = 'Aucune classe disponible';
    select.appendChild(empty);
    select.disabled = true;
  }

  button.addEventListener('click', function () {
    var label = document.getElementById('wbTitleLabel');
    titleInput.value = label ? label.textContent.trim() : 'Whiteboard';
    chosen = null;
    setError('');
    showStep('choose');
    if (typeof dialog.showModal === 'function') dialog.showModal();
  });

  dialog.querySelector('[data-share-cancel]').addEventListener('click', function () {
    dialog.close();
  });
  dialog.querySelector('[data-share-back]').addEventListener('click', function () {
    setError('');
    showStep('choose');
  });
  dialog.querySelector('[data-share-next]').addEventListener('click', function () {
    if (!classes.length || !select.value) {
      setError('Créez une classe avant de partager.');
      return;
    }
    chosen = classes.find(function (item) { return String(item.id) === select.value; }) || null;
    if (!chosen) {
      setError('Choisissez une classe.');
      return;
    }
    if (sendBtn) sendBtn.disabled = false;
    setError('');
    confirmText.textContent = 'Partager ce whiteboard avec la classe « ' + chosen.name
      + ' » ? Il sera visible uniquement par les élèves de cette classe.';
    showStep('confirm');
  });

  dialog.querySelector('form').addEventListener('submit', function (event) {
    event.preventDefault();
    if (!chosen || confirmStep.hidden) return;
    setError('');
    sendBtn.disabled = true;
    var title = (titleInput.value || '').trim() || 'Whiteboard';
    canvas.toBlob(function (blob) {
      if (!blob) {
        setError('Export indisponible : une image externe bloque la capture.');
        sendBtn.disabled = false;
        return;
      }
      var body = new FormData();
      body.append('image', blob, 'whiteboard.png');
      body.append('classroom_id', String(chosen.id));
      body.append('title', title);
      fetch(button.dataset.shareUrl, {
        method: 'POST',
        body: body,
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': app.dataset.csrf || '' },
      }).then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      }).then(function (result) {
        if (!result.ok) throw new Error((result.data && result.data.error) || 'Partage impossible.');
        dialog.close();
        var status = document.getElementById('wbStatus');
        if (status) status.textContent = 'Partagé avec « ' + chosen.name + ' ».';
      }).catch(function (err) {
        setError(err.message || 'Partage impossible.');
        sendBtn.disabled = false;
      });
    }, 'image/png');
  });
})();
