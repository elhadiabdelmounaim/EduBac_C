'use strict';

// Behavioral smoke test for the composer recorder. Run:
// node EduBac/chat/voice-recorder.test.cjs
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class El {
  constructor(id) {
    this.id = id || '';
    this.children = [];
    this.events = {};
    this.attrs = {};
    this.hidden = false;
    this.disabled = false;
    this.value = '0';
    this.textContent = '';
    this.innerHTML = '';
    this.parentNode = null;
    this._classes = new Set();
    this.style = {
      setProperty: (key, value) => { this.style[key] = value; },
    };
    this.classList = {
      add: (...names) => names.forEach((name) => this._classes.add(name)),
      remove: (...names) => names.forEach((name) => this._classes.delete(name)),
      toggle: (name, force) => {
        const has = this._classes.has(name);
        const next = force === undefined ? !has : !!force;
        if (next) this._classes.add(name);
        else this._classes.delete(name);
        return next;
      },
      contains: (name) => this._classes.has(name),
    };
  }

  addEventListener(name, callback) {
    (this.events[name] ||= []).push(callback);
  }

  emit(name, event) {
    (this.events[name] || []).slice().forEach((callback) => callback(event));
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }

  removeAttribute(name) {
    delete this.attrs[name];
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  querySelectorAll() {
    return [];
  }
}

function el(id) {
  return new El(id);
}

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function run() {
  const byId = {};
  const document = el('');
  document.readyState = 'loading';
  document.hidden = false;
  document.createElement = () => el('');
  document.getElementById = (id) => byId[id] || null;
  document.querySelectorAll = () => [];
  document.dispatchEvent = (event) => {
    document.emit(event.type, event);
    return !event.defaultPrevented;
  };
  const window = el('');
  const composer = el('');
  const nodes = {};
  for (const id of [
    'chatVoiceBtn', 'chatVoiceRecorder', 'chatForm', 'chatVoiceRec', 'chatVoicePreview',
    'chatVoiceCancel', 'chatVoiceStop', 'chatVoiceDelete', 'chatVoicePlay', 'chatVoiceSeek',
    'chatVoiceElapsed', 'chatVoiceDuration', 'chatVoicePreviewState', 'chatVoiceSend',
    'chatVoicePreviewAudio', 'chatVoiceRecTime', 'chatVoiceWave', 'chatVoiceRecLabel', 'chatEmojiPanel',
  ]) {
    nodes[id] = el(id);
    byId[id] = nodes[id];
  }
  const panel = nodes.chatVoiceRecorder;
  const form = nodes.chatForm;
  const rec = nodes.chatVoiceRec;
  const preview = nodes.chatVoicePreview;
  const mic = nodes.chatVoiceBtn;
  const audio = nodes.chatVoicePreviewAudio;
  const seek = nodes.chatVoiceSeek;
  const playBtn = nodes.chatVoicePlay;
  const sendBtn = nodes.chatVoiceSend;
  const deleteBtn = nodes.chatVoiceDelete;
  const stopBtn = nodes.chatVoiceStop;
  const cancelBtn = nodes.chatVoiceCancel;
  const stateEl = nodes.chatVoicePreviewState;
  const elapsedEl = nodes.chatVoiceElapsed;
  const durationEl = nodes.chatVoiceDuration;
  const wave = nodes.chatVoiceWave;
  nodes.chatVoiceRecLabel.textContent = 'Enregistrement';
  nodes.chatVoicePreviewState.textContent = 'Aperçu';
  panel.hidden = true;
  panel.setAttribute('data-state', 'idle');
  rec.hidden = true;
  preview.hidden = true;
  preview.setAttribute('data-playback', 'paused');
  form.closest = (selector) => (selector === '.chat-composer' ? composer : null);
  audio.paused = true;
  audio.ended = false;
  audio.duration = NaN;
  audio.currentTime = 0;
  audio._src = '';
  Object.defineProperty(audio, 'src', {
    configurable: true,
    get() { return this._src; },
    set(value) { this._src = String(value || ''); },
  });
  audio.removeAttribute = (name) => {
    if (name === 'src') audio._src = '';
    delete audio.attrs[name];
  };
  audio.load = () => {};
  audio.play = () => {
    audio.playCalls = (audio.playCalls || 0) + 1;
    audio.paused = false;
    audio.ended = false;
    audio.emit('play');
    return Promise.resolve();
  };
  audio.pause = () => {
    audio.paused = true;
    audio.emit('pause');
  };

  const objectUrls = new Map();
  const alerts = [];
  const sends = [];
  let micCalls = 0;
  let tracksStopped = 0;
  let releaseMic = null;
  const URLShim = {
    createObjectURL(blob) {
      const id = 'blob:voice-' + (objectUrls.size + 1);
      objectUrls.set(id, blob);
      return id;
    },
    revokeObjectURL(id) { objectUrls.delete(id); },
  };
  function stream() {
    return { getTracks: () => [{ stop() { tracksStopped += 1; } }] };
  }
  class FakeRecorder {
    constructor(mediaStream, options) {
      this.stream = mediaStream;
      this.mimeType = (options && options.mimeType) || 'audio/webm';
      this.state = 'inactive';
      this.ondataavailable = null;
      this.onstop = null;
      this.onerror = null;
    }
    start() { this.state = 'recording'; }
    stop() {
      if (this.state === 'inactive') return;
      this.state = 'inactive';
      const size = FakeRecorder.blobSize;
      const data = new Blob([new Uint8Array(size)], { type: this.mimeType });
      if (this.ondataavailable) this.ondataavailable({ data });
      if (this.onstop) this.onstop();
    }
    static isTypeSupported(type) { return String(type).indexOf('audio/webm') === 0; }
  }
  FakeRecorder.blobSize = 180;
  const navigator = {
    mediaDevices: {
      getUserMedia() {
        micCalls += 1;
        return Promise.resolve(stream());
      },
    },
  };
  window.MediaRecorder = FakeRecorder;
  const intervals = new Set();
  const rawSetInterval = setInterval;
  const rawClearInterval = clearInterval;

  document.addEventListener('edubac:voice-send', (event) => {
    event.preventDefault();
    sends.push(event.detail);
  });

  try {
  const filename = path.resolve(__dirname, '../static/js/chat-voice.js');
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    window,
    document,
    navigator,
    WeakMap,
    Number,
    String,
    Blob,
    File,
    URL: URLShim,
    CustomEvent,
    alert(message) { alerts.push(String(message)); },
    setInterval(callback, delay) {
      const id = rawSetInterval(callback, delay);
      intervals.add(id);
      return id;
    },
    clearInterval(id) {
      intervals.delete(id);
      rawClearInterval(id);
    },
  }, { filename });

  assert(window.EduBacVoice && typeof window.EduBacVoice.enhance === 'function', 'message player stays available');
  assert.equal(wave.children.length, 24, 'recording waveform is ready');
  assert.equal(panel.getAttribute('data-state'), 'idle');
  assert.equal(panel.hidden, true);
  assert.equal(form.hidden, false);
  assert.equal(sends.length, 0, 'loading the recorder never sends');

  async function begin() {
    mic.emit('click');
    await flush();
  }

  await begin();
  assert.equal(micCalls, 1);
  assert.equal(panel.getAttribute('data-state'), 'recording');
  assert.equal(panel.hidden, false);
  assert.equal(form.hidden, true, 'the text composer is hidden while recording');
  assert.equal(rec.hidden, false);
  assert.equal(preview.hidden, true);
  assert.equal(composer.classList.contains('is-voice-active'), true);
  assert.equal(nodes.chatVoiceRecLabel.textContent, 'Enregistrement');
  const callsAfterSecondClick = micCalls;
  mic.emit('click');
  await flush();
  assert.equal(micCalls, callsAfterSecondClick, 'a second click does not open another recording');
  assert.equal(sends.length, 0);

  stopBtn.emit('click');
  assert.equal(panel.getAttribute('data-state'), 'preview');
  assert.equal(rec.hidden, true);
  assert.equal(preview.hidden, false);
  assert.equal(form.hidden, true);
  assert.equal(sends.length, 0, 'stopping never sends the voice message');
  assert.ok(audio.src.startsWith('blob:voice-'), 'the preview keeps a playable object URL');
  assert.equal(objectUrls.size, 1);
  assert.equal(audio.playCalls || 0, 0, 'preview does not autoplay');
  const heldUrl = audio.src;

  audio.duration = 5;
  audio.emit('loadedmetadata');
  assert.equal(durationEl.textContent, '0:05');
  assert.equal(seek.disabled, false, 'a known duration enables seeking');
  assert.equal(stateEl.textContent, 'Aperçu');

  for (let replay = 0; replay < 3; replay += 1) {
    playBtn.emit('click');
    await flush();
    assert.equal(audio.paused, false, 'replay ' + (replay + 1) + ' starts playback');
    assert.equal(preview.getAttribute('data-playback'), 'playing');
    assert.equal(stateEl.textContent, 'Lecture');
    audio.currentTime = 1.4;
    audio.emit('timeupdate');
    assert.equal(elapsedEl.textContent, '0:01');
    playBtn.emit('click');
    assert.equal(audio.paused, true);
    assert.equal(preview.getAttribute('data-playback'), 'paused');
    assert.equal(stateEl.textContent, 'Pause');
  }
  assert.equal(sends.length, 0, 'replaying never sends');
  assert.equal(audio.src, heldUrl, 'the same recording stays available across replays');

  seek.value = '2.5';
  seek.emit('input');
  assert.equal(audio.currentTime, 2.5, 'the progress control seeks inside the preview');
  assert.equal(elapsedEl.textContent, '0:02');
  assert.equal(seek.getAttribute('aria-valuetext').includes('sur 0:05'), true);

  audio.currentTime = 5;
  audio.ended = true;
  audio.emit('ended');
  assert.equal(stateEl.textContent, 'Aperçu');
  playBtn.emit('click');
  await flush();
  assert.equal(audio.currentTime, 0, 'playing again after the end restarts the message');
  assert.equal(audio.paused, false);
  playBtn.emit('click');

  const beforePreviewClick = micCalls;
  mic.emit('click');
  await flush();
  assert.equal(micCalls, beforePreviewClick, 'the microphone stays inactive during preview');

  deleteBtn.emit('click');
  assert.equal(panel.getAttribute('data-state'), 'idle');
  assert.equal(form.hidden, false);
  assert.equal(audio.src, '');
  assert.equal(objectUrls.size, 0, 'delete revokes the preview');
  assert.equal(sends.length, 0, 'delete does not send');
  assert.equal(composer.classList.contains('is-voice-active'), false);

  await begin();
  stopBtn.emit('click');
  const failedUrl = audio.src;
  assert.equal(objectUrls.size, 1);
  sendBtn.emit('click');
  assert.equal(sends.length, 1);
  assert.equal(sendBtn.disabled, true);
  assert.ok(sends[0].file instanceof File);
  assert.ok(sends[0].file.size >= 100);
  assert.match(sends[0].file.name, /^voice_\d+\.webm$/);
  assert.equal(sends[0].file.type.indexOf('audio/webm'), 0);
  sends[0].done(false);
  assert.equal(panel.getAttribute('data-state'), 'preview', 'a failed send keeps the preview');
  assert.equal(audio.src, failedUrl);
  assert.equal(objectUrls.has(failedUrl), true);
  assert.equal(sendBtn.disabled, false);
  sendBtn.emit('click');
  assert.equal(sends[1].file, sends[0].file, 'retry sends the same recording');
  sends[1].done(true);
  assert.equal(panel.getAttribute('data-state'), 'idle');
  assert.equal(objectUrls.has(failedUrl), false, 'the preview is released only after a successful send');
  assert.equal(form.hidden, false);

  await begin();
  cancelBtn.emit('click');
  assert.equal(panel.getAttribute('data-state'), 'idle');
  assert.equal(objectUrls.size, 0);
  assert.equal(sends.length, 2, 'cancel does not create a send');
  assert.ok(tracksStopped > 0);

  await begin();
  document.emit('keydown', { key: 'Escape' });
  assert.equal(panel.getAttribute('data-state'), 'idle');
  assert.equal(sends.length, 2);

  FakeRecorder.blobSize = 40;
  await begin();
  stopBtn.emit('click');
  assert.equal(panel.getAttribute('data-state'), 'idle');
  assert.ok(alerts.some((message) => message.includes('trop court')));
  assert.equal(objectUrls.size, 0);
  assert.equal(sends.length, 2);
  FakeRecorder.blobSize = 180;

  const savedGetUserMedia = navigator.mediaDevices.getUserMedia;
  navigator.mediaDevices.getUserMedia = () => {
    micCalls += 1;
    return Promise.reject(new Error('denied'));
  };
  mic.emit('click');
  await flush();
  assert.ok(alerts.some((message) => message.includes('Autorisez le micro')));
  assert.equal(panel.getAttribute('data-state'), 'idle');
  navigator.mediaDevices.getUserMedia = savedGetUserMedia;

  const savedDevices = navigator.mediaDevices;
  navigator.mediaDevices = null;
  mic.emit('click');
  assert.ok(alerts.some((message) => message.includes('non supporté')));
  navigator.mediaDevices = savedDevices;

  micCalls = 0;
  navigator.mediaDevices.getUserMedia = () => new Promise((resolve) => {
    micCalls += 1;
    releaseMic = resolve;
  });
  mic.emit('click');
  mic.emit('click');
  assert.equal(micCalls, 1, 'the permission request cannot be started twice');
  releaseMic(stream());
  await flush();
  assert.equal(panel.getAttribute('data-state'), 'recording');
  window.emit('pagehide');
  assert.equal(panel.getAttribute('data-state'), 'idle');
  assert.equal(objectUrls.size, 0, 'leaving the page discards an in-progress recording');
  assert.equal(sends.length, 2);

  navigator.mediaDevices.getUserMedia = savedGetUserMedia;
  await begin();
  stopBtn.emit('click');
  assert.equal(objectUrls.size, 1);
  window.emit('pagehide');
  assert.equal(panel.getAttribute('data-state'), 'idle');
  assert.equal(audio.src, '');
  assert.equal(objectUrls.size, 0, 'leaving the page revokes an unsent preview');
  assert.equal(sends.length, 2);

  const chatJs = fs.readFileSync(path.resolve(__dirname, '../static/js/chat.js'), 'utf8');
  assert.equal(chatJs.includes('sendMessage(file, true)'), false);
  assert.equal(chatJs.includes("addEventListener('edubac:voice-send'"), true);
  assert.equal(chatJs.includes('sendMessage(detail.file, true)'), true);
  assert.equal(chatJs.includes("var body = isVoice ? '' : (input.value || '').trim();"), true);

  console.log('PASS: voice recorder waits for an explicit send (record, replay, seek, delete, retry, cancel, short recording, page leave).');
  } finally {
    for (const id of intervals) rawClearInterval(id);
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
