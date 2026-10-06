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
  var contentReady = false;
  var model = window.EduBacObjects;
  var selectedId = null;
  var dragging = null;
  var dragBefore = null;
  var lastPointer = null;
  var editTarget = null;
  var editor = document.getElementById('wbObjectEditor');

  function selected() { return objects.find(function (o) { return o.id === selectedId; }) || null; }
  function notifySelection() {
    var o = selected(), bar = document.getElementById('wbSelectionBar');
    if (bar) bar.hidden = !o;
    var label = document.getElementById('wbSelectionLabel');
    if (label) label.textContent = o ? (o.latex || o.text || o.expr || o.type) : '';
    window.dispatchEvent(new CustomEvent('edubac:selection', { detail: o ? serializeObj(o) : null }));
  }
  function commit() {
    redraw();
    scheduleSave();
    broadcast({ type:'content_sync', content:{version:1, objects:objects.map(serializeObj)} });
  }
  function deleteSelected() {
    if (!canEdit || !contentReady || !selected()) return;
    if (!confirm('Supprimer cet élément ?')) return;
    pushUndo();
    objects = objects.filter(function(o){return o.id !== selectedId;});
    selectedId = null;
    notifySelection();
    commit();
  }
  function editSelected() {
    var o=selected();
    if (!canEdit || !contentReady || !o || !editor) return;
    editTarget=o.id;
    var fields=document.getElementById('wbEditorFields');
    fields.replaceChildren();
    var keys=['color','size','x','y','w','h','x1','y1','x2','y2','x3','y3','cx','cy','r','angle','xmin','xmax','ymin','ymax','alpha'];
    if(o.type==='text' || o.type==='note') keys.unshift('text');
    if(o.type==='math') keys.unshift('latex');
    if(o.type==='graph') keys.unshift('expr');
    if(o.type==='image') keys.unshift('src');
    if(o.type==='stroke') keys.unshift('points');
    var names={text:'Texte',latex:'Équation LaTeX',expr:'Fonction',src:'Image (URL ou données)',points:'Points (JSON)',color:'Couleur',size:'Épaisseur',w:'Largeur',h:'Hauteur',r:'Rayon',angle:'Angle (0 à 180°)',alpha:'Opacité'};
    keys.forEach(function(k){
      if(o[k]==null) return;
      var label=document.createElement('label'); label.textContent=names[k] || k;
      var input=document.createElement(['text','latex','points'].includes(k)?'textarea':'input');
      input.name=k; input.value=k==='points'?JSON.stringify(o[k]):o[k];
      if(typeof o[k]==='number') {input.type='number';input.step='any';}
      if(k==='color') input.type='color';
      if(['text','latex','points','src','expr'].includes(k)) label.style.gridColumn='1 / -1';
      label.appendChild(input);fields.appendChild(label);
    });
    document.getElementById('wbEditorError').textContent='';
    editor.showModal();
  }
  document.getElementById('wbEditSelected').addEventListener('click',editSelected);
  document.getElementById('wbDeleteSelected').addEventListener('click',deleteSelected);
  document.getElementById('wbEditorCancel').addEventListener('click',function(){editor.close();});
  document.getElementById('wbEditorForm').addEventListener('submit',function(e){
    e.preventDefault();
    var o=objects.find(function(item){return item.id===editTarget;});
    if(!canEdit || !contentReady || !o) return;
    var copy=serializeObj(o);
    try {
      document.querySelectorAll('#wbEditorFields [name]').forEach(function(input){
        var key=input.name, value=input.value;
        if(key==='points') {
          value=JSON.parse(value);
          if(!Array.isArray(value) || !value.length || value.length>20000 || value.some(function(p){return !p || !Number.isFinite(p.x) || !Number.isFinite(p.y);})) throw new Error('Points invalides.');
        } else if(typeof o[key]==='number') {
          value=Number(value);
          if(!Number.isFinite(value) || (['w','h','r','size'].includes(key) && value<=0) || (key==='alpha' && (value<0 || value>1))) throw new Error('Dimensions invalides.');
          if(key==='angle' && (value<0 || value>180))throw new Error('L’angle doit être compris entre 0 et 180°.');
        }
        if(key==='src' && !/^(data:image\/(?:png|jpeg|webp|gif);base64,|https?:\/\/|\/)/i.test(value)) throw new Error('Adresse d’image invalide.');
        copy[key]=value;
      });
      if(copy.type==='graph') {
        if(copy.xmin>=copy.xmax || copy.ymin>=copy.ymax) throw new Error('Bornes du graphique invalides.');
        var fn=compileFn(copy.expr);fn(0);copy._fn=fn;
      }
      pushUndo();
      objects[objects.indexOf(o)]=copy;
      editor.close();notifySelection();commit();
    } catch(err) { document.getElementById('wbEditorError').textContent=err.message || 'Valeur invalide.'; }
  });

  function pushUndo() {
    undoStack.push(model.state(objects));
    if (undoStack.length > 80) undoStack.shift();
    redoStack = [];
  }

  function getPos(e) {
    var r = canvas.getBoundingClientRect();
    var touch = e.touches && e.touches[0] || e.changedTouches && e.changedTouches[0];
    var cx = touch ? touch.clientX : e.clientX;
    var cy = touch ? touch.clientY : e.clientY;
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
      if(o.geometry==='ruler')drawRuler(o);
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
      ctx.arc(o.cx, o.cy, o.r, o.geometry==='protractor'?Math.PI:0, Math.PI*2);
      ctx.stroke();
      if(o.geometry==='protractor')drawProtractor(o);
    } else if (o.type === 'triangle') {
      ctx.strokeStyle = o.color;
      ctx.lineWidth = o.size;
      ctx.beginPath();
      ctx.moveTo(o.x1, o.y1);
      ctx.lineTo(o.x2, o.y2);
      ctx.lineTo(o.x3, o.y3);
      ctx.closePath();
      ctx.stroke();
    } else if (o.type === 'text' || o.type === 'note') {
      if(o.type==='note' || o.note) {
        var box=model.bounds(o);
        ctx.fillStyle='#f4e6cb';ctx.fillRect(box.x-8,box.y-8,box.w+16,box.h+16);
      }
      ctx.fillStyle = o.color;
      ctx.font = (o.size * 4 + 12) + 'px sans-serif';
      String(o.text || '').split('\n').forEach(function(line,i){ctx.fillText(line,o.x,o.y+i*(o.size*4+12)*1.3);});
    } else if (o.type === 'graph') {
      drawGraphObject(o);
    } else if (o.type === 'image' && o._img) {
      ctx.drawImage(o._img, o.x, o.y, o.w, o.h);
    } else if(o.type==='image' && o._imgError) {
      ctx.strokeStyle='#a45e17';ctx.strokeRect(o.x,o.y,o.w,o.h);
      ctx.fillStyle='#a45e17';ctx.font='16px sans-serif';ctx.fillText('Image indisponible · modifier pour réessayer',o.x+8,o.y+24);
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

  function drawRuler(o) {
    var length=Math.hypot(o.x2-o.x1,o.y2-o.y1), angle=Math.atan2(o.y2-o.y1,o.x2-o.x1);
    if(length<1)return;
    ctx.save();ctx.translate(o.x1,o.y1);ctx.rotate(angle);
    ctx.strokeStyle=o.color;ctx.fillStyle=o.color;ctx.lineWidth=1;ctx.font='12px sans-serif';
    // One graduation = 10 logical canvas units, not physical centimetres.
    for(var n=0;n<=Math.min(length,10000);n+=10){
      var major=n%50===0;
      ctx.beginPath();ctx.moveTo(n,0);ctx.lineTo(n,major?-16:-8);ctx.stroke();
      if(major)ctx.fillText(String(n),n-4,-20);
    }
    ctx.fillText(Math.round(length)+' unités tableau',Math.max(0,length/2-50),22);
    ctx.restore();
  }

  function drawProtractor(o) {
    var radius=o.r, angle=Math.max(0,Math.min(180,o.angle==null?60:o.angle));
    ctx.save();ctx.strokeStyle=o.color;ctx.fillStyle=o.color;ctx.lineWidth=1;ctx.font='12px sans-serif';
    ctx.beginPath();ctx.moveTo(o.cx-radius,o.cy);ctx.lineTo(o.cx+radius,o.cy);ctx.stroke();
    for(var degree=0;degree<=180;degree+=10) {
      var a=degree*Math.PI/180, major=degree%30===0, inner=Math.max(0,radius-(major?16:8));
      ctx.beginPath();ctx.moveTo(o.cx+radius*Math.cos(a),o.cy-radius*Math.sin(a));
      ctx.lineTo(o.cx+inner*Math.cos(a),o.cy-inner*Math.sin(a));ctx.stroke();
      if(major && radius>50)ctx.fillText(degree+'°',o.cx+(radius-30)*Math.cos(a)-10,o.cy-(radius-30)*Math.sin(a)-3);
    }
    var rad=angle*Math.PI/180;
    ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(o.cx+radius*.75,o.cy);ctx.lineTo(o.cx,o.cy);ctx.lineTo(o.cx+radius*.75*Math.cos(rad),o.cy-radius*.75*Math.sin(rad));ctx.stroke();
    ctx.fillText(angle+'°',o.cx+8,o.cy-12);ctx.restore();
  }

  function compileFn(expr) {
    // safe-ish math expression
    var cleaned = String(expr).replace(/[^0-9xX+\-*/().,\sMathsincotaqrtpowe]/g, '');
    cleaned = cleaned.replace(/x/gi, 'x');
    // eslint-disable-next-line no-new-func
    return new Function('x', 'with(Math){ return (' + cleaned + '); }');
  }

  function redraw() {
    document.getElementById('wbUndo').disabled=!canEdit || !undoStack.length;
    document.getElementById('wbRedo').disabled=!canEdit || !redoStack.length;
    model.normalize(objects);
    var bottom = objects.reduce(function(max,o){var b=model.bounds(o);return Math.max(max,b.y+b.h+80);},1000);
    var right = objects.reduce(function(max,o){var b=model.bounds(o);return Math.max(max,b.x+b.w+80);},1600);
    var nextW=Math.ceil(right), nextH=Math.ceil(bottom);
    if(canvas.width!==nextW || canvas.height!==nextH) {
      canvas.width=nextW;canvas.height=nextH;
      wrap.style.aspectRatio=nextW+' / '+nextH;
      wrap.style.minWidth=(nextW/2)+'px';
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#fcfaf5';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawGrid();
    objects.forEach(function (o) {
      if (o.type === 'image' && o.src && !o._img && !o._loading && !o._imgError) {
        o._loading = true;
        var img = new Image();
        img.onload = function () { o._img = img; o._loading=false; redraw(); };
        img.onerror = function () { o._loading=false; o._imgError=true; redraw(); };
        img.src = o.src;
      }
      if (o.type === 'graph' && o.expr && !o._fn) {
        try { o._fn = compileFn(o.expr); } catch (e) { o._fn = function () { return 0; }; }
      }
      renderObject(o);
    });
    renderMathLayer();
    var selection=selected();
    if(selection) {
      var b=model.bounds(selection);ctx.save();ctx.strokeStyle='#a45e17';ctx.lineWidth=2;ctx.setLineDash([7,4]);
      ctx.strokeRect(b.x-8,b.y-8,Math.max(8,b.w)+16,Math.max(8,b.h)+16);ctx.restore();
    }
  }

  function renderMathLayer() {
    if (!mathLayer) return;
    mathLayer.innerHTML = '';
    var r = canvas.getBoundingClientRect();
    var sx = canvas.clientWidth / canvas.width;
    var sy = canvas.clientHeight / canvas.height;
    objects.filter(function (o) { return o.type === 'math'; }).forEach(function (o, idx) {
      var div = document.createElement('div');
      div.className = 'wb-math-item';
      div.style.left = (o.x * sx) + 'px';
      div.style.top = (o.y * sy) + 'px';
      div.dataset.idx = String(objects.indexOf(o));
      div.dataset.objectId = o.id;
      try {
        if (window.katex) {
          katex.render(o.latex, div, { throwOnError: false, displayMode: false, trust:false, maxExpand:1000 });
        } else {
          div.textContent = o.latex;
        }
      } catch (e) {
        div.textContent = o.latex;
      }
      mathLayer.appendChild(div);
      o._width=div.offsetWidth/sx;
      o._height=div.offsetHeight/sy;
    });
  }

  function broadcast(payload) {
    if(!canEdit && ['object','content_sync','clear'].includes(payload.type))return;
    if(payload.type==='object' && payload.object && !payload.object.id) payload.object.id=model.id();
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
    if (!canEdit || !contentReady) return;
    setStatus('saving');
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
      .then(function (r) { if(!r.ok) throw new Error('Sauvegarde refusée'); return r.json(); })
      .then(function () {
        setStatus('saved');
        broadcast({ type: 'content_sync', content: content });
      })
      .catch(function () { setStatus('error'); });
  }

  function serializeObj(o) {
    return model.serialize(o);
  }

  function setStatus(s) {
    var el = document.getElementById('wbStatus');
    if (!el) return;
    if (s === 'online') { el.textContent = '● en ligne'; el.className = 'wb-status small online'; }
    else if (s === 'saved') { el.textContent = '● sauvé'; el.className = 'wb-status small online'; }
    else if (s === 'error') { el.textContent = '● erreur'; el.className = 'wb-status small offline'; }
    else if (s === 'loading') { el.textContent = 'Chargement…'; el.className = 'wb-status small'; }
    else if (s === 'saving') { el.textContent = 'Sauvegarde…'; el.className = 'wb-status small'; }
    else { el.textContent = '●'; el.className = 'wb-status small offline'; }
  }

  function loadContent() {
    setStatus('loading');
    fetch(apiUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if(!r.ok) throw new Error('Chargement refusé');return r.json(); })
      .then(function (data) {
        objects = model.normalize((data.content && data.content.objects) || []);
        contentReady=true;
        setStatus('saved');
        document.getElementById('wbLoadError').hidden=true;
        redraw();
      })
      .catch(function () { document.getElementById('wbLoadError').hidden=false;redraw(); });
  }

  // --- events ---
  function onStart(e) {
    var p = getPos(e);
    lastPointer=p;
    if(tool==='select') {
      e.preventDefault();
      var hit=objects.slice().reverse().find(function(o){return model.hit(o,p,10);});
      selectedId=hit?hit.id:null;
      notifySelection();redraw();
      if(canEdit && contentReady && hit) {dragging=hit;dragBefore=model.state(objects);}
      return;
    }
    if (!canEdit || !contentReady) return;
    e.preventDefault();
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
    if(dragging && canEdit) {
      e.preventDefault();var pos=getPos(e);
      model.move(dragging,pos.x-lastPointer.x,pos.y-lastPointer.y);lastPointer=pos;
      redraw();return;
    }
    if (!drawing || !canEdit) return;
    e.preventDefault();
    var p = getPos(e);
    lastPointer=p;
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
    if (tool === 'line' || tool === 'arrow' || tool==='ruler') {
      var line={ type: tool==='ruler'?'line':tool, x1: x1, y1: y1, x2: x2, y2: y2, color: color, size: size };
      if(tool==='ruler')line.geometry='ruler';
      return line;
    }
    if (tool === 'rect') {
      return { type: 'rect', x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), color: color, size: size };
    }
    if (tool === 'circle' || tool==='protractor') {
      var r = Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2));
      var circle={ type: 'circle', cx: x1, cy: y1, r: r, color: color, size: size };
      if(tool==='protractor'){circle.geometry='protractor';circle.angle=60;}
      return circle;
    }
    if (tool === 'triangle') {
      return { type: 'triangle', x1: x1, y1: y2, x2: x2, y2: y2, x3: (x1 + x2) / 2, y3: y1, color: color, size: size };
    }
    return null;
  }

  function onEnd(e) {
    if(dragging) {
      if(canEdit && model.state(objects)!==dragBefore) {
        undoStack.push(dragBefore);if(undoStack.length>80)undoStack.shift();redoStack=[];commit();
      }
      dragging=null;dragBefore=null;return;
    }
    if (!drawing || !canEdit) return;
    drawing = false;
    var p = e && (e.changedTouches || e.touches) ? getPos(e) : (lastPointer || { x: startX, y: startY });
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
    if (shape && ['line','arrow','rect','circle','triangle','ruler','protractor'].includes(tool)) {
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
  canvas.addEventListener('mouseleave', function () { if (drawing || dragging) onEnd(); });
  canvas.addEventListener('touchstart', onStart, { passive: false });
  canvas.addEventListener('touchmove', onMove, { passive: false });
  canvas.addEventListener('touchend', onEnd);
  canvas.addEventListener('touchcancel',onEnd);
  canvas.addEventListener('dblclick',function(){if(tool==='select') editSelected();});
  document.addEventListener('keydown',function(e){
    if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || e.target.isContentEditable || editor.open) return;
    if(e.key==='Delete' || e.key==='Backspace') {if(selected()){e.preventDefault();deleteSelected();}}
    if(e.key==='Escape') {selectedId=null;notifySelection();redraw();}
  });

  // tools
  document.querySelectorAll('.wb-tool[data-tool]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (!canEdit && btn.dataset.tool!=='select') return;
      document.querySelectorAll('.wb-tool[data-tool]').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      tool = btn.dataset.tool;
      canvas.style.cursor=tool==='select'?'default':'crosshair';
      btn.setAttribute('aria-pressed','true');
    });
  });

  var colorEl = document.getElementById('wbColor');
  var sizeEl = document.getElementById('wbSize');
  if (colorEl) colorEl.addEventListener('input', function () { color = colorEl.value; });
  if (sizeEl) sizeEl.addEventListener('input', function () { size = parseInt(sizeEl.value, 10) || 4; });

  document.getElementById('wbUndo').addEventListener('click', function () {
    if (!canEdit || !undoStack.length) return;
    redoStack.push(model.state(objects));
    objects = JSON.parse(undoStack.pop());
    redraw();
    notifySelection();
    scheduleSave();
    broadcast({ type: 'content_sync', content: { version: 1, objects: objects.map(serializeObj) } });
  });
  document.getElementById('wbRedo').addEventListener('click', function () {
    if (!canEdit || !redoStack.length) return;
    undoStack.push(model.state(objects));
    objects = JSON.parse(redoStack.pop());
    redraw();
    scheduleSave();
    notifySelection();
    broadcast({ type:'content_sync',content:{version:1,objects:objects.map(serializeObj)} });
  });
  document.getElementById('wbClear').addEventListener('click', function () {
    if (!canEdit || !contentReady) return;
    if (!confirm('Effacer tout le tableau ?')) return;
    pushUndo();
    objects = [];
    selectedId=null;notifySelection();
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
    try {
    var a = document.createElement('a');
    a.download = 'edubac-whiteboard-' + boardId + '.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
    } catch(err) { alert('Export indisponible : une image externe bloque la capture. Remplace-la par un fichier importé.'); }
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
    if(!canEdit || !contentReady) return;
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
    if(!canEdit || !contentReady) return;
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
    if(!canEdit || !contentReady) return;
    var file = e.target.files && e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      if(!canEdit || !contentReady)return;
      var src = reader.result;
      var img = new Image();
      img.onload = function () {
        if(!canEdit || !contentReady)return;
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
        if(data.object.id && objects.some(function(o){return o.id===data.object.id;})) return;
        objects.push(data.object);
        redraw();
      } else if (data.type === 'clear') {
        objects = [];
        redraw();
      } else if (data.type === 'content_sync' && data.content) {
        objects = data.content.objects || [];
        contentReady=true;
        dragging=null;drawing=false;currentPath=null;
        redraw();
      }
      notifySelection();
    };
  }

  // init
  if (!canEdit) {
    tool='select';
    document.querySelectorAll('.wb-tool').forEach(function (b) {
      if(b.dataset.tool==='select') b.classList.add('active');
      else {b.disabled=true;b.classList.remove('active');}
    });
  }
  document.getElementById('wbLoadRetry').addEventListener('click',loadContent);
  var permissionToggle=document.getElementById('wbStudentsEdit');
  if(permissionToggle) permissionToggle.addEventListener('change',saveContent);
  window.EduBacBoard = {
    canEdit:canEdit,
    getObjects:function(){return objects.map(serializeObj);},
    getSelected:function(){var o=selected();return o?serializeObj(o):null;},
    snapshot:function(){return canvas.toDataURL('image/png');},
    addActions:function(actions){
      if(!canEdit || !contentReady) return [];
      var additions=model.actions(actions,objects,canvas.width);
      if(!additions.length) return [];
      pushUndo();
      var original=objects.slice();
      objects=objects.concat(additions);
      redraw();
      // KaTeX can be taller than an estimate (fractions, matrices).
      // Re-check actual DOM-measured bounds before committing a single undo batch.
      var placed=original.map(model.bounds);
      additions.forEach(function(o){
        var b=model.bounds(o), tries=0;
        while(placed.some(function(p){return b.x<p.x+p.w+24 && b.x+b.w+24>p.x && b.y<p.y+p.h+24 && b.y+b.h+24>p.y;}) && tries++<10000) {
          model.move(o,0,40);b=model.bounds(o);
        }
        placed.push(b);
      });
      commit();
      return additions.map(serializeObj);
    }
  };
  window.addEventListener('resize',redraw);
  loadContent();
  connectWs();
  window.addEventListener('beforeunload', function () {
    if (canEdit) saveContent();
  });
})();
