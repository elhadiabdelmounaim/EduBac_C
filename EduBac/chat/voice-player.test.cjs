'use strict';

// Dependency-free behavioral smoke test, not a substitute for real media/browser tests.
// Run from any directory: node EduBac/chat/voice-player.test.cjs
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

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
  }

  addEventListener(name, callback) {
    (this.events[name] ||= []).push(callback);
  }

  removeEventListener(name, callback) {
    this.events[name] = (this.events[name] || []).filter(fn => fn !== callback);
  }

  emit(name) {
    (this.events[name] || []).slice().forEach(callback => callback());
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
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
    if (!value.includes('chat-voice-timeline')) return;
    // Model only the controls the player creates; no HTML parser dependency.
    this.controlsMap = {};
    for (const name of ['play', 'stop', 'seek', 'elapsed', 'duration', 'status']) {
      const control = new Element(name === 'seek' ? 'input' : 'div');
      control.disabled = name === 'seek';
      control.value = '0';
      this.controlsMap['.chat-voice-' + name] = control;
    }
  }
}

class Audio extends Element {
  constructor() {
    super('audio');
    this.className = 'chat-voice-player';
    this.controls = true;
    this.paused = true;
    this.ended = false;
    this.duration = NaN;
    this.currentTime = 0;
    this.readyState = 0;
    this.error = null;
    this.rejectPlay = false;
    this.playCalls = 0;
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
  const filename = path.resolve(__dirname, '../static/js/chat-voice.js');
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    window, document, WeakMap, Number, String,
  }, { filename });

  const row = new Element();
  const first = new Audio();
  const second = new Audio();
  document.appendChild(row);
  row.appendChild(first);
  row.appendChild(second);
  assert.equal(first.controls, true, 'native fallback exists before enhancement');
  window.EduBacVoice.enhance(row);
  const firstWrapper = first.parentNode;
  const secondWrapper = second.parentNode;
  const control = (wrapper, name) => wrapper.querySelector('.chat-voice-' + name);
  const click = (wrapper, name) => control(wrapper, name).emit('click');

  assert(first.hidden && !first.controls, 'successful enhancement hides native controls');
  assert.equal(first.playCalls + second.playCalls, 0, 'enhancement never autoplays');
  assert(control(firstWrapper, 'seek').disabled, 'unknown duration disables seeking');
  assert.equal(control(firstWrapper, 'duration').textContent, '—');

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
  assert(control(firstWrapper, 'seek').disabled, 'Infinity disables seeking');
  assert(control(firstWrapper, 'status').textContent.includes('Durée indisponible'));
  click(firstWrapper, 'play');
  await Promise.resolve();
  assert(!first.paused, 'Infinity does not block playback');
  click(firstWrapper, 'play');
  assert(first.paused, 'play button toggles pause');
  assert.equal(control(firstWrapper, 'play').attrs['aria-label'], 'Lire le message vocal');

  first.duration = 83.4;
  first.emit('durationchange');
  assert.equal(control(firstWrapper, 'duration').textContent, '1:23');
  assert(!control(firstWrapper, 'seek').disabled, 'finite duration enables seeking');
  control(firstWrapper, 'seek').value = '23.2';
  control(firstWrapper, 'seek').emit('input');
  assert.equal(first.currentTime, 23.2, 'seek changes playback position');
  assert.equal(control(firstWrapper, 'elapsed').textContent, '0:23');
  assert(control(firstWrapper, 'seek').attrs['aria-valuetext'].includes('sur 1:23'));

  click(firstWrapper, 'play');
  await Promise.resolve();
  assert(!first.paused);
  assert.equal(control(firstWrapper, 'play').attrs['aria-label'], 'Mettre en pause');
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

  click(firstWrapper, 'play');
  await Promise.resolve();
  first.currentTime = 41.8;
  click(firstWrapper, 'stop');
  assert(first.paused, 'reset pauses playback');
  assert.equal(first.currentTime, 0, 'reset returns to the beginning');
  assert.equal(control(firstWrapper, 'elapsed').textContent, '0:00');

  first.ended = true;
  first.currentTime = 83.4;
  first.emit('ended');
  assert.equal(first.currentTime, 0, 'ended resets position');
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
  assert(control(firstWrapper, 'seek').disabled, 'audio error disables seeking');
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

  console.log('PASS: voice-player mock-DOM tests (play/pause, reset, seek, mutual exclusion, idempotency, rejection, unavailable/Infinity duration, media error/retry, hidden page and page exit).');
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
