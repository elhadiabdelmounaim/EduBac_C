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
