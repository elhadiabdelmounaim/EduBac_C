/**
 * Quiz correction whiteboard — objets, connexions, chat IA, undo/redo, autosave.
 */
(function () {
  'use strict';

  var shell = document.getElementById('qwbShell');
  if (!shell) return;

  var apiUrl = shell.getAttribute('data-api');
  var ruleOnly = shell.getAttribute('data-rule-only') === '1';
  var csrf = shell.getAttribute('data-csrf') || '';
  var canvas = document.getElementById('qwbCanvas');
  var wrap = document.getElementById('qwbCanvasWrap');
  var svgLinks = document.getElementById('qwbLinks');
  var statusEl = document.getElementById('qwbStatus');
  var warnEl = document.getElementById('qwbWarning');
  var linear = document.getElementById('qwbLinear');
  var editText = document.getElementById('qwbEditText');
  var btnDup = document.getElementById('qwbDup');
  var btnLock = document.getElementById('qwbLock');
  var btnDel = document.getElementById('qwbDel');
  var chatLog = document.getElementById('qwbChatLog');
  var chatInput = document.getElementById('qwbChatInput');
  var chatSend = document.getElementById('qwbChatSend');
  var proposalsBox = document.getElementById('qwbProposals');

  var state = {
    document: { version: 1, title: 'Correction', elements: [], connections: [] },
    revision: 0,
    selectedId: null,
    scale: 1,
    panX: 0,
    panY: 0,
    undo: [],
    redo: [],
    saveTimer: null,
    dirty: false,
    renderedRules: {},
  };

  function setStatus(t) { if (statusEl) statusEl.textContent = t; }
  function setWarning(t) {
    if (!warnEl) return;
    if (t) { warnEl.textContent = t; warnEl.classList.remove('d-none'); }
    else warnEl.classList.add('d-none');
  }
  function escapeText(s) { return String(s == null ? '' : s); }

  function pushUndo() {
    state.undo.push(JSON.stringify(state.document));
    if (state.undo.length > 100) state.undo.shift();
    state.redo = [];
  }

  function applyTransform() {
    var t = 'translate(' + state.panX + 'px,' + state.panY + 'px) scale(' + state.scale + ')';
    canvas.style.transform = t;
    if (svgLinks) svgLinks.style.transform = t;
  }

  function contentOf(el) {
    var t = el.type;
    if (t === 'formula' || t === 'calculation') return el.latex || '';
    if (t === 'step') return (el.label ? el.label + ' — ' : '') + (el.text || '');
    if (t === 'table') return (el.headers || []).join(' | ');
    return el.text || '';
  }

  function renderKatex(node, latex) {
    node.textContent = latex;
    if (window.katex) {
      try {
        window.katex.render(latex, node, {
          throwOnError: false, trust: false, strict: 'ignore', maxExpand: 100
        });
      } catch (e) { node.textContent = latex; }
    } else {
      node.textContent = /^\s*\$/.test(latex) ? latex : '$' + latex + '$';
    }
  }

  function anchorPoint(el, anchor) {
    var x = (el.position && el.position.x) || 0;
    var y = (el.position && el.position.y) || 0;
    var w = (el.size && el.size.width) || 200;
    var h = (el.size && el.size.height) || 80;
    if (anchor === 'top') return { x: x + w / 2, y: y };
    if (anchor === 'bottom') return { x: x + w / 2, y: y + h };
    if (anchor === 'left') return { x: x, y: y + h / 2 };
    return { x: x + w, y: y + h / 2 };
  }

  function renderConnections() {
    if (!svgLinks) return;
    while (svgLinks.firstChild) svgLinks.removeChild(svgLinks.firstChild);
    var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    var marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'qwbArrow');
    marker.setAttribute('markerWidth', '8');
    marker.setAttribute('markerHeight', '8');
    marker.setAttribute('refX', '6');
    marker.setAttribute('refY', '3');
    marker.setAttribute('orient', 'auto');
    var mp = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    mp.setAttribute('d', 'M0,0 L6,3 L0,6 Z');
    mp.setAttribute('fill', '#5c2d7a');
    marker.appendChild(mp);
    defs.appendChild(marker);
    svgLinks.appendChild(defs);

    var byId = {};
    (state.document.elements || []).forEach(function (e) { byId[e.id] = e; });
    (state.document.connections || []).forEach(function (c) {
      var a = byId[c.from && c.from.elementId];
      var b = byId[c.to && c.to.elementId];
      if (!a || !b) return;
      var p1 = anchorPoint(a, (c.from && c.from.anchor) || 'right');
      var p2 = anchorPoint(b, (c.to && c.to.anchor) || 'left');
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      var mx = (p1.x + p2.x) / 2;
      var d = 'M ' + p1.x + ' ' + p1.y + ' C ' + mx + ' ' + p1.y + ', ' + mx + ' ' + p2.y + ', ' + p2.x + ' ' + p2.y;
      path.setAttribute('d', d);
      path.setAttribute('class', 'qwb-link-line');
      path.setAttribute('marker-end', 'url(#qwbArrow)');
      svgLinks.appendChild(path);
      if (c.label) {
        var text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', mx);
        text.setAttribute('y', (p1.y + p2.y) / 2 - 6);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('class', 'qwb-link-label');
        text.textContent = String(c.label).slice(0, 40);
        svgLinks.appendChild(text);
      }
    });
  }

  function render() {
    canvas.innerHTML = '';
    linear.innerHTML = '';
    var els = (state.document.elements || []).slice().sort(function (a, b) {
      return (a.zIndex || 0) - (b.zIndex || 0);
    });
    els.forEach(function (el) {
      var div = document.createElement('div');
      div.className = 'qwb-el';
      div.dataset.id = el.id;
      div.setAttribute('data-emphasis', (el.style && el.style.emphasis) || 'normal');
      if (el.locked) div.classList.add('is-locked');
      if (state.selectedId === el.id) div.classList.add('is-selected');
      div.style.left = ((el.position && el.position.x) || 0) + 'px';
      div.style.top = ((el.position && el.position.y) || 0) + 'px';
      var width = (el.size && el.size.width) || 220;
      if (ruleOnly) width = Math.max(200, Math.min(width, wrap.clientWidth - 80));
      div.style.width = width + 'px';
      div.style.height = ((el.size && el.size.height) || 80) + 'px';
      div.style.zIndex = el.zIndex || 0;

      var typeLabel = document.createElement('div');
      typeLabel.className = 'qwb-el__type';
      typeLabel.textContent = (ruleOnly ? 'Règle utilisée' : el.type) + (el.locked ? ' 🔒' : '');
      div.appendChild(typeLabel);

      var body = document.createElement('div');
      body.className = 'qwb-el__body';
      var renderedRule = state.renderedRules[el.id];
      if (el.type === 'rule') body.classList.add('lesson-md');
      if (el.type === 'rule' && renderedRule && renderedRule.text === el.text) {
        // HTML comes only from the server's existing |latex filter, never from
        // a board object or the model. The shared renderMath handles KaTeX.
        body.innerHTML = renderedRule.html;
      } else if (el.type === 'formula' || el.type === 'calculation') {
        renderKatex(body, el.latex || '');
      } else if (el.type === 'table') {
        var tbl = document.createElement('table');
        tbl.className = 'table table-sm mb-0';
        if (el.headers && el.headers.length) {
          var thead = document.createElement('thead');
          var trh = document.createElement('tr');
          el.headers.forEach(function (h) {
            var th = document.createElement('th');
            th.textContent = escapeText(h);
            trh.appendChild(th);
          });
          thead.appendChild(trh);
          tbl.appendChild(thead);
        }
        var tbody = document.createElement('tbody');
        (el.rows || []).forEach(function (row) {
          var tr = document.createElement('tr');
          (row || []).forEach(function (c) {
            var td = document.createElement('td');
            td.textContent = escapeText(c);
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
        tbl.appendChild(tbody);
        body.appendChild(tbl);
      } else {
        body.textContent = escapeText(contentOf(el));
      }
      div.appendChild(body);
      bindDrag(div, el);
      div.addEventListener('pointerdown', function (ev) {
        if (ev.button !== 0) return;
        selectEl(el.id);
      });
      canvas.appendChild(div);
      if (
        el.type !== 'formula' &&
        el.type !== 'calculation' &&
        window.renderMath
      ) {
        window.renderMath(body);
      }

      var li = document.createElement('li');
      li.className = 'list-group-item' + (state.selectedId === el.id ? ' active' : '');
      li.textContent = ruleOnly ? contentOf(el).split('\n')[0] :
        el.type + ' — ' + contentOf(el).slice(0, 60);
      li.addEventListener('click', function () { selectEl(el.id); });
      linear.appendChild(li);
    });
    renderConnections();
    applyTransform();
    updateProps();
  }

  function findEl(id) {
    return (state.document.elements || []).find(function (e) { return e.id === id; });
  }
  function selectEl(id) { state.selectedId = id; render(); }

  function updateProps() {
    var el = findEl(state.selectedId);
    var show = !!el;
    editText.classList.toggle('d-none', !show);
    btnDup.classList.toggle('d-none', !show || ruleOnly);
    btnLock.classList.toggle('d-none', !show);
    btnDel.classList.toggle('d-none', !show);
    if (!el) return;
    editText.value = el.latex != null ? el.latex : (el.text || '');
    btnLock.textContent = el.locked ? 'Déverrouiller' : 'Verrouiller';
  }

  function bindDrag(div, el) {
    var startX, startY, origX, origY, dragging = false;
    div.addEventListener('pointerdown', function (ev) {
      if (el.locked || ev.button !== 0) return;
      dragging = true;
      div.setPointerCapture(ev.pointerId);
      startX = ev.clientX; startY = ev.clientY;
      origX = el.position.x; origY = el.position.y;
      pushUndo();
    });
    div.addEventListener('pointermove', function (ev) {
      if (!dragging) return;
      el.position.x = Math.round(origX + (ev.clientX - startX) / state.scale);
      el.position.y = Math.round(origY + (ev.clientY - startY) / state.scale);
      div.style.left = el.position.x + 'px';
      div.style.top = el.position.y + 'px';
      renderConnections();
    });
    div.addEventListener('pointerup', function () {
      if (!dragging) return;
      dragging = false;
      scheduleSave();
    });
  }

  function scheduleSave() {
    state.dirty = true;
    setStatus('Enregistrement…');
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(save, 1500);
  }

  function api(body) {
    return fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify(body),
      credentials: 'same-origin',
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    });
  }

  function save() {
    api({ action: 'save', revision: state.revision, document: state.document }).then(function (res) {
      if (res.status === 409) {
        setStatus('Conflit — rechargement');
        if (res.data.document) {
          state.document = res.data.document;
          state.renderedRules = res.data.rendered_rules || {};
          state.revision = res.data.revision;
          render();
        }
        return;
      }
      if (res.data && res.data.ok) {
        state.revision = res.data.revision;
        state.renderedRules = res.data.rendered_rules || {};
        state.dirty = false;
        setStatus('Enregistré');
      } else setStatus('Échec — Réessayer');
    }).catch(function () { setStatus('Échec — Réessayer'); });
  }

  function generate(regenerate) {
    if (ruleOnly) {
      clearTimeout(state.saveTimer);
      state.document = { version: 1, title: 'Règle utilisée', elements: [], connections: [] };
      state.renderedRules = {};
      state.undo = [];
      state.redo = [];
      state.selectedId = null;
      state.dirty = false;
      chatLog.innerHTML = '';
      proposalsBox.innerHTML = '';
      render();
    }
    setStatus('Génération…');
    api({ action: 'generate', regenerate: !!regenerate }).then(function (res) {
      if (res.data && res.data.document) {
        state.document = res.data.document;
        state.renderedRules = res.data.rendered_rules || {};
        state.revision = res.data.revision;
        setWarning(res.data.warning || '');
        setStatus(res.data.generated_by_ai ? 'Généré par IA' : 'Tableau de base');
        document.getElementById('qwbRegen').classList.remove('d-none');
        render();
      } else {
        setStatus('Erreur de génération');
        setWarning((res.data && res.data.message) || 'Impossible de générer.');
      }
    }).catch(function () { setStatus('Erreur réseau'); });
  }

  function load() {
    // correction_page already discarded the saved board and invalidated old
    // revisions. Never load previous correction objects on a completed quiz.
    if (ruleOnly) { generate(false); return; }
    setStatus('Chargement…');
    fetch(apiUrl, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.exists && data.document) {
          state.document = data.document;
          state.renderedRules = data.rendered_rules || {};
          state.revision = data.revision;
          setWarning(data.warning || '');
          setStatus('Enregistré');
          document.getElementById('qwbRegen').classList.remove('d-none');
          render();
        } else setStatus('Prêt — cliquez sur Générer');
      })
      .catch(function () { setStatus('Erreur de chargement'); });
  }

  function appendChat(role, text) {
    var div = document.createElement('div');
    div.className = 'qwb-chat-msg ' + role;
    div.textContent = (role === 'user' ? 'Vous : ' : 'IA : ') + text;
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function showProposals(list) {
    proposalsBox.innerHTML = '';
    (list || []).forEach(function (pr) {
      var box = document.createElement('div');
      box.className = 'qwb-proposal';
      var label = document.createElement('div');
      label.className = 'small';
      label.textContent = (pr.type || 'text') + ' — ' + contentOf(pr).slice(0, 80);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-edubac mt-1';
      btn.textContent = 'Ajouter au tableau';
      btn.addEventListener('click', function () {
        pushUndo();
        pr.position = pr.position || { x: 60, y: 60 };
        pr.position.x = (pr.position.x || 60) + 30;
        pr.position.y = (pr.position.y || 60) + 30;
        state.document.elements.push(pr);
        state.selectedId = pr.id;
        render();
        scheduleSave();
        box.remove();
      });
      box.appendChild(label);
      box.appendChild(btn);
      proposalsBox.appendChild(box);
    });
  }

  function sendChat() {
    var msg = (chatInput.value || '').trim();
    if (!msg) return;
    appendChat('user', msg);
    chatInput.value = '';
    chatSend.disabled = true;
    setStatus('IA…');
    api({
      action: 'chat',
      message: msg,
      selected_element_id: state.selectedId || null,
    }).then(function (res) {
      chatSend.disabled = false;
      if (res.status === 429) {
        appendChat('bot', (res.data && res.data.message) || 'Limite atteinte.');
        setStatus('Limite IA');
        return;
      }
      if (res.data && res.data.ok) {
        appendChat('bot', res.data.reply || '');
        showProposals(res.data.proposals || []);
        setStatus('Enregistré');
      } else {
        appendChat('bot', (res.data && res.data.message) || 'Erreur de réponse.');
        setStatus('Erreur chat');
      }
    }).catch(function () {
      chatSend.disabled = false;
      appendChat('bot', 'Erreur réseau. Réessayez.');
      setStatus('Erreur réseau');
    });
  }

  document.getElementById('qwbGenerate').addEventListener('click', function () { generate(false); });
  document.getElementById('qwbRegen').addEventListener('click', function () {
    if (confirm(ruleOnly ? 'Régénérer la règle ?' : 'Régénérer la correction ?')) generate(true);
  });
  document.getElementById('qwbZoomIn').addEventListener('click', function () {
    state.scale = Math.min(2.5, state.scale + 0.1); applyTransform();
  });
  document.getElementById('qwbZoomOut').addEventListener('click', function () {
    state.scale = Math.max(0.4, state.scale - 0.1); applyTransform();
  });
  document.getElementById('qwbZoomReset').addEventListener('click', function () {
    state.scale = 1; state.panX = 0; state.panY = 0; applyTransform();
  });
  document.getElementById('qwbUndo').addEventListener('click', function () {
    if (!state.undo.length) return;
    state.redo.push(JSON.stringify(state.document));
    state.document = JSON.parse(state.undo.pop());
    render(); scheduleSave();
  });
  document.getElementById('qwbRedo').addEventListener('click', function () {
    if (!state.redo.length) return;
    state.undo.push(JSON.stringify(state.document));
    state.document = JSON.parse(state.redo.pop());
    render(); scheduleSave();
  });

  editText.addEventListener('change', function () {
    var el = findEl(state.selectedId);
    if (!el || el.locked) return;
    pushUndo();
    if (el.type === 'formula' || el.type === 'calculation') el.latex = editText.value.slice(0, 500);
    else el.text = editText.value.slice(0, 2000);
    render(); scheduleSave();
  });
  btnDup.addEventListener('click', function () {
    if (ruleOnly) return;
    var el = findEl(state.selectedId);
    if (!el) return;
    pushUndo();
    var copy = JSON.parse(JSON.stringify(el));
    copy.id = 'el' + Date.now().toString(36);
    copy.position = { x: el.position.x + 20, y: el.position.y + 20 };
    copy.locked = false;
    state.document.elements.push(copy);
    state.selectedId = copy.id;
    render(); scheduleSave();
  });
  btnLock.addEventListener('click', function () {
    var el = findEl(state.selectedId);
    if (!el) return;
    pushUndo();
    el.locked = !el.locked;
    render(); scheduleSave();
  });
  btnDel.addEventListener('click', function () {
    var el = findEl(state.selectedId);
    if (!el || el.locked) return;
    pushUndo();
    state.document.elements = state.document.elements.filter(function (e) { return e.id !== el.id; });
    state.document.connections = (state.document.connections || []).filter(function (c) {
      return c.from.elementId !== el.id && c.to.elementId !== el.id;
    });
    state.selectedId = null;
    render(); scheduleSave();
  });

  chatSend.addEventListener('click', sendChat);
  chatInput.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); sendChat(); }
  });

  var panning = false, psx, psy, ppx, ppy;
  wrap.addEventListener('pointerdown', function (ev) {
    if (ev.target !== wrap && ev.target !== canvas && ev.target !== svgLinks) return;
    panning = true;
    wrap.setPointerCapture(ev.pointerId);
    psx = ev.clientX; psy = ev.clientY; ppx = state.panX; ppy = state.panY;
  });
  wrap.addEventListener('pointermove', function (ev) {
    if (!panning) return;
    state.panX = ppx + (ev.clientX - psx);
    state.panY = ppy + (ev.clientY - psy);
    applyTransform();
  });
  wrap.addEventListener('pointerup', function () { panning = false; });
  wrap.addEventListener('wheel', function (ev) {
    ev.preventDefault();
    state.scale = Math.max(0.4, Math.min(2.5, state.scale + (ev.deltaY < 0 ? 0.08 : -0.08)));
    applyTransform();
  }, { passive: false });

  document.addEventListener('keydown', function (ev) {
    if (ev.target && (ev.target.tagName === 'TEXTAREA' || ev.target.tagName === 'INPUT')) return;
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'z') {
      ev.preventDefault(); document.getElementById('qwbUndo').click();
    }
    if ((ev.ctrlKey || ev.metaKey) && (ev.key === 'y' || (ev.shiftKey && ev.key === 'z'))) {
      ev.preventDefault(); document.getElementById('qwbRedo').click();
    }
    if (ev.key === 'Delete' || ev.key === 'Backspace') btnDel.click();
  });

  if (svgLinks) {
    svgLinks.setAttribute('width', '2400');
    svgLinks.setAttribute('height', '1600');
    svgLinks.style.position = 'absolute';
    svgLinks.style.left = '0';
    svgLinks.style.top = '0';
    svgLinks.style.transformOrigin = '0 0';
  }

  if (ruleOnly) window.addEventListener('resize', render);
  load();
})();
