const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(
  new URL('../static/js/edubac-ui.js', `file://${__filename}`),
  'utf8',
);
const match = source.match(/function initPasswordToggle\(\) \{[\s\S]*?\n  \}/);
assert.ok(match, 'the production password-toggle handler exists');

const input = { type: 'password' };
const iconClasses = new Set(['bi', 'bi-eye']);
const buttonState = {
  target: 'loginPassword',
  attrs: { 'aria-label': 'Afficher le mot de passe', 'aria-pressed': 'false' },
};
let clickHandler;

function $(value) {
  if (value === document) return { on(_event, _selector, handler) { clickHandler = handler; } };
  if (value === '#loginPassword') return { length: 1, attr(name, val) {
    if (val === undefined) return input[name];
    input[name] = val;
    return this;
  } };
  if (value === button) return {
    data() { return buttonState.target; },
    find() { return $(icon); },
    attr(attrs) { Object.assign(buttonState.attrs, attrs); return this; },
  };
  if (value === icon) return {
    removeClass(name) { iconClasses.delete(name); return this; },
    addClass(name) { iconClasses.add(name); return this; },
  };
  throw new Error(`Unexpected jQuery selector: ${String(value)}`);
}

const document = {};
const button = {};
const icon = {};
vm.runInNewContext(`${match[0]}\ninitPasswordToggle();`, { $, document });
assert.equal(typeof clickHandler, 'function', 'a single delegated click handler is registered');

clickHandler.call(button);
assert.equal(input.type, 'text', 'first click reveals the password');
assert.ok(iconClasses.has('bi-eye-slash'));
assert.equal(buttonState.attrs['aria-pressed'], 'true');
assert.equal(buttonState.attrs['aria-label'], 'Masquer le mot de passe');

clickHandler.call(button);
assert.equal(input.type, 'password', 'second click hides the password again');
assert.ok(iconClasses.has('bi-eye'));
assert.equal(buttonState.attrs['aria-pressed'], 'false');
assert.equal(buttonState.attrs['aria-label'], 'Afficher le mot de passe');
console.log('PASS: login password toggle reveals on first click and hides on second.');
