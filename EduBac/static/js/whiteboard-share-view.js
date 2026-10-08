/**
 * Visionneuse lecture seule : zoom, déplacement, plein écran, mise à jour.
 * Aucun outil de dessin n'est branché sur le canvas.
 */
(function () {
  'use strict';
  var root = document.getElementById('wbShareView');
  var watch = document.getElementById('wbShareWatch');
  if (!root && watch && watch.dataset.classroomId) {
    var watchApi = watch.dataset.api || '';
    var watchClass = watch.dataset.classroomId;
    function openShare(data) {
      if (data && data.view_url) window.location.assign(data.view_url);
    }
    function watchPoll() {
      if (!watchApi) return;
      fetch(watchApi + '?classroom=' + encodeURIComponent(watchClass), { credentials: 'same-origin' })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (data) {
          var items = (data && data.shares) || [];
          if (items.length) openShare(items[0]);
        })
        .catch(function () {});
    }
    if (window.WebSocket) {
      var watchProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      try {
        var watchSocket = new WebSocket(watchProto + '//' + location.host + '/ws/whiteboard/classe/' + watchClass + '/');
        watchSocket.onmessage = function (event) {
          try { openShare(JSON.parse(event.data)); } catch (err) { /* ignore */ }
        };
      } catch (err) { /* polling covers it */ }
    }
    if (watchApi) window.setInterval(watchPoll, 8000);
    return;
  }
  if (!root || root.dataset.bound === '1') return;
  root.dataset.bound = '1';

  var viewport = root.querySelector('.wb-share-viewport');
  var stage = root.querySelector('.wb-share-stage');
  var canvas = root.querySelector('canvas');
  var label = root.querySelector('[data-zoom-label]');
  var titleEl = root.querySelector('[data-share-title]');
  var metaEl = root.querySelector('[data-share-meta]');
  var banner = root.querySelector('[data-share-banner]');
  var ctx = canvas.getContext('2d');
  var img = new Image();
  var scale = 1;
  var x = 0;
  var y = 0;
  var dragging = false;
  var lastX = 0;
  var lastY = 0;
  var shareId = Number(root.dataset.shareId || 0);
  var follow = root.dataset.follow === '1';
  var classroomId = root.dataset.classroomId || '';
  var api = root.dataset.api || '';

  function apply() {
    stage.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + scale + ')';
    if (label) label.textContent = Math.round(scale * 100) + '%';
  }

  function fit() {
    var vw = viewport.clientWidth || 1;
    var vh = viewport.clientHeight || 1;
    var iw = img.naturalWidth || canvas.width || 1;
    var ih = img.naturalHeight || canvas.height || 1;
    scale = Math.min(vw / iw, vh / ih, 1);
    if (!isFinite(scale) || scale <= 0) scale = 1;
    x = Math.max(0, (vw - iw * scale) / 2);
    y = Math.max(0, (vh - ih * scale) / 2);
    apply();
  }

  function draw() {
    canvas.width = img.naturalWidth || 1;
    canvas.height = img.naturalHeight || 1;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0);
    fit();
  }

  img.onload = draw;
  img.alt = '';
  img.src = root.dataset.image || '';

  function zoomBy(factor) {
    scale = Math.min(4, Math.max(0.25, scale * factor));
    apply();
  }

  root.querySelectorAll('[data-zoom]').forEach(function (button) {
    button.addEventListener('click', function () {
      var mode = button.getAttribute('data-zoom');
      if (mode === 'in') zoomBy(1.15);
      else if (mode === 'out') zoomBy(1 / 1.15);
      else fit();
    });
  });

  viewport.addEventListener('wheel', function (event) {
    event.preventDefault();
    zoomBy(event.deltaY < 0 ? 1.08 : 1 / 1.08);
  }, { passive: false });

  viewport.addEventListener('pointerdown', function (event) {
    if (event.button != null && event.button !== 0) return;
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    viewport.classList.add('is-panning');
    if (viewport.setPointerCapture) viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener('pointermove', function (event) {
    if (!dragging) return;
    x += event.clientX - lastX;
    y += event.clientY - lastY;
    lastX = event.clientX;
    lastY = event.clientY;
    apply();
  });
  function stopPan() {
    dragging = false;
    viewport.classList.remove('is-panning');
  }
  viewport.addEventListener('pointerup', stopPan);
  viewport.addEventListener('pointercancel', stopPan);

  var fullscreenBtn = root.querySelector('[data-fullscreen]');
  if (fullscreenBtn) {
    if (!viewport.requestFullscreen) fullscreenBtn.hidden = true;
    fullscreenBtn.addEventListener('click', function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else viewport.requestFullscreen();
    });
  }

  function prependHistory(data) {
    var history = document.getElementById('wbShareHistory');
    if (!history || history.querySelector('[data-share-id="' + data.id + '"]')) return;
    var empty = history.querySelector('[data-empty]');
    if (empty) empty.remove();
    var item = document.createElement('li');
    item.className = 'list-group-item';
    item.dataset.shareId = String(data.id);
    var link = document.createElement('a');
    link.href = data.view_url || '#';
    link.className = 'text-decoration-none d-block';
    var when = document.createElement('div');
    when.className = 'small text-muted';
    when.textContent = data.when || '';
    var name = document.createElement('div');
    name.className = 'fw-semibold';
    name.style.color = 'var(--edubac-navy)';
    name.textContent = (data.classroom_name || '') + ' — ' + (data.title || '');
    link.appendChild(when);
    link.appendChild(name);
    item.appendChild(link);
    history.insertBefore(item, history.firstChild);
  }

  function receive(data) {
    if (!data || !data.id || Number(data.id) === shareId) return;
    if (String(data.classroom_id || '') !== String(classroomId)) return;
    prependHistory(data);
    if (follow) {
      shareId = Number(data.id);
      root.dataset.shareId = String(shareId);
      if (titleEl) titleEl.textContent = data.title || '';
      if (metaEl) {
        metaEl.textContent = (data.when || '') + ' · ' + (data.classroom_name || '') + ' — ' + (data.title || '');
      }
      img.src = data.image_url;
      return;
    }
    if (banner) {
      banner.replaceChildren();
      banner.hidden = false;
      var text = document.createElement('span');
      text.textContent = 'Nouveau whiteboard partagé : ' + (data.title || '') + '. ';
      var link = document.createElement('a');
      link.href = data.view_url || '#';
      link.textContent = 'Ouvrir';
      banner.appendChild(text);
      banner.appendChild(link);
    }
  }

  function poll() {
    if (!api) return;
    var url = api + '?after=' + shareId;
    if (classroomId) url += '&classroom=' + encodeURIComponent(classroomId);
    fetch(url, { credentials: 'same-origin' })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        var items = (data && data.shares) || [];
        items.slice().reverse().forEach(receive);
      })
      .catch(function () {});
  }

  if (classroomId && window.WebSocket) {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
      var socket = new WebSocket(proto + '//' + location.host + '/ws/whiteboard/classe/' + classroomId + '/');
      socket.onmessage = function (event) {
        try { receive(JSON.parse(event.data)); } catch (err) { /* ignore */ }
      };
      socket.onclose = function () { window.setTimeout(poll, 4000); };
    } catch (err) {
      poll();
    }
  }
  if (api) window.setInterval(poll, 8000);
})();
