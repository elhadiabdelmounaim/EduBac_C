'use strict';

// Dependency-free behavioral smoke test, not a substitute for real media/browser tests.
// Run from any directory: node EduBac/chat/voice-player.test.cjs
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const CONTROL_NAMES = ['play', 'wave', 'elapsed', 'duration', 'speed', 'status'];

class Element {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.events = {};
    this.attrs = {};
    this.hidden = false;
    this.textContent = '';
    this.className = '';
    this.parentNode = null;
    this.style = { setProperty: (key, value) => { this.style[key] = value; } };
    this._classes = new Set();
    this.classList = {
      toggle: (name, force) => {
        const next = force === undefined ? !this._classes.has(name) : !!force;
        if (next) this._classes.add(name); else this._classes.delete(name);
        return next;
      },
      contains: (name) => this._classes.has(name),
      add: (name) => this._classes.add(name),
      remove: (name) => this._classes.delete(name),
    };
  }

  addEventListener(name, callback) {
    (this.events[name] ||= []).push(callback);
  }

  removeEventListener(name, callback) {
    this.events[name] = (this.events[name] || []).filter(fn => fn !== callback);
  }

  emit(name, event = {}) {
    (this.events[name] || []).slice().forEach(callback => callback(event));
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }

  appendChild(child) {
    child.remove();
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  insertBefore(child, reference) {
    child.remove();
    const index = this.children.indexOf(reference);
    assert.notEqual(index, -1, 'insertBefore reference must belong to this parent');
    this.children.splice(index, 0, child);
    child.parentNode = this;
  }

  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter(child => child !== this);
    this.parentNode = null;
  }

  matches(selector) {
    return selector === 'audio.chat-voice-player' &&
      this.tag === 'audio' && this.className === 'chat-voice-player';
  }

  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(child.matches(selector) ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }

  querySelector(selector) {
    return this.controlsMap && this.controlsMap[selector];
  }

  set innerHTML(value) {
    this.html = value;
    if (!value.includes('chat-voice-wave')) return;
    // Model only the controls the player creates; no HTML parser dependency.
    this.controlsMap = {};
    for (const name of CONTROL_NAMES) {
      const control = new Element(name === 'play' || name === 'speed' ? 'button' : 'div');
      this.controlsMap['.chat-voice-' + name] = control;
    }
    this.controlsMap['.chat-voice-wave'].getBoundingClientRect = () => ({ left: 100, width: 200 });
  }

  get innerHTML() {
    return this.html || '';
  }
}

class Audio extends Element {
  constructor(src) {
    super('audio');
    this.className = 'chat-voice-player';
    this.attrs.src = src;
    this.controls = true;
    this.preload = 'none';
    this.paused = true;
    this.ended = false;
    this.duration = NaN;
    this.currentTime = 0;
    this.readyState = 0;
    this.error = null;
    this.rejectPlay = false;
    this.playCalls = 0;
    this.playbackRate = 1;
    this.defaultPlaybackRate = 1;
  }

  play() {
    this.playCalls++;
    if (this.rejectPlay) return Promise.reject({ name: 'NotAllowedError' });
    this.paused = false;
    this.emit('play');
    this.emit('playing');
    return Promise.resolve();
  }

  pause() {
    const wasPlaying = !this.paused;
    this.paused = true;
    if (wasPlaying) this.emit('pause');
  }

  load() {
    this.error = null;
    this.emit('loadstart');
  }
}

