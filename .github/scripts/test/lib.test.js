'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const lib = require('../lib');

test('parseIssueForm reads sections, maps _No response_ to empty, ignores ### inside fences', () => {
  const body = [
    '### Area', '', 'Dashboard card', '',
    '### Logs', '', '```shell', '### not a heading', '```', '',
    '### Screenshot or recording', '', '_No response_',
  ].join('\n');
  const f = lib.parseIssueForm(body);
  assert.equal(f.Area, 'Dashboard card');
  assert.match(f.Logs, /not a heading/);
  assert.equal(f['Screenshot or recording'], '');
  assert.deepEqual(Object.keys(f), ['Area', 'Logs', 'Screenshot or recording']);
});

test('parseIssueForm on free text finds no fields', () => {
  assert.deepEqual(lib.parseIssueForm('just some words\nno headings'), {});
  assert.deepEqual(lib.parseIssueForm(null), {});
});

test('areaLabelFor maps every dropdown option from the config and nothing else', () => {
  for (const [option, label] of Object.entries(lib.config.areas)) {
    assert.equal(lib.areaLabelFor(option), label);
  }
  assert.equal(lib.areaLabelFor('Not sure'), null);
  assert.equal(lib.areaLabelFor(undefined), null);
});

test('redactSecrets removes the pinned vector token, stream and code', () => {
  const input = [
    'relay https://peek-relay-b9a8.onrender.com/telemetry/4b907ba136d0a7f2',
    'token ec3cb3699bd1284efb2fcfe056609e87edf4813b84e9ce84',
    'code K7M2-P4QX-9R / k7m2-p4qx-9r / K7M2P4QX9R',
  ].join('\n');
  const { text, kinds } = lib.redactSecrets(input);
  assert.ok(!/4b907ba136d0a7f2|ec3cb369|K7M2|k7m2/i.test(text), text);
  assert.deepEqual(kinds.sort(), ['pairing code', 'read token', 'relay stream ID or URL']);
  assert.match(text, /\/telemetry\/\[redacted-stream\]/);
});

test('redactSecrets handles bearer headers and token fields in pasted config', () => {
  const { text, kinds } = lib.redactSecrets(
    'Authorization: Bearer abcDEF123456789xyz\n{"token": "supersecretvalue1"}\ntoken=hunter2hunter2',
  );
  assert.ok(!/abcDEF|supersecret|hunter2/.test(text), text);
  assert.ok(kinds.includes('bearer token') && kinds.includes('token value'));
});

test('redactSecrets leaves ordinary text, placeholders and versions alone', () => {
  const clean = [
    'PeekESP 0.1.1 on Home Assistant 2026.11.2',
    'CONNECTION REFUSED, DEPLOYMENT FAILED, RESPECTFUL, 2222222222',
    'url shape is <relay>/telemetry/<stream> and sensor.dietpi_screen',
    'commit 9f698171ed81b15d1823a05fc7211befd50c8ae0',
  ].join('\n');
  const { text, kinds } = lib.redactSecrets(clean);
  assert.equal(text, clean);
  assert.deepEqual(kinds, []);
});

test('redactSecrets is idempotent', () => {
  const once = lib.redactSecrets('x /telemetry/4b907ba136d0a7f2 K7M2-P4QX-9R').text;
  const twice = lib.redactSecrets(once);
  assert.equal(twice.text, once);
  assert.deepEqual(twice.kinds, []);
});

test('parseCommands only reads unquoted, unfenced lines that start with a slash', () => {
  const body = [
    'hello', '/assign', '> /close', '  /confirm', '```', '/close', '```',
    '/label bug, area: card', '/etc/hosts', 'see /duplicate #3 inline', '/Help',
  ].join('\n');
  assert.deepEqual(lib.parseCommands(body), [
    { name: 'assign', args: '' },
    { name: 'label', args: 'bug, area: card' },
    { name: 'help', args: '' },
  ]);
});

test('parseCommands caps the number of commands per comment', () => {
  const body = Array.from({ length: 30 }, () => '/help').join('\n');
  assert.equal(lib.parseCommands(body).length, 10);
});

test('parseLogins and parseLabelArgs', () => {
  assert.deepEqual(lib.parseLogins('@alice, bob me not_a_login!'), ['alice', 'bob']);
  assert.deepEqual(lib.parseLogins('me'), []);
  assert.deepEqual(lib.parseLabelArgs('bug, "area: card" , ,help wanted'), [
    'bug',
    'area: card',
    'help wanted',
  ]);
});
