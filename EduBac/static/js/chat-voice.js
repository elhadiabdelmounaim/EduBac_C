/**
 * Lecteur des messages vocaux (style messagerie mobile), sans dépendance.
 * chat.js / private-chat.js appellent EduBacVoice.enhance(row) après chaque insertion.
 *
 * - bouton lecture/pause, forme d'onde cliquable et déplaçable (souris, doigt, clavier) ;
 * - temps écoulé / durée totale, vitesse 1x · 1.5x · 2x commune à tous les messages ;
 * - un seul message vocal joue à la fois ; pause automatique si la page est masquée.
 * La forme d'onde réelle est calculée quand le message devient visible ; à défaut,
 * une forme d'onde stable (dérivée de l'adresse) est affichée.
 */
(function () {
  'use strict';
  if (window.EduBacVoice) return;
  var enhanced = new WeakMap();
  var players = [];
  var active = null;
  var serial = 0;
  var BAR_COUNT = 36;
  var SPEEDS = [1, 1.5, 2];
  var SEEK_STEP = 5;
  var rate = readRate();
  var icons = {
    play: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M8 5.2v13.6c0 .8.9 1.3 1.6.8l10.2-6.8c.6-.4.6-1.2 0-1.6L9.6 4.4C8.9 3.9 8 4.4 8 5.2z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="6" y="4.5" width="4.2" height="15" rx="1.3"/><rect x="13.8" y="4.5" width="4.2" height="15" rx="1.3"/></svg>',
    retry: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5V2L7 6l5 4V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z"/></svg>'
  };

  function readRate() {
    try {
      var saved = Number(window.localStorage && window.localStorage.getItem('edubac-voice-rate'));
      return SPEEDS.indexOf(saved) !== -1 ? saved : 1;
    } catch (error) { return 1; }
  }

  function saveRate(value) {
    try { if (window.localStorage) window.localStorage.setItem('edubac-voice-rate', String(value)); } catch (error) {}
  }

  function clock(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return '—';
    seconds = Math.floor(seconds);
    return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
  }

  function speedLabel(value) { return String(value).replace('.', ',') + '×'; }

  /** Forme d'onde stable dérivée d'une chaîne (affichée avant l'analyse réelle). */
  function fallbackPeaks(seed) {
    var hash = 2166136261;
    seed = String(seed || 'voice');
    for (var i = 0; i < seed.length; i++) hash = Math.imul(hash ^ seed.charCodeAt(i), 16777619);
    var peaks = [];
    var previous = 0.5;
    for (var b = 0; b < BAR_COUNT; b++) {
      hash = Math.imul(hash ^ (hash >>> 15), 2246822507) >>> 0;
      var value = 0.22 + (hash % 1000) / 1000 * 0.7;
      previous = previous * 0.45 + value * 0.55;
      peaks.push(previous);
    }
    return peaks;
  }

  /* ---- Analyse réelle (forme d'onde et durée), mise en cache par adresse ---- */
  var analyses = new Map();
  var queue = [];
  var running = 0;

  function canAnalyse() {
    return typeof window.fetch === 'function' && typeof window.Blob === 'function' &&
      !!(window.OfflineAudioContext || window.webkitOfflineAudioContext);
  }

  function decode(buffer) {
    var Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    var ctx = new Offline(1, 1, 44100);
    return new Promise(function (resolve, reject) {
      var result = ctx.decodeAudioData(buffer, resolve, reject);
      if (result && typeof result.then === 'function') result.then(resolve, reject);
    });
  }

  function computePeaks(audioBuffer) {
    var data = audioBuffer.getChannelData(0);
    var bucket = Math.max(1, Math.floor(data.length / BAR_COUNT));
    var stride = Math.max(1, Math.floor(bucket / 400));
    var peaks = [];
    var max = 0;
    for (var b = 0; b < BAR_COUNT; b++) {
      var start = b * bucket;
      var end = Math.min(data.length, start + bucket);
      var sum = 0;
      var count = 0;
      for (var i = start; i < end; i += stride) { sum += data[i] * data[i]; count++; }
      var rms = count ? Math.sqrt(sum / count) : 0;
      peaks.push(rms);
      if (rms > max) max = rms;
    }
    return peaks.map(function (value) { return max ? Math.max(0.12, value / max) : 0.12; });
  }

  function pump() {
    while (running < 2 && queue.length) {
      var job = queue.shift();
      running++;
      job().then(done, done);
    }
    function done() { running--; pump(); }
  }

  function analyse(url) {
    if (analyses.has(url)) return analyses.get(url);
    var promise = new Promise(function (resolve, reject) {
      queue.push(function () {
        var type = '';
        return window.fetch(url, { credentials: 'same-origin' }).then(function (response) {
          if (!response.ok) throw new Error('HTTP ' + response.status);
          type = response.headers.get('content-type') || '';
          return response.arrayBuffer();
        }).then(function (buffer) {
          // Copie locale : le déplacement dans l'audio fonctionne même si le
          // serveur ne gère pas les requêtes partielles.
          var blobUrl = '';
          if (buffer.byteLength < 15 * 1024 * 1024 && window.URL && window.URL.createObjectURL) {
            blobUrl = window.URL.createObjectURL(new Blob([buffer], { type: type || 'audio/webm' }));
          }
          return decode(buffer.slice(0)).then(function (audioBuffer) {
            return { peaks: computePeaks(audioBuffer), duration: audioBuffer.duration, blobUrl: blobUrl };
          }, function () {
            return { peaks: null, duration: NaN, blobUrl: blobUrl };
          });
        }).then(resolve, reject);
      });
      pump();
    });
    analyses.set(url, promise);
    return promise;
  }

  var observer = null;
  function whenVisible(element, callback) {
    if (typeof window.IntersectionObserver !== 'function') { callback(); return; }
    if (!observer) {
      observer = new window.IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          observer.unobserve(entry.target);
          var run = entry.target.__edubacVisible;
          entry.target.__edubacVisible = null;
          if (run) run();
        });
      }, { rootMargin: '200px 0px' });
    }
    element.__edubacVisible = callback;
    observer.observe(element);
  }

  /* ---- Lecteur ---- */
  function enhanceOne(audio) {
    if (enhanced.has(audio) || !audio.parentNode) return;
    var parent = audio.parentNode;
    var originalHidden = audio.hidden;
    var originalControls = audio.controls;
    var listeners = [];
    var wrapper = document.createElement('div');
    var state;
    function listen(target, name, callback) {
      target.addEventListener(name, callback);
      listeners.push([target, name, callback]);
    }
    try {
      wrapper.className = 'chat-voice';
      wrapper.setAttribute('role', 'group');
      wrapper.setAttribute('aria-label', 'Message vocal');
      wrapper.setAttribute('data-state', 'paused');
      wrapper.innerHTML =
        '<button type="button" class="chat-voice-play" aria-label="Lire le message vocal"></button>' +
        '<div class="chat-voice-body">' +
          '<div class="chat-voice-wave" role="slider" tabindex="0" aria-label="Position de lecture" aria-valuemin="0"></div>' +
          '<div class="chat-voice-meta">' +
            '<span class="chat-voice-times"><span class="chat-voice-elapsed">0:00</span>' +
            '<span class="chat-voice-sep" aria-hidden="true"> / </span>' +
            '<span class="chat-voice-duration">—</span></span>' +
            '<button type="button" class="chat-voice-speed"></button>' +
          '</div>' +
        '</div>' +
        '<div class="chat-voice-status" role="status" aria-live="polite" aria-atomic="true"></div>';
      var play = wrapper.querySelector('.chat-voice-play');
      var wave = wrapper.querySelector('.chat-voice-wave');
      var elapsed = wrapper.querySelector('.chat-voice-elapsed');
      var duration = wrapper.querySelector('.chat-voice-duration');
      var speed = wrapper.querySelector('.chat-voice-speed');
      var status = wrapper.querySelector('.chat-voice-status');
      status.id = 'chat-voice-status-' + (++serial);
      play.setAttribute('aria-describedby', status.id);
      state = {
        audio: audio, pending: false, token: 0, loading: false, message: '',
        decodedDuration: NaN, bars: [], started: false, dragging: false
      };

      var source = audio.getAttribute ? (audio.getAttribute('src') || '') : '';
      for (var b = 0; b < BAR_COUNT; b++) {
        var bar = document.createElement('span');
        bar.className = 'chat-voice-bar';
        wave.appendChild(bar);
        state.bars.push(bar);
      }
      function paintPeaks(peaks, estimated) {
        for (var i = 0; i < state.bars.length; i++) {
          var height = Math.round(14 + (peaks[i] || 0.12) * 86);
          if (state.bars[i].style) state.bars[i].style.height = height + '%';
        }
        if (wrapper.classList) wrapper.classList.toggle('is-estimated', !!estimated);
      }
      paintPeaks(fallbackPeaks(source), true);

      function total() {
        var value = audio.duration;
        if (Number.isFinite(value) && value > 0) return value;
        return Number.isFinite(state.decodedDuration) && state.decodedDuration > 0 ? state.decodedDuration : NaN;
      }

      function render() {
        var length = total();
        var known = Number.isFinite(length) && length > 0;
        var current = Number.isFinite(audio.currentTime) ? Math.max(0, audio.currentTime) : 0;
        if (known) current = Math.min(current, length);
        var playing = !audio.paused && !audio.ended;
        var busy = playing || state.pending;
        if (current > 0.05 || busy) state.started = true;
        play.innerHTML = busy ? icons.pause : (audio.error ? icons.retry : icons.play);
        var label = busy ? 'Mettre en pause' : (audio.error ? 'Réessayer la lecture' : 'Lire le message vocal');
        play.setAttribute('aria-label', label);
        play.title = label;
        wrapper.setAttribute('data-state', busy ? 'playing' : 'paused');
        if (wrapper.classList) {
          wrapper.classList.toggle('is-started', state.started);
          wrapper.classList.toggle('is-loading', !!state.loading);
        }
        var ratio = known ? current / length : 0;
        var playedBars = Math.round(ratio * state.bars.length);
        for (var i = 0; i < state.bars.length; i++) {
          var played = i < playedBars;
          if (state.bars[i].classList) state.bars[i].classList.toggle('is-played', played);
        }
        if (wave.style && wave.style.setProperty) wave.style.setProperty('--progress', String(ratio));
        var disabled = !known || !!audio.error;
        wave.setAttribute('aria-disabled', disabled ? 'true' : 'false');
        wave.setAttribute('aria-valuemax', known ? String(Math.round(length)) : '0');
        wave.setAttribute('aria-valuenow', String(Math.round(current)));
        wave.setAttribute('aria-valuetext', clock(current) + (known ? ' sur ' + clock(length) : ' ; durée indisponible'));
        elapsed.textContent = clock(current);
        duration.textContent = known ? clock(length) : '—';
        duration.setAttribute('aria-label', known ? 'Durée : ' + clock(length) : 'Durée indisponible');
        speed.textContent = speedLabel(rate);
        speed.setAttribute('aria-label', 'Vitesse de lecture : ' + speedLabel(rate) + '. Changer la vitesse');
        speed.title = 'Vitesse de lecture';
        var text = state.message || (state.loading ? 'Chargement du message vocal…' :
          (!known && audio.readyState >= 1 ? 'Durée indisponible ; lecture possible.' : ''));
        if (status.textContent !== text) status.textContent = text;
      }
      state.render = render;

      function applyRate() {
        try {
          audio.defaultPlaybackRate = rate;
          audio.playbackRate = rate;
        } catch (error) { /* Lecteur sans réglage de vitesse. */ }
      }

      state.pause = function () {
        state.token++;
        state.pending = false;
        state.loading = false;
        audio.pause();
        if (active === state) active = null;
        render();
      };

      function failed(error, token) {
        if (token !== state.token) return;
        state.pause();
        state.message = error && error.name === 'NotAllowedError' ?
          'Lecture refusée par le navigateur. Appuyez sur Lire pour réessayer.' :
          'Lecture impossible. Appuyez sur Lire pour réessayer.';
        render();
      }

      function seekTo(seconds) {
        var length = total();
        if (!(length > 0) || audio.error) return;
        var target = Math.max(0, Math.min(seconds, length));
        try {
          audio.currentTime = target;
          state.message = '';
          state.started = true;
        } catch (error) { state.message = 'Déplacement indisponible pour le moment.'; }
        render();
      }

      function seekFromPointer(event) {
        if (!wave.getBoundingClientRect) return;
        var rect = wave.getBoundingClientRect();
        if (!rect.width) return;
        var ratio = (event.clientX - rect.left) / rect.width;
        seekTo(Math.max(0, Math.min(1, ratio)) * total());
      }

      listen(play, 'click', function () {
        if (!audio.paused || state.pending) { state.pause(); return; }
        if (active && active !== state) active.pause();
        active = state;
        state.message = '';
        state.pending = true;
        state.loading = true;
        var token = ++state.token;
        render();
        try {
          if (audio.error) audio.load();
          if (audio.ended) audio.currentTime = 0;
          applyRate();
          var promise = audio.play();
          if (promise && typeof promise.then === 'function') {
            promise.then(function () {
              if (token !== state.token) return;
              state.pending = false;
              render();
            }, function (error) { failed(error, token); });
          }
        } catch (error) { failed(error, token); }
      });
      listen(speed, 'click', function () {
        rate = SPEEDS[(SPEEDS.indexOf(rate) + 1) % SPEEDS.length];
        saveRate(rate);
        players.forEach(function (player) {
          try {
            player.audio.defaultPlaybackRate = rate;
            player.audio.playbackRate = rate;
          } catch (error) {}
          player.render();
        });
      });
      listen(wave, 'pointerdown', function (event) {
        if (wave.getAttribute('aria-disabled') === 'true') return;
        state.dragging = true;
        if (wave.setPointerCapture && event.pointerId != null) {
          try { wave.setPointerCapture(event.pointerId); } catch (error) {}
        }
        seekFromPointer(event);
        if (event.preventDefault) event.preventDefault();
      });
      listen(wave, 'pointermove', function (event) {
        if (state.dragging) seekFromPointer(event);
      });
      ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (name) {
        listen(wave, name, function () { state.dragging = false; });
      });
      listen(wave, 'keydown', function (event) {
        var length = total();
        if (!(length > 0)) return;
        var current = audio.currentTime || 0;
        var next = null;
        if (event.key === 'ArrowRight' || event.key === 'ArrowUp') next = current + SEEK_STEP;
        else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') next = current - SEEK_STEP;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = length;
        else if (event.key === ' ' || event.key === 'Enter') { play.click ? play.click() : null; event.preventDefault(); return; }
        if (next === null) return;
        event.preventDefault();
        seekTo(next);
      });
      listen(audio, 'play', function () {
        if (document.hidden) { state.pause(); return; }
        if (active && active !== state) active.pause();
        active = state;
        state.pending = false;
        state.message = '';
        applyRate();
        render();
      });
      listen(audio, 'playing', function () { state.loading = false; state.message = ''; render(); });
      listen(audio, 'pause', function () {
        state.pending = false;
        state.loading = false;
        if (active === state) active = null;
        render();
      });
      listen(audio, 'ended', function () {
        state.pause();
        try { audio.currentTime = 0; } catch (error) { /* Média non déplaçable. */ }
        state.message = '';
        state.started = false;
        render();
      });
      listen(audio, 'error', function () {
        state.pause();
        state.message = 'Message vocal indisponible. Appuyez sur Réessayer la lecture.';
        render();
      });
      ['waiting', 'stalled', 'loadstart'].forEach(function (name) {
        listen(audio, name, function () {
          state.loading = state.pending || !audio.paused;
          render();
        });
      });
      ['loadedmetadata', 'durationchange', 'timeupdate', 'seeked', 'emptied', 'ratechange'].forEach(function (name) {
        listen(audio, name, render);
      });
      listen(audio, 'canplay', function () { state.loading = false; render(); });
      if (audio.error) state.message = 'Message vocal indisponible. Appuyez sur Réessayer la lecture.';
      render();
      parent.insertBefore(wrapper, audio);
      wrapper.appendChild(audio);
      // Les contrôles natifs ne disparaissent qu'une fois le lecteur prêt.
      enhanced.set(audio, state);
      players.push(state);
      audio.controls = false;
      audio.hidden = true;

      if (source && canAnalyse()) {
        whenVisible(wrapper, function () {
          analyse(source).then(function (result) {
            if (result.peaks) paintPeaks(result.peaks, false);
            if (Number.isFinite(result.duration)) state.decodedDuration = result.duration;
            var untouched = audio.paused && !state.pending && !(audio.currentTime > 0);
            if (result.blobUrl && untouched && audio.getAttribute('src') === source) {
              audio.src = result.blobUrl;
              applyRate();
            }
            render();
          }, function () {
            if (audio.preload === 'none') audio.preload = 'metadata';
          });
        });
      } else if (audio.preload === 'none') {
        audio.preload = 'metadata';
      }
    } catch (error) {
      listeners.forEach(function (entry) { entry[0].removeEventListener(entry[1], entry[2]); });
      enhanced.delete(audio);
      if (audio.parentNode === wrapper) parent.insertBefore(audio, wrapper);
      if (wrapper.remove) wrapper.remove();
      audio.hidden = originalHidden;
      audio.controls = originalControls;
    }
  }

  function enhance(root) {
    root = root || document;
    if (root.jquery) root = root[0];
    if (!root || !root.querySelectorAll) return;
    if (root.matches && root.matches('audio.chat-voice-player')) enhanceOne(root);
    root.querySelectorAll('audio.chat-voice-player').forEach(enhanceOne);
  }
  function pauseAll() {
    if (active) active.pause();
    document.querySelectorAll('audio.chat-voice-player').forEach(function (audio) {
      var state = enhanced.get(audio);
      if (state) state.pause();
      else audio.pause();
    });
  }
  window.EduBacVoice = { enhance: enhance, pauseAll: pauseAll };
  document.addEventListener('visibilitychange', function () { if (document.hidden) pauseAll(); });
  window.addEventListener('pagehide', pauseAll);
  window.addEventListener('beforeunload', pauseAll);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { enhance(document); }, { once: true });
  } else enhance(document);
})();

