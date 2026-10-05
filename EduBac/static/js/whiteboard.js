/**
 * EduBac Whiteboard — canvas interactif + WebSocket + save
 */
(function () {
  'use strict';
  var app = document.getElementById('wbApp');
  if (!app) return;

  var boardId = app.dataset.boardId;
  var canEdit = app.dataset.canEdit === '1';
  var apiUrl = app.dataset.apiUrl;
  var wsPath = app.dataset.wsPath;
  var csrf = app.dataset.csrf;

  var canvas = document.getElementById('wbCanvas');
  var ctx = canvas.getContext('2d');
  var wrap = document.getElementById('wbCanvasWrap');
  var mathLayer = document.getElementById('wbMathLayer');

  var tool = 'pencil';
  var color = '#1e2a4a';
  var size = 4;
  var drawing = false;
  var startX = 0, startY = 0;
  var currentPath = null;
  var objects = []; // {type, ...}
  var undoStack = [];
  var redoStack = [];
  var showGrid = true;
  var zoom = 1;
  var snapshot = null;
  var saveTimer = null;
  var ws = null;
  var remoteDrawing = false;

  function pushUndo() {
    undoStack.push(JSON.stringify(objects));
    if (undoStack.length > 80) undoStack.shift();
    redoStack = [];
  }

  function getPos(e) {
    var r = canvas.getBoundingClientRect();
    var cx = e.touches ? e.touches[0].clientX : e.clientX;
    var cy = e.touches ? e.touches[0].clientY : e.clientY;
    return {
      x: (cx - r.left) * (canvas.width / r.width),
      y: (cy - r.top) * (canvas.height / r.height),
    };
  }

  function drawGrid() {
    if (!showGrid) return;
    ctx.save();
    ctx.strokeStyle = 'rgba(0,0,0,0.06)';
    ctx.lineWidth = 1;
    var step = 40;
    for (var x = 0; x < canvas.width; x += step) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
    }
    for (var y = 0; y < canvas.height; y += step) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
    }
    ctx.restore();
  }

  function renderObject(o) {
    ctx.save();
    if (o.type === 'stroke') {
      ctx.globalAlpha = o.alpha != null ? o.alpha : 1;
      ctx.strokeStyle = o.color;
      ctx.lineWidth = o.size;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      if (o.erase) ctx.globalCompositeOperation = 'destination-out';
      ctx.beginPath();
      var pts = o.points || [];
      if (pts.length) {
        ctx.moveTo(pts[0].x, pts[0].y);
        for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
        ctx.stroke();
      }
    } else if (o.type === 'line' || o.type === 'arrow') {
      ctx.strokeStyle = o.color;
      ctx.lineWidth = o.size;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(o.x1, o.y1);
      ctx.lineTo(o.x2, o.y2);
      ctx.stroke();
      if (o.type === 'arrow') {
        var angle = Math.atan2(o.y2 - o.y1, o.x2 - o.x1);
        var head = 12 + o.size;
        ctx.beginPath();
        ctx.moveTo(o.x2, o.y2);
        ctx.lineTo(o.x2 - head * Math.cos(angle - 0.4), o.y2 - head * Math.sin(angle - 0.4));
        ctx.moveTo(o.x2, o.y2);
        ctx.lineTo(o.x2 - head * Math.cos(angle + 0.4), o.y2 - head * Math.sin(angle + 0.4));
        ctx.stroke();
      }
    } else if (o.type === 'rect') {
      ctx.strokeStyle = o.color;
      ctx.lineWidth = o.size;
      ctx.strokeRect(o.x, o.y, o.w, o.h);
    } else if (o.type === 'circle') {
      ctx.strokeStyle = o.color;
      ctx.lineWidth = o.size;
      ctx.beginPath();
      ctx.arc(o.cx, o.cy, o.r, 0, Math.PI * 2);
      ctx.stroke();
    } else if (o.type === 'triangle') {
      ctx.strokeStyle = o.color;
      ctx.lineWidth = o.size;
      ctx.beginPath();
      ctx.moveTo(o.x1, o.y1);
      ctx.lineTo(o.x2, o.y2);
      ctx.lineTo(o.x3, o.y3);
      ctx.closePath();
      ctx.stroke();
    } else if (o.type === 'text') {
      ctx.fillStyle = o.color;
      ctx.font = (o.size * 4 + 12) + 'px sans-serif';
      ctx.fillText(o.text, o.x, o.y);
    } else if (o.type === 'graph') {
      drawGraphObject(o);
    } else if (o.type === 'image' && o._img) {
      ctx.drawImage(o._img, o.x, o.y, o.w, o.h);
    }
    ctx.restore();
  }

  function drawGraphObject(o) {
    var x0 = o.x, y0 = o.y, w = o.w, h = o.h;
    ctx.save();
    ctx.strokeStyle = '#ccc';
    ctx.lineWidth = 1;
    ctx.strokeRect(x0, y0, w, h);
    // axes
    var midX = x0 + w / 2, midY = y0 + h / 2;
    ctx.strokeStyle = '#888';
    ctx.beginPath();
    ctx.moveTo(x0, midY); ctx.lineTo(x0 + w, midY);
    ctx.moveTo(midX, y0); ctx.lineTo(midX, y0 + h);
    ctx.stroke();
    var xmin = o.xmin, xmax = o.xmax;
    var ymin = o.ymin != null ? o.ymin : xmin;
    var ymax = o.ymax != null ? o.ymax : xmax;
    function toCanvas(x, y) {
      return {
        X: x0 + ((x - xmin) / (xmax - xmin)) * w,
        Y: y0 + h - ((y - ymin) / (ymax - ymin)) * h,
      };
    }
    ctx.strokeStyle = o.color || '#DD8826';
    ctx.lineWidth = 2;
    ctx.beginPath();
    var first = true;
    var steps = 200;
    for (var i = 0; i <= steps; i++) {
      var x = xmin + (i / steps) * (xmax - xmin);
      var y;
      try {
        y = o._fn(x);
      } catch (e) {
        continue;
      }
      if (!isFinite(y)) { first = true; continue; }
      var p = toCanvas(x, y);
      if (p.Y < y0 - 50 || p.Y > y0 + h + 50) { first = true; continue; }
      if (first) { ctx.moveTo(p.X, p.Y); first = false; }
      else ctx.lineTo(p.X, p.Y);
    }
    ctx.stroke();
    ctx.fillStyle = '#666';
    ctx.font = '12px sans-serif';
    ctx.fillText('f(x)=' + (o.expr || ''), x0 + 6, y0 + 14);
    ctx.restore();
  }

  function compileFn(expr) {
    // safe-ish math expression
    var cleaned = String(expr).replace(/[^0-9xX+\-*/().,\sMathsincotaqrtpowe]/g, '');
    cleaned = cleaned.replace(/x/gi, 'x');
    // eslint-disable-next-line no-new-func
    return new Function('x', 'with(Math){ return (' + cleaned + '); }');
  }

  function redraw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawGrid();
    objects.forEach(function (o) {
      if (o.type === 'image' && o.src && !o._img) {
        var img = new Image();
        img.onload = function () { o._img = img; redraw(); };
        img.src = o.src;
      }
      if (o.type === 'graph' && o.expr && !o._fn) {
        try { o._fn = compileFn(o.expr); } catch (e) { o._fn = function () { return 0; }; }
      }
      renderObject(o);
    });
    renderMathLayer();
  }

  function renderMathLayer() {
    if (!mathLayer) return;
    mathLayer.innerHTML = '';
    var r = canvas.getBoundingClientRect();
    var sx = r.width / canvas.width;
    var sy = r.height / canvas.height;
    objects.filter(function (o) { return o.type === 'math'; }).forEach(function (o, idx) {
      var div = document.createElement('div');
      div.className = 'wb-math-item';
      div.style.left = (o.x * sx) + 'px';
      div.style.top = (o.y * sy) + 'px';
      div.dataset.idx = String(objects.indexOf(o));
      try {
        if (window.katex) {
          katex.render(o.latex, div, { throwOnError: false, displayMode: false });
        } else {
          div.textContent = o.latex;
        }
      } catch (e) {
        div.textContent = o.latex;
      }
      mathLayer.appendChild(div);
    });
  }

  function broadcast(payload) {
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify(payload));
    }
  }

  function scheduleSave() {
    if (!canEdit) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveContent, 1200);
  }

  function saveContent() {
    if (!canEdit) return;
    var content = { version: 1, objects: objects.map(serializeObj) };
    fetch(apiUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf,
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        content: content,
        students_can_edit: document.getElementById('wbStudentsEdit')
          ? document.getElementById('wbStudentsEdit').checked
          : undefined,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        setStatus('saved');
        broadcast({ type: 'content_sync', content: content });
      })
      .catch(function () { setStatus('error'); });
  }

  function serializeObj(o) {
    var copy = {};
    Object.keys(o).forEach(function (k) {
      if (k === '_img' || k === '_fn') return;
      copy[k] = o[k];
    });
    return copy;
  }

  function setStatus(s) {
    var el = document.getElementById('wbStatus');
    if (!el) return;
    if (s === 'online') { el.textContent = '● en ligne'; el.className = 'wb-status small online'; }
    else if (s === 'saved') { el.textContent = '● sauvé'; el.className = 'wb-status small online'; }
    else if (s === 'error') { el.textContent = '● erreur'; el.className = 'wb-status small offline'; }
    else { el.textContent = '●'; el.className = 'wb-status small offline'; }
  }

  function loadContent() {
    fetch(apiUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        objects = (data.content && data.content.objects) || [];
        redraw();
      })
      .catch(function () { redraw(); });
  }

  // --- events ---
  function onStart(e) {
    if (!canEdit) return;
    e.preventDefault();
    var p = getPos(e);
    drawing = true;
    startX = p.x; startY = p.y;
    snapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);

    if (tool === 'text') {
      drawing = false;
      var t = prompt('Texte :');
      if (t) {
        pushUndo();
        var obj = { type: 'text', text: t, x: p.x, y: p.y, color: color, size: size };
        objects.push(obj);
        redraw();
        broadcast({ type: 'object', object: obj });
        scheduleSave();
      }
      return;
    }

    if (tool === 'pencil' || tool === 'pen' || tool === 'highlighter' || tool === 'eraser') {
      pushUndo();
      currentPath = {
        type: 'stroke',
        color: tool === 'eraser' ? '#000' : color,
        size: tool === 'pen' ? size * 1.4 : tool === 'highlighter' ? size * 3 : size,
        alpha: tool === 'highlighter' ? 0.35 : 1,
        erase: tool === 'eraser',
        points: [{ x: p.x, y: p.y }],
      };
    }
  }

  function onMove(e) {
    if (!drawing || !canEdit) return;
    e.preventDefault();
    var p = getPos(e);
    if (currentPath) {
      currentPath.points.push({ x: p.x, y: p.y });
      redraw();
      renderObject(currentPath);
      return;
    }
    // shape preview
    if (snapshot) ctx.putImageData(snapshot, 0, 0);
    var preview = shapeFromDrag(startX, startY, p.x, p.y);
    if (preview) renderObject(preview);
  }

  function shapeFromDrag(x1, y1, x2, y2) {
    if (tool === 'line' || tool === 'arrow') {
      return { type: tool, x1: x1, y1: y1, x2: x2, y2: y2, color: color, size: size };
    }
    if (tool === 'rect') {
      return { type: 'rect', x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), color: color, size: size };
    }
    if (tool === 'circle') {
      var r = Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2));
      return { type: 'circle', cx: x1, cy: y1, r: r, color: color, size: size };
    }
    if (tool === 'triangle') {
      return { type: 'triangle', x1: x1, y1: y2, x2: x2, y2: y2, x3: (x1 + x2) / 2, y3: y1, color: color, size: size };
    }
    return null;
  }

  function onEnd(e) {
    if (!drawing || !canEdit) return;
    drawing = false;
    var p = e && (e.changedTouches || e.touches) ? getPos(e.changedTouches ? e : e) : { x: startX, y: startY };
    if (e && !e.touches && e.clientX != null) p = getPos(e);

    if (currentPath) {
      objects.push(currentPath);
      broadcast({ type: 'object', object: currentPath });
      currentPath = null;
      scheduleSave();
      redraw();
      return;
    }
    var shape = shapeFromDrag(startX, startY, p.x, p.y);
    if (shape && (tool === 'line' || tool === 'arrow' || tool === 'rect' || tool === 'circle' || tool === 'triangle')) {
      pushUndo();
      objects.push(shape);
      broadcast({ type: 'object', object: shape });
      scheduleSave();
      redraw();
    }
  }

  canvas.addEventListener('mousedown', onStart);
  canvas.addEventListener('mousemove', onMove);
  canvas.addEventListener('mouseup', onEnd);
  canvas.addEventListener('mouseleave', function () { if (drawing) onEnd(); });
  canvas.addEventListener('touchstart', onStart, { passive: false });
  canvas.addEventListener('touchmove', onMove, { passive: false });
  canvas.addEventListener('touchend', onEnd);

  // tools
  document.querySelectorAll('.wb-tool[data-tool]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (!canEdit && btn.dataset.tool) return;
      document.querySelectorAll('.wb-tool[data-tool]').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      tool = btn.dataset.tool;
    });
  });

  var colorEl = document.getElementById('wbColor');
  var sizeEl = document.getElementById('wbSize');
  if (colorEl) colorEl.addEventListener('input', function () { color = colorEl.value; });
  if (sizeEl) sizeEl.addEventListener('input', function () { size = parseInt(sizeEl.value, 10) || 4; });

  document.getElementById('wbUndo').addEventListener('click', function () {
    if (!canEdit || !undoStack.length) return;
    redoStack.push(JSON.stringify(objects));
    objects = JSON.parse(undoStack.pop());
    redraw();
    scheduleSave();
    broadcast({ type: 'content_sync', content: { version: 1, objects: objects.map(serializeObj) } });
  });
  document.getElementById('wbRedo').addEventListener('click', function () {
    if (!canEdit || !redoStack.length) return;
    undoStack.push(JSON.stringify(objects));
    objects = JSON.parse(redoStack.pop());
    redraw();
    scheduleSave();
  });
  document.getElementById('wbClear').addEventListener('click', function () {
    if (!canEdit) return;
    if (!confirm('Effacer tout le tableau ?')) return;
    pushUndo();
    objects = [];
    redraw();
    scheduleSave();
    broadcast({ type: 'clear' });
  });
  document.getElementById('wbGridToggle').addEventListener('click', function () {
    showGrid = !showGrid;
    redraw();
  });

  function applyZoom() {
    wrap.style.transform = 'scale(' + zoom + ')';
    wrap.style.transformOrigin = 'top left';
    document.getElementById('wbZoomLabel').textContent = Math.round(zoom * 100) + '%';
  }
  document.getElementById('wbZoomIn').addEventListener('click', function () { zoom = Math.min(2.5, zoom + 0.1); applyZoom(); });
  document.getElementById('wbZoomOut').addEventListener('click', function () { zoom = Math.max(0.4, zoom - 0.1); applyZoom(); });
  document.getElementById('wbZoomReset').addEventListener('click', function () { zoom = 1; applyZoom(); });

  document.getElementById('wbSaveBtn').addEventListener('click', saveContent);
  document.getElementById('wbExportPng').addEventListener('click', function () {
    var a = document.createElement('a');
    a.download = 'edubac-whiteboard-' + boardId + '.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  });

  // Math
  var mathModal = document.getElementById('wbMathModal');
  var mathInput = document.getElementById('wbMathInput');
  var mathPreview = document.getElementById('wbMathPreview');
  document.getElementById('wbMathBtn').addEventListener('click', function () {
    if (!canEdit) return;
    if (window.bootstrap) new bootstrap.Modal(mathModal).show();
    else mathModal.classList.add('show');
  });
  document.querySelectorAll('.wb-math-snip').forEach(function (b) {
    b.addEventListener('click', function () {
      mathInput.value += b.dataset.s;
      previewMath();
    });
  });
  function previewMath() {
    if (!mathPreview) return;
    try {
      if (window.katex) katex.render(mathInput.value || '…', mathPreview, { throwOnError: false });
      else mathPreview.textContent = mathInput.value;
    } catch (e) { mathPreview.textContent = mathInput.value; }
  }
  if (mathInput) mathInput.addEventListener('input', previewMath);
  document.getElementById('wbMathPlace').addEventListener('click', function () {
    var latex = (mathInput.value || '').trim();
    if (!latex) return;
    pushUndo();
    var obj = { type: 'math', latex: latex, x: 80, y: 80 + objects.filter(function (o) { return o.type === 'math'; }).length * 40 };
    objects.push(obj);
    redraw();
    scheduleSave();
    broadcast({ type: 'object', object: obj });
    if (window.bootstrap) bootstrap.Modal.getInstance(mathModal).hide();
  });

  // Graph
  var graphModal = document.getElementById('wbGraphModal');
  document.getElementById('wbGraphBtn').addEventListener('click', function () {
    if (!canEdit) return;
    if (window.bootstrap) new bootstrap.Modal(graphModal).show();
  });
  document.getElementById('wbGraphPlace').addEventListener('click', function () {
    var expr = document.getElementById('wbGraphFn').value.trim();
    var xmin = parseFloat(document.getElementById('wbGraphXmin').value);
    var xmax = parseFloat(document.getElementById('wbGraphXmax').value);
    if (!expr || !isFinite(xmin) || !isFinite(xmax) || xmin >= xmax) return;
    var fn;
    try { fn = compileFn(expr); fn(0); } catch (e) { alert('Expression invalide'); return; }
    pushUndo();
    var obj = {
      type: 'graph', expr: expr, xmin: xmin, xmax: xmax, ymin: xmin, ymax: xmax,
      x: 100, y: 100, w: 400, h: 300, color: color, _fn: fn,
    };
    objects.push(obj);
    redraw();
    scheduleSave();
    broadcast({ type: 'object', object: serializeObj(obj) });
    if (window.bootstrap) bootstrap.Modal.getInstance(graphModal).hide();
  });

  // Image
  document.getElementById('wbImageBtn').addEventListener('click', function () {
    if (!canEdit) return;
    document.getElementById('wbImageInput').click();
  });
  document.getElementById('wbImageInput').addEventListener('change', function (e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      var src = reader.result;
      var img = new Image();
      img.onload = function () {
        pushUndo();
        var maxW = 500;
        var w = Math.min(maxW, img.width);
        var h = img.height * (w / img.width);
        var obj = { type: 'image', src: src, x: 60, y: 60, w: w, h: h, _img: img };
        objects.push(obj);
        redraw();
        scheduleSave();
        broadcast({ type: 'object', object: serializeObj(obj) });
      };
      img.src = src;
    };
    reader.readAsDataURL(file);
  });

  // WebSocket
  function connectWs() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
      ws = new WebSocket(proto + '//' + location.host + wsPath);
    } catch (e) {
      setStatus('offline');
      return;
    }
    ws.onopen = function () { setStatus('online'); };
    ws.onclose = function () { setStatus('offline'); setTimeout(connectWs, 3000); };
    ws.onmessage = function (ev) {
      try {
        var data = JSON.parse(ev.data);
      } catch (e) { return; }
      if (data.type === 'object' && data.object) {
        objects.push(data.object);
        redraw();
      } else if (data.type === 'clear') {
        objects = [];
        redraw();
      } else if (data.type === 'content_sync' && data.content) {
        objects = data.content.objects || [];
        redraw();
      }
    };
  }

  // init
  if (!canEdit) {
    document.querySelectorAll('.wb-tool').forEach(function (b) {
      if (b.id !== 'wbExportPng') b.style.opacity = '0.45';
    });
  }
  loadContent();
  connectWs();
  window.addEventListener('beforeunload', function () {
    if (canEdit) saveContent();
  });
})();
