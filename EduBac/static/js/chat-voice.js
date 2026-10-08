/**
 * Progressive, dependency-free voice controls.
 * chat.js calls EduBacVoice.enhance(row) after inserting each message.
 */
(function () {
  'use strict';
  if (window.EduBacVoice) return;
  var enhanced = new WeakMap();
  var active = null;
  var serial = 0;
  var icons = {
    play: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M7 4v16l14-8z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 4h4v16H6zm8 0h4v16h-4z"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 6h12v12H6z"/></svg>'
  };

  function clock(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return '—';
    seconds = Math.floor(seconds);
    return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
  }

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
      wrapper.innerHTML =
        '<button type="button" class="chat-voice-button chat-voice-play" aria-label="Lire le message vocal"></button>' +
        '<div class="chat-voice-timeline">' +
          '<input type="range" class="chat-voice-seek" min="0" max="1" step="0.1" value="0" disabled aria-label="Position de lecture">' +
          '<div class="chat-voice-times"><span class="chat-voice-elapsed">0:00</span><span class="chat-voice-duration">—</span></div>' +
        '</div>' +
        '<button type="button" class="chat-voice-button chat-voice-stop" aria-label="Arrêter et revenir au début"></button>' +
        '<div class="chat-voice-status" role="status" aria-live="polite" aria-atomic="true"></div>';
      var play = wrapper.querySelector('.chat-voice-play');
      var stop = wrapper.querySelector('.chat-voice-stop');
      var seek = wrapper.querySelector('.chat-voice-seek');
      var elapsed = wrapper.querySelector('.chat-voice-elapsed');
      var duration = wrapper.querySelector('.chat-voice-duration');
      var status = wrapper.querySelector('.chat-voice-status');
      status.id = 'chat-voice-status-' + (++serial);
      play.setAttribute('aria-describedby', status.id);
      seek.setAttribute('aria-describedby', status.id);
      stop.innerHTML = icons.stop;
      state = { audio: audio, pending: false, token: 0, loading: false, message: '' };

      function render() {
        var total = audio.duration;
        var known = Number.isFinite(total) && total > 0;
        var current = Number.isFinite(audio.currentTime) ? Math.max(0, audio.currentTime) : 0;
        var playing = !audio.paused && !audio.ended;
        play.innerHTML = playing || state.pending ? icons.pause : icons.play;
        var label = playing || state.pending ? 'Mettre en pause' : (audio.error ? 'Réessayer la lecture' : 'Lire le message vocal');
        play.setAttribute('aria-label', label);
        play.title = label;
        stop.title = 'Arrêter et revenir au début';
        seek.disabled = !known || !!audio.error;
        seek.max = known ? total : 1;
        seek.value = known ? Math.min(current, total) : 0;
        seek.setAttribute('aria-valuetext', clock(current) + (known ? ' sur ' + clock(total) : ' ; durée indisponible'));
        elapsed.textContent = clock(current);
        duration.textContent = known ? clock(total) : '—';
        duration.setAttribute('aria-label', known ? 'Durée : ' + clock(total) : 'Durée indisponible');
        var text = state.message || (state.loading ? 'Chargement du message vocal…' :
          (!known && audio.readyState >= 1 ? 'Durée indisponible ; lecture possible.' : ''));
        if (status.textContent !== text) status.textContent = text;
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
      listen(stop, 'click', function () {
        state.pause();
        state.message = '';
        try { audio.currentTime = 0; } catch (error) { /* Metadata may not yet exist. */ }
        render();
      });
      listen(seek, 'input', function () {
        if (seek.disabled) return;
        try {
          audio.currentTime = Math.max(0, Math.min(Number(seek.value), audio.duration));
          state.message = '';
        } catch (error) { state.message = 'Déplacement indisponible pour le moment.'; }
        render();
      });
      listen(audio, 'play', function () {
        if (document.hidden) { state.pause(); return; }
        if (active && active !== state) active.pause();
        active = state;
        state.pending = false;
        state.message = '';
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
        try { audio.currentTime = 0; } catch (error) { /* Non-seekable media. */ }
        state.message = '';
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
      ['loadedmetadata', 'durationchange', 'timeupdate', 'seeked', 'emptied'].forEach(function (name) {
        listen(audio, name, render);
      });
      listen(audio, 'canplay', function () { state.loading = false; render(); });
      if (audio.error) state.message = 'Message vocal indisponible. Appuyez sur Réessayer la lecture.';
      render();
      parent.insertBefore(wrapper, audio);
      wrapper.appendChild(audio);
      // Only remove the browser fallback once the complete controls are ready.
      enhanced.set(audio, state);
      audio.controls = false;
      audio.hidden = true;
    } catch (error) {
      listeners.forEach(function (entry) { entry[0].removeEventListener(entry[1], entry[2]); });
      enhanced.delete(audio);
      if (audio.parentNode === wrapper) parent.insertBefore(audio, wrapper);
      wrapper.remove();
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
  window.EduBacVoice = { enhance: enhance };
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
  var emojiPanel = document.getElementById('chatEmojiPanel');

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
        for (var i = 0; i < bars.length; i++) {
          var value = data[Math.min(data.length - 1, Math.floor(i * data.length / bars.length))] || 0;
          bars[i].style.height = (4 + Math.round((value / 255) * 22)) + 'px';
        }
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
    var label = playing ? 'Lecture' : (!audio.ended && current > 0.05 ? 'Pause' : 'Aperçu');
    if (stateEl && !sending) stateEl.textContent = label;
    preview.setAttribute('data-playback', playing ? 'playing' : 'paused');
    setPlayIcon(playing);
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