async function run() {
  const document = new Element();
  document.readyState = 'complete';
  document.hidden = false;
  document.createElement = tag => new Element(tag);
  const window = new Element();
  const storage = {};
  window.localStorage = {
    getItem: key => (key in storage ? storage[key] : null),
    setItem: (key, value) => { storage[key] = String(value); },
  };
  const filename = path.resolve(__dirname, '../static/js/chat-voice.js');
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    window, document, WeakMap, Map, Number, String, Math, Promise,
  }, { filename });

  const row = new Element();
  const first = new Audio('/chat/attachments/1/');
  const second = new Audio('/chat/attachments/2/');
  document.appendChild(row);
  row.appendChild(first);
  row.appendChild(second);
  assert.equal(first.controls, true, 'native fallback exists before enhancement');
  window.EduBacVoice.enhance(row);
  const firstWrapper = first.parentNode;
  const secondWrapper = second.parentNode;
  const control = (wrapper, name) => wrapper.querySelector('.chat-voice-' + name);
  const click = (wrapper, name) => control(wrapper, name).emit('click');
  const wave = control(firstWrapper, 'wave');
  const playedBars = () => wave.children.filter(bar => bar.classList.contains('is-played')).length;

  assert(first.hidden && !first.controls, 'successful enhancement hides native controls');
  assert.equal(first.preload, 'metadata', 'without waveform analysis the duration is still loaded');
  assert.equal(first.playCalls + second.playCalls, 0, 'enhancement never autoplays');
  assert.equal(wave.children.length, 36, 'the waveform is drawn with vertical bars');
  assert(wave.children.every(bar => /%$/.test(bar.style.height)), 'every bar has a height');
  assert.equal(wave.attrs.role, undefined, 'role is set in markup, not via setAttribute');
  assert.equal(wave.attrs['aria-disabled'], 'true', 'unknown duration disables seeking');
  assert.equal(control(firstWrapper, 'duration').textContent, '—');
  assert.equal(control(firstWrapper, 'speed').textContent, '1×');

  const listenerCounts = Object.fromEntries(
    Object.entries(first.events).map(([name, callbacks]) => [name, callbacks.length])
  );
  window.EduBacVoice.enhance(row);
  window.EduBacVoice.enhance(first);
  assert.equal(first.parentNode, firstWrapper, 'idempotency preserves the wrapper');
  assert.equal(row.children.length, 2, 'idempotency does not add wrappers');
  for (const [name, count] of Object.entries(listenerCounts)) {
    assert.equal(first.events[name].length, count, 'idempotency preserves ' + name + ' listeners');
  }

  first.duration = Infinity;
  first.readyState = 1;
  first.emit('durationchange');
  assert.equal(control(firstWrapper, 'duration').textContent, '—');
  assert.equal(wave.attrs['aria-disabled'], 'true', 'Infinity disables seeking');
  assert(control(firstWrapper, 'status').textContent.includes('Durée indisponible'));
  click(firstWrapper, 'play');
  await Promise.resolve();
  assert(!first.paused, 'Infinity does not block playback');
  assert.equal(firstWrapper.attrs['data-state'], 'playing', 'the bubble shows the playing state');
  click(firstWrapper, 'play');
  assert(first.paused, 'play button toggles pause');
  assert.equal(firstWrapper.attrs['data-state'], 'paused');
  assert.equal(control(firstWrapper, 'play').attrs['aria-label'], 'Lire le message vocal');

  first.duration = 80;
  first.currentTime = 0;
  first.emit('durationchange');
  assert.equal(control(firstWrapper, 'duration').textContent, '1:20');
  assert.equal(wave.attrs['aria-disabled'], 'false', 'finite duration enables seeking');

  wave.emit('pointerdown', { clientX: 150, pointerId: 1, preventDefault() {} });
  assert.equal(first.currentTime, 20, 'clicking a quarter of the waveform seeks to a quarter');
  assert.equal(control(firstWrapper, 'elapsed').textContent, '0:20');
  assert.equal(playedBars(), 9, 'bars before the position are drawn as played');
  wave.emit('pointermove', { clientX: 200 });
  assert.equal(first.currentTime, 40, 'dragging keeps seeking');
  wave.emit('pointerup', {});
  wave.emit('pointermove', { clientX: 290 });
  assert.equal(first.currentTime, 40, 'moving after release does not seek');
  assert(wave.attrs['aria-valuetext'].includes('sur 1:20'));
  assert.equal(firstWrapper.classList.contains('is-started'), true, 'elapsed time is shown once started');

  wave.emit('keydown', { key: 'ArrowRight', preventDefault() {} });
  assert.equal(first.currentTime, 45, 'arrow keys move by five seconds');
  wave.emit('keydown', { key: 'ArrowLeft', preventDefault() {} });
  wave.emit('keydown', { key: 'ArrowLeft', preventDefault() {} });
  assert.equal(first.currentTime, 35);
  wave.emit('keydown', { key: 'Home', preventDefault() {} });
  assert.equal(first.currentTime, 0, 'Home returns to the beginning');

  click(firstWrapper, 'speed');
  assert.equal(control(firstWrapper, 'speed').textContent, '1,5×');
  assert.equal(control(secondWrapper, 'speed').textContent, '1,5×', 'speed is shared by every voice message');
  assert.equal(first.playbackRate, 1.5);
  assert.equal(second.playbackRate, 1.5);
  assert.equal(storage['edubac-voice-rate'], '1.5', 'the chosen speed is remembered');
  click(secondWrapper, 'speed');
  assert.equal(first.playbackRate, 2);
  click(firstWrapper, 'speed');
  assert.equal(first.playbackRate, 1, 'speed cycles back to 1×');

  click(firstWrapper, 'play');
  await Promise.resolve();
  assert(!first.paused);
  assert.equal(control(firstWrapper, 'play').attrs['aria-label'], 'Mettre en pause');
  first.currentTime = 30;
  click(firstWrapper, 'play');
  click(firstWrapper, 'play');
  await Promise.resolve();
  assert.equal(first.currentTime, 30, 'playback resumes where it was paused');
  click(secondWrapper, 'play');
  await Promise.resolve();
  assert(first.paused && !second.paused, 'starting another voice message pauses the first');

  document.hidden = true;
  document.emit('visibilitychange');
  assert(first.paused && second.paused, 'hiding the document pauses playback');
  click(firstWrapper, 'play');
  await Promise.resolve();
  assert(first.paused, 'play event while hidden cannot keep audio playing');
  document.hidden = false;
  document.emit('visibilitychange');
  assert(first.paused && second.paused, 'returning to the page never resumes automatically');

  first.ended = true;
  first.currentTime = 80;
  first.emit('ended');
  assert.equal(first.currentTime, 0, 'ended resets position');
  assert.equal(playedBars(), 0, 'ended clears the progress');
  assert.equal(firstWrapper.classList.contains('is-started'), false);
  assert.equal(control(firstWrapper, 'play').attrs['aria-label'], 'Lire le message vocal');
  first.ended = false;

  first.rejectPlay = true;
  click(firstWrapper, 'play');
  await Promise.resolve();
  assert(first.paused, 'rejected playback stays paused');
  assert(control(firstWrapper, 'status').textContent.includes('refusée'));
  assert.equal(control(firstWrapper, 'play').attrs['aria-label'], 'Lire le message vocal');

  first.error = { code: 4 };
  first.emit('error');
  assert(control(firstWrapper, 'status').textContent.includes('indisponible'));
  assert.equal(wave.attrs['aria-disabled'], 'true', 'audio error disables seeking');
  assert.equal(control(firstWrapper, 'play').attrs['aria-label'], 'Réessayer la lecture');
  first.rejectPlay = false;
  click(firstWrapper, 'play');
  await Promise.resolve();
  assert(!first.paused && !first.error, 'retry reloads failed media and plays');
  assert.equal(control(firstWrapper, 'status').textContent, '');

  window.emit('pagehide');
  assert(first.paused && second.paused, 'pagehide pauses playback');
  click(secondWrapper, 'play');
  await Promise.resolve();
  window.emit('beforeunload');
  assert(first.paused && second.paused, 'page exit pauses playback');

  console.log('PASS: voice-player mock-DOM tests (play/pause/resume, waveform click/drag/keyboard seek, played bars, shared speed 1×/1.5×/2×, mutual exclusion, idempotency, rejection, unavailable/Infinity duration, media error/retry, hidden page and page exit).');
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