/**
 * Voice composer: record, stop, replay, then delete or send.
 * Nothing is uploaded until the user presses Envoyer.
 */
(function () {
  'use strict';
  if (!document || typeof document.getElementById !== 'function') return;

  var mic = document.getElementById('chatVoiceBtn');
  var panel = document.getElementById('chatVoiceRecorder');
  var form = document.getElementById('chatForm');
  var rec = document.getElementById('chatVoiceRec');
  var preview = document.getElementById('chatVoicePreview');
  if (!mic || !panel || !form || !rec || !preview) return;

  var cancelBtn = document.getElementById('chatVoiceCancel');
  var stopBtn = document.getElementById('chatVoiceStop');
  var deleteBtn = document.getElementById('chatVoiceDelete');
  var playBtn = document.getElementById('chatVoicePlay');
  var seek = document.getElementById('chatVoiceSeek');
  var elapsedEl = document.getElementById('chatVoiceElapsed');
  var durationEl = document.getElementById('chatVoiceDuration');
  var stateEl = document.getElementById('chatVoicePreviewState');
  var sendBtn = document.getElementById('chatVoiceSend');
  var audio = document.getElementById('chatVoicePreviewAudio');
  var timerEl = document.getElementById('chatVoiceRecTime');
  var wave = document.getElementById('chatVoiceWave');
  var emojiPanel = document.getElementById('chatEmojiPanel') || document.getElementById('privateEmojiPanel');
  var restartBtn = document.getElementById('chatVoiceRestart');
  var recSendBtn = document.getElementById('chatVoiceRecSend');
  var previewWave = document.getElementById('chatVoicePreviewWave');
  var PREVIEW_BARS = 40;
  var levels = [];
  var previewBars = [];
  var sendAfterStop = false;

  var mediaRecorder = null;
  var stream = null;
  var chunks = [];
  var discard = false;
  var cancelRequested = false;
  var recording = false;
  var requesting = false;
  var startedAt = 0;
  var recordedSeconds = 0;
  var timer = null;
  var raf = 0;
  var audioCtx = null;
  var analyser = null;
  var sourceNode = null;
  var objectUrl = '';
  var pendingFile = null;
  var sending = false;
  var icons = {
    play: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M8 5v14l11-7z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>'
  };

  function clock(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
    seconds = Math.floor(seconds);
    var mins = Math.floor(seconds / 60);
    var secs = seconds % 60;
    return mins + ':' + (secs < 10 ? '0' : '') + secs;
  }

  function markComposer(active) {
    var composer = form.closest ? form.closest('.chat-composer') : null;
    if (composer && composer.classList) composer.classList.toggle('is-voice-active', !!active);
  }

  function setMicBusy(busy) {
    mic.disabled = !!busy;
    mic.setAttribute('aria-pressed', busy ? 'true' : 'false');
  }

  function setComposerState(state) {
    panel.hidden = state === 'idle';
    panel.setAttribute('data-state', state);
    form.hidden = state !== 'idle';
    markComposer(state !== 'idle');
    rec.hidden = state !== 'recording';
    preview.hidden = state !== 'preview';
  }

  function showIdle() {
    setComposerState('idle');
    preview.setAttribute('data-playback', 'paused');
    setMicBusy(false);
    if (mic.focus) mic.focus();
  }

  function buildBars() {
    if (!wave) return;
    var count = wave.children ? wave.children.length : (wave.childElementCount || 0);
    if (count) return;
    for (var i = 0; i < 24; i++) {
      var bar = document.createElement('span');
      bar.className = 'chat-voice-bar';
      if (bar.style && bar.style.setProperty) bar.style.setProperty('--i', String(i));
      wave.appendChild(bar);
    }
  }

  function stopWave() {
    if (raf) {
      (window.cancelAnimationFrame || clearTimeout)(raf);
      raf = 0;
    }
    if (sourceNode) {
      try { sourceNode.disconnect(); } catch (error) {}
      sourceNode = null;
    }
    analyser = null;
    if (audioCtx) {
      var ctx = audioCtx;
      audioCtx = null;
      if (ctx.close) {
        try {
          var closed = ctx.close();
          if (closed && typeof closed.catch === 'function') closed.catch(function () {});
        } catch (error) {}
      }
    }
  }

  function startWave(mediaStream) {
    buildBars();
    if (wave) wave.classList.add('is-fallback');
    var AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx || !wave || typeof requestAnimationFrame !== 'function') return;
    try {
      audioCtx = new AudioCtx();
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      sourceNode = audioCtx.createMediaStreamSource(mediaStream);
      sourceNode.connect(analyser);
      var data = new Uint8Array(analyser.frequencyBinCount);
      var bars = wave.querySelectorAll('.chat-voice-bar');
      wave.classList.remove('is-fallback');
      var tick = function () {
        if (!analyser) return;
        analyser.getByteFrequencyData(data);
        var total = 0;
        for (var i = 0; i < bars.length; i++) {
          var value = data[Math.min(data.length - 1, Math.floor(i * data.length / bars.length))] || 0;
          total += value;
          bars[i].style.height = (4 + Math.round((value / 255) * 22)) + 'px';
        }
        // Niveau moyen conservé pour dessiner la forme d'onde de l'aperçu.
        if (levels.length < 6000) levels.push(bars.length ? total / bars.length / 255 : 0);
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    } catch (error) {
      stopWave();
      if (wave) wave.classList.add('is-fallback');
    }
  }

  function releaseStream() {
    if (stream) {
      stream.getTracks().forEach(function (track) {
        try { track.stop(); } catch (error) {}
      });
      stream = null;
    }
    recording = false;
    requesting = false;
    stopWave();
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  function revokePreview() {
    pendingFile = null;
    sending = false;
    if (audio) {
      try { audio.pause(); } catch (error) {}
      audio.removeAttribute('src');
      try { audio.load(); } catch (error) {}
    }
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = '';
    }
  }

  function extensionFor(type) {
    type = String(type || '').toLowerCase();
    if (type.indexOf('mp4') !== -1 || type.indexOf('m4a') !== -1 || type.indexOf('aac') !== -1) return 'm4a';
    if (type.indexOf('ogg') !== -1) return 'ogg';
    if (type.indexOf('wav') !== -1) return 'wav';
    if (type.indexOf('mpeg') !== -1 || type.indexOf('mp3') !== -1) return 'mp3';
    return 'webm';
  }

  function shownDuration() {
    var total = audio ? audio.duration : NaN;
    if (Number.isFinite(total) && total > 0) return total;
    if (recordedSeconds > 0.2) return recordedSeconds;
    return 0;
  }

  function setPlayIcon(playing) {
    if (!playBtn) return;
    playBtn.innerHTML = playing ? icons.pause : icons.play;
    var label = playing ? 'Pause' : 'Lecture';
    playBtn.setAttribute('aria-label', label);
    playBtn.title = label;
    playBtn.setAttribute('aria-pressed', playing ? 'true' : 'false');
  }

  function renderPreview() {
    if (!audio) return;
    var shown = shownDuration();
    var current = Number.isFinite(audio.currentTime) ? Math.max(0, audio.currentTime) : 0;
    if (shown) current = Math.min(current, shown);
    var playing = !audio.paused && !audio.ended;
    if (seek) {
      seek.disabled = !(shown > 0) || sending;
      seek.max = shown > 0 ? String(shown) : '1';
      if (document.activeElement !== seek) seek.value = String(current);
      seek.setAttribute('aria-valuetext', clock(current) + (shown ? ' sur ' + clock(shown) : ''));
    }
    if (elapsedEl) elapsedEl.textContent = clock(current);
    if (durationEl) durationEl.textContent = shown ? clock(shown) : '0:00';
    paintPreviewProgress(shown ? current / shown : 0);
    var label = playing ? 'Lecture' : (!audio.ended && current > 0.05 ? 'Pause' : 'Aperçu');
    if (stateEl && !sending) stateEl.textContent = label;
    preview.setAttribute('data-playback', playing ? 'playing' : 'paused');
    setPlayIcon(playing);
  }

  function buildPreviewWave() {
    if (!previewWave) return;
    previewWave.innerHTML = '';
    previewBars = [];
    var count = PREVIEW_BARS;
    var max = 0;
    var samples = [];
    for (var i = 0; i < count; i++) {
      var start = Math.floor(i * levels.length / count);
      var end = Math.max(start + 1, Math.floor((i + 1) * levels.length / count));
      var sum = 0;
      var n = 0;
      for (var j = start; j < end && j < levels.length; j++) { sum += levels[j]; n++; }
      var value = n ? sum / n : 0;
      samples.push(value);
      if (value > max) max = value;
    }
    for (var b = 0; b < count; b++) {
      var bar = document.createElement('span');
      bar.className = 'chat-voice-bar';
      var ratio = max ? samples[b] / max : 0.35 + 0.25 * Math.abs(Math.sin(b * 1.7));
      if (bar.style) bar.style.height = Math.round(14 + Math.max(0.1, ratio) * 86) + '%';
      previewWave.appendChild(bar);
      previewBars.push(bar);
    }
  }

  function paintPreviewProgress(ratio) {
    var played = Math.round(ratio * previewBars.length);
    for (var i = 0; i < previewBars.length; i++) {
      if (previewBars[i].classList) previewBars[i].classList.toggle('is-played', i < played);
    }
  }

  function showPreview(blob) {
    var type = blob.type || 'audio/webm';
    pendingFile = new File([blob], 'voice_' + Date.now() + '.' + extensionFor(type), { type: type });
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(blob);
    sending = false;
    if (sendBtn) sendBtn.disabled = false;
    if (deleteBtn) deleteBtn.disabled = false;
    if (audio) {
      audio.src = objectUrl;
      try { audio.load(); } catch (error) {}
      try { audio.currentTime = 0; } catch (error) {}
    }
    buildPreviewWave();
    renderPreview();
    setComposerState('preview');
    setMicBusy(false);
    if (playBtn && playBtn.focus) playBtn.focus();
  }

  function bindAudio() {
    if (!audio) return;
    ['loadedmetadata', 'durationchange', 'timeupdate', 'seeked', 'ended'].forEach(function (name) {
      audio.addEventListener(name, renderPreview);
    });
    audio.addEventListener('play', renderPreview);
    audio.addEventListener('pause', renderPreview);
  }

  function togglePlay() {
    if (!audio || !objectUrl || sending) return;
    if (!audio.paused && !audio.ended) {
      audio.pause();
      return;
    }
    var shown = shownDuration();
    if (audio.ended || (shown > 0 && audio.currentTime >= shown - 0.05)) {
      try { audio.currentTime = 0; } catch (error) {}
    }
    var promise;
    try { promise = audio.play(); } catch (error) {
      if (stateEl) stateEl.textContent = 'Lecture impossible. Réessayez.';
      return;
    }
    if (promise && typeof promise.catch === 'function') {
      promise.catch(function () {
        if (stateEl) stateEl.textContent = 'Lecture impossible. Réessayez.';
      });
    }
  }

  function deletePreview() {
    if (sending) return;
    revokePreview();
    recordedSeconds = 0;
    showIdle();
  }

  function sendPreview() {
    if (!pendingFile || sending) return;
    if (audio && !audio.paused) {
      try { audio.pause(); } catch (error) {}
    }
    sending = true;
    if (sendBtn) sendBtn.disabled = true;
    if (deleteBtn) deleteBtn.disabled = true;
    if (playBtn) playBtn.disabled = true;
    if (seek) seek.disabled = true;
    var file = pendingFile;
    var url = objectUrl;
    var finished = false;
    function done(ok) {
      if (finished) return;
      finished = true;
      sending = false;
      if (playBtn) playBtn.disabled = false;
      if (ok && pendingFile === file) {
        pendingFile = null;
        if (objectUrl === url && url) {
          URL.revokeObjectURL(url);
          objectUrl = '';
        }
        if (audio) {
          try { audio.pause(); } catch (error) {}
          audio.removeAttribute('src');
          try { audio.load(); } catch (error) {}
        }
        recordedSeconds = 0;
        showIdle();
        return;
      }
      if (sendBtn) sendBtn.disabled = false;
      if (deleteBtn) deleteBtn.disabled = false;
      renderPreview();
    }
    var event;
    try {
      event = new CustomEvent('edubac:voice-send', {
        cancelable: true,
        detail: { file: file, done: done }
      });
    } catch (error) {
      done(false);
      return;
    }
    document.dispatchEvent(event);
    if (!event.defaultPrevented) done(false);
  }

  function openRecorder(mediaStream) {
    stream = mediaStream;
    chunks = [];
    discard = false;
    var preferred = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'];
    var mime = '';
    var Recorder = window.MediaRecorder;
    for (var i = 0; i < preferred.length; i++) {
      if (Recorder.isTypeSupported && Recorder.isTypeSupported(preferred[i])) {
        mime = preferred[i];
        break;
      }
    }
    try {
      mediaRecorder = mime ? new Recorder(mediaStream, { mimeType: mime }) : new Recorder(mediaStream);
    } catch (error) {
      releaseStream();
      setMicBusy(false);
      showIdle();
      alert('Enregistrement vocal non supporté par ce navigateur.');
      return;
    }
    mediaRecorder.ondataavailable = function (event) {
      if (event.data && event.data.size > 0) chunks.push(event.data);
    };
    mediaRecorder.onstop = function () {
      var wasDiscard = discard;
      var elapsed = startedAt ? (Date.now() - startedAt) / 1000 : 0;
      var recorded = chunks.slice();
      var actualType = (mediaRecorder && mediaRecorder.mimeType) || (recorded[0] && recorded[0].type) || mime || 'audio/webm';
      chunks = [];
      mediaRecorder = null;
      releaseStream();
      discard = false;
      if (wasDiscard) {
        sendAfterStop = false;
        showIdle();
        return;
      }
      var blob = new Blob(recorded, { type: actualType });
      if (blob.size < 100) {
        showIdle();
        alert('Enregistrement trop court.');
        return;
      }
      recordedSeconds = elapsed;
      showPreview(blob);
      if (sendAfterStop) {
        sendAfterStop = false;
        sendPreview();
      }
    };
    mediaRecorder.onerror = function () {
      discard = true;
      chunks = [];
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        try { mediaRecorder.stop(); } catch (error) { releaseStream(); showIdle(); }
      } else {
        releaseStream();
        showIdle();
      }
      alert('Impossible d’enregistrer ce message vocal. Réessaie.');
    };
    try {
      mediaRecorder.start();
    } catch (error) {
      mediaRecorder = null;
      releaseStream();
      setMicBusy(false);
      showIdle();
      alert('Impossible d’enregistrer ce message vocal. Réessaie.');
      return;
    }
    requesting = false;
    recording = true;
    levels = [];
    sendAfterStop = false;
    startedAt = Date.now();
    recordedSeconds = 0;
    if (timerEl) timerEl.textContent = '0:00';
    if (emojiPanel) emojiPanel.hidden = true;
    setComposerState('recording');
    startWave(mediaStream);
    timer = setInterval(function () {
      if (timerEl) timerEl.textContent = clock((Date.now() - startedAt) / 1000);
    }, 200);
    if (stopBtn && stopBtn.focus) stopBtn.focus();
  }

  function startRecording() {
    if (requesting || recording || panel.getAttribute('data-state') !== 'idle') return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      alert('Enregistrement vocal non supporté par ce navigateur.');
      return;
    }
    requesting = true;
    cancelRequested = false;
    discard = false;
    setMicBusy(true);
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (mediaStream) {
      if (cancelRequested) {
        mediaStream.getTracks().forEach(function (track) {
          try { track.stop(); } catch (error) {}
        });
        requesting = false;
        setMicBusy(false);
        showIdle();
        return;
      }
      openRecorder(mediaStream);
    }).catch(function () {
      requesting = false;
      setMicBusy(false);
      if (!cancelRequested) alert('Autorisez le micro pour envoyer un message vocal.');
    });
  }

  function stopRecording() {
    discard = false;
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      try { mediaRecorder.stop(); } catch (error) {
        releaseStream();
        showIdle();
      }
    }
  }

  function cancelRecording() {
    sendAfterStop = false;
    cancelRequested = true;
    discard = true;
    chunks = [];
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      try { mediaRecorder.stop(); return; } catch (error) {}
    }
    releaseStream();
    requesting = false;
    setMicBusy(false);
    showIdle();
  }

  function abandon() {
    sendAfterStop = false;
    discard = true;
    cancelRequested = true;
    var stopping = mediaRecorder && mediaRecorder.state !== 'inactive';
    if (stopping) {
      try { mediaRecorder.stop(); } catch (error) { stopping = false; }
    }
    if (!stopping) releaseStream();
    revokePreview();
    showIdle();
  }

  buildBars();
  bindAudio();
  setPlayIcon(false);
  mic.addEventListener('click', startRecording);
  if (stopBtn) stopBtn.addEventListener('click', stopRecording);
  if (cancelBtn) cancelBtn.addEventListener('click', cancelRecording);
  if (deleteBtn) deleteBtn.addEventListener('click', deletePreview);
  if (playBtn) playBtn.addEventListener('click', togglePlay);
  if (sendBtn) sendBtn.addEventListener('click', sendPreview);
  if (restartBtn) restartBtn.addEventListener('click', function () {
    if (sending) return;
    deletePreview();
    startRecording();
  });
  if (recSendBtn) recSendBtn.addEventListener('click', function () {
    sendAfterStop = true;
    stopRecording();
  });
  if (seek) {
    seek.addEventListener('input', function () {
      if (!audio || seek.disabled) return;
      var shown = shownDuration();
      var next = Math.max(0, Math.min(Number(seek.value) || 0, shown || 0));
      try { audio.currentTime = next; } catch (error) {}
      renderPreview();
    });
  }
  document.addEventListener('keydown', function (event) {
    if (!event || event.key !== 'Escape') return;
    if (panel.getAttribute('data-state') === 'recording' || requesting) cancelRecording();
  });
  window.addEventListener('pagehide', abandon);
})();
