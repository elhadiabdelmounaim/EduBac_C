'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const publish = fs.readFileSync(path.join(__dirname, '../static/js/whiteboard-share-publish.js'), 'utf8');
const view = fs.readFileSync(path.join(__dirname, '../static/js/whiteboard-share-view.js'), 'utf8');

test('share sends one png of the current canvas to one classroom', () => {
  assert.match(publish, /canvas\.toBlob/);
  assert.match(publish, /FormData/);
  assert.match(publish, /classroom_id/);
  assert.equal(publish.includes('classrooms.forEach'), false);
});

test('student viewer draws the image and does not expose drawing tools', () => {
  assert.match(view, /drawImage/);
  assert.equal(view.includes('beginPath'), false);
  assert.equal(view.includes('toBlob'), false);
  assert.match(view, /requestFullscreen/);
  assert.match(view, /WebSocket/);
  assert.match(view, /setInterval\(poll/);
});
