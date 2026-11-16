'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeFake, context, core, bugBody } = require('./fake-github');
const triage = require('../triage');
const comments = require('../comments');
const pr = require('../pr');
const syncLabels = require('../sync-labels');
const lib = require('../lib');

const reporter = { login: 'alice', type: 'User' };
const issueOf = (over = {}) => ({
  number: 7,
  state: 'open',
  user: reporter,
  labels: [{ name: 'bug' }, { name: 'needs-triage' }],
  assignees: [],
  body: bugBody({ logs: '```\nboom\n```' }),
  ...over,
});

async function runTriage(issue, action = 'opened', senderLogin = 'alice', fake = {}) {
  const f = makeFake({ issue, ...fake });
  await triage({
    github: f.github,
    core,
    context: context({ action, issue, sender: { login: senderLogin, type: 'User' } }),
  });
  return f.state;
}

/* ----------------------------- triage ----------------------------- */

test('triage: a complete bug report gets its area label, needs-triage, an assignee and no comment', async () => {
  const s = await runTriage(issueOf());
  assert.ok(s.labels.has('area: card') && s.labels.has('needs-triage'));
  assert.ok(!s.labels.has('needs-info'));
  assert.deepEqual([...s.assignees], ['rhshourav']);
  assert.equal(s.comments.length, 0);
});

test('triage: a bug report with no logs and no screenshot is held for info, with one comment', async () => {
  const s = await runTriage(issueOf({ body: bugBody() }));
  assert.ok(s.labels.has('needs-info'));
  assert.ok(!s.labels.has('needs-triage'));
  assert.equal(s.comments.length, 1);
  assert.match(s.comments[0].body, /custom_components\.peekesp: debug/);
  assert.deepEqual([...s.assignees], ['rhshourav']);
});

test('triage: a screenshot alone counts as evidence', async () => {
  const s = await runTriage(issueOf({ body: bugBody({ shot: '![image](https://x/y.png)' }) }));
  assert.ok(!s.labels.has('needs-info'));
});

test('triage: a feature request (no evidence fields) is never held for info', async () => {
  const body = '### Area\n\nSetup and pairing\n\n### Problem\n\nI want X';
  const s = await runTriage(issueOf({ body, labels: [{ name: 'enhancement' }] }));
  assert.ok(s.labels.has('area: setup') && s.labels.has('needs-triage'));
  assert.ok(!s.labels.has('needs-info'));
  assert.equal(s.comments.length, 0);
});

test('triage: existing assignees are kept', async () => {
  const s = await runTriage(issueOf({ assignees: [{ login: 'bob' }] }));
  assert.deepEqual([...s.assignees], ['bob']);
});

test('triage: secrets in the body are redacted, labelled and explained', async () => {
  const secret = 'https://r.example/telemetry/4b907ba136d0a7f2 ec3cb3699bd1284efb2fcfe056609e87edf4813b84e9ce84';
  const s = await runTriage(issueOf({ body: bugBody({ logs: 'x', secret }) }));
  assert.ok(!/4b907ba136d0a7f2|ec3cb369/.test(s.body), s.body);
  assert.ok(s.labels.has('secrets-redacted'));
  assert.equal(s.comments.length, 1);
  assert.match(s.comments[0].body, /edit history/);
});

test('triage: editing in the missing evidence clears needs-info', async () => {
  const first = makeFake({ issue: issueOf({ body: bugBody() }) });
  const opened = issueOf({ body: bugBody() });
  await triage({ github: first.github, core, context: context({ action: 'opened', issue: opened, sender: reporter }) });
  const edited = issueOf({ body: bugBody({ logs: 'now with logs' }), labels: [{ name: 'needs-info' }] });
  await triage({ github: first.github, core, context: context({ action: 'edited', issue: edited, sender: reporter }) });
  assert.ok(!first.state.labels.has('needs-info'));
  assert.ok(first.state.labels.has('needs-triage'));
});

test('triage: someone else editing does not clear needs-info', async () => {
  const f = makeFake({ issue: issueOf({ body: bugBody() }) });
  await triage({ github: f.github, core, context: context({ action: 'opened', issue: issueOf({ body: bugBody() }), sender: reporter }) });
  const edited = issueOf({ body: bugBody({ logs: 'x' }), labels: [{ name: 'needs-info' }] });
  await triage({ github: f.github, core, context: context({ action: 'edited', issue: edited, sender: { login: 'mallory', type: 'User' } }) });
  assert.ok(f.state.labels.has('needs-info'));
});

test('triage: bots and pull requests are ignored; reopening drops stale', async () => {
  const bot = makeFake();
  await triage({ github: bot.github, core, context: context({ action: 'opened', issue: issueOf(), sender: { login: 'x[bot]', type: 'Bot' } }) });
  assert.equal(bot.state.labels.size, 0);

  const pull = makeFake();
  await triage({ github: pull.github, core, context: context({ action: 'opened', issue: issueOf({ pull_request: {} }), sender: reporter }) });
  assert.equal(pull.state.labels.size, 0);

  const re = makeFake({ issue: { labels: [{ name: 'stale' }] } });
  await triage({ github: re.github, core, context: context({ action: 'reopened', issue: issueOf(), sender: reporter }) });
  assert.ok(!re.state.labels.has('stale'));
});

test('triage: creates labels that do not exist yet', async () => {
  const f = makeFake({ issue: issueOf(), repoLabels: [] });
  await triage({ github: f.github, core, context: context({ action: 'opened', issue: issueOf(), sender: reporter }) });
  assert.ok(f.state.repoLabels.has('area: card') && f.state.repoLabels.has('needs-triage'));
});

/* ----------------------------- comments ---------------------------- */

async function runComment(body, { actor = 'alice', issue = issueOf(), perms = {}, ...fake } = {}) {
  const f = makeFake({ issue, permissions: perms, existingIssues: [3], repoLabels: ['bug', 'help wanted'], ...fake });
  const comment = { id: 55, body, user: { login: actor, type: 'User' } };
  await comments({
    github: f.github,
    core,
    context: context({ action: 'created', issue, comment, sender: comment.user }),
  });
  return f.state;
}

test('comments: anyone can /assign themselves', async () => {
  const s = await runComment('/assign', { actor: 'carol' });
  assert.ok(s.assignees.has('carol'));
  assert.deepEqual(s.reactions, ['+1']);
});

test('comments: /assign is refused when another contributor already has the issue', async () => {
  const issue = issueOf({ assignees: [{ login: 'bob' }] });
  const s = await runComment('/assign', { actor: 'carol', issue });
  assert.ok(!s.assignees.has('carol'));
  assert.deepEqual(s.reactions, ['confused']);
  assert.match(s.comments[0].body, /already assigned to @bob/);
});

test('comments: /assign works when only a maintainer holds it', async () => {
  const issue = issueOf({ assignees: [{ login: 'rhshourav' }] });
  const s = await runComment('/assign', { actor: 'carol', issue });
  assert.ok(s.assignees.has('carol'));
});

test('comments: a self-assign GitHub refuses is reported, not claimed', async () => {
  const s = await runComment('/assign', { actor: 'carol', assignable: [] });
  assert.deepEqual(s.reactions, ['confused']);
});

test('comments: maintainer-only commands are denied to everyone else and change nothing', async () => {
  const s = await runComment('/label bug\n/close\n/confirm\n/assign @dave', { actor: 'carol', perms: { carol: 'read' } });
  assert.ok(!s.labels.has('confirmed') && s.state === 'open' && !s.assignees.has('dave'));
  assert.deepEqual(s.reactions, ['confused']);
  assert.equal(s.comments[0].body.match(/only maintainers/g).length, 4);
});

test('comments: a collaborator with write access is a maintainer', async () => {
  const s = await runComment('/confirm', { actor: 'erin', perms: { erin: 'write' } });
  assert.ok(s.labels.has('confirmed') && !s.labels.has('needs-triage'));
});

test('comments: /label adds existing labels and reports unknown ones', async () => {
  const s = await runComment('/label help wanted, nonsense', { actor: 'rhshourav' });
  assert.ok(s.labels.has('help wanted') && !s.labels.has('nonsense'));
  assert.match(s.comments[0].body, /no such label: `nonsense`/);
});

test('comments: /duplicate closes as not planned and labels it; bad targets are rejected', async () => {
  const ok = await runComment('/duplicate #3', { actor: 'rhshourav' });
  assert.equal(ok.state, 'closed');
  assert.equal(ok.stateReason, 'not_planned');
  assert.ok(ok.labels.has('duplicate'));
  assert.match(ok.comments[0].body, /duplicate of #3/);

  const missing = await runComment('/duplicate #999', { actor: 'rhshourav' });
  assert.equal(missing.state, 'open');
  const self = await runComment('/duplicate #7', { actor: 'rhshourav' });
  assert.equal(self.state, 'open');
});

test('comments: /needs-info labels, moves off needs-triage and asks the reporter', async () => {
  const s = await runComment('/needs-info which Home Assistant version?', { actor: 'rhshourav' });
  assert.ok(s.labels.has('needs-info') && !s.labels.has('needs-triage'));
  assert.match(s.comments[0].body, /@alice/);
  assert.match(s.comments[0].body, /> which Home Assistant version\?/);
});

test('comments: the reporter can reopen their own issue, a stranger cannot', async () => {
  const closed = issueOf({ state: 'closed' });
  const own = await runComment('/reopen', { actor: 'alice', issue: closed });
  assert.equal(own.state, 'open');
  const other = await runComment('/reopen', { actor: 'mallory', issue: closed });
  assert.equal(other.state, 'closed');
});

test('comments: the reporter replying clears needs-info', async () => {
  const issue = issueOf({ labels: [{ name: 'needs-info' }] });
  const s = await runComment('here are the logs', { actor: 'alice', issue });
  assert.ok(!s.labels.has('needs-info') && s.labels.has('needs-triage'));
  assert.equal(s.reactions.length, 0);
});

test('comments: someone else replying does not clear needs-info', async () => {
  const issue = issueOf({ labels: [{ name: 'needs-info' }] });
  const s = await runComment('same here', { actor: 'bob', issue });
  assert.ok(s.labels.has('needs-info'));
});

test('comments: secrets in a comment are scrubbed and explained', async () => {
  const s = await runComment('my code is K7M2-P4QX-9R', { actor: 'alice' });
  assert.ok(!/K7M2/.test(s.updatedComments.get(55)));
  assert.ok(s.labels.has('secrets-redacted'));
  assert.match(s.comments[0].body, /a comment by @alice/);
});

test('comments: commands inside code blocks, quotes and unknown commands do nothing', async () => {
  const s = await runComment('```\n/close\n```\n> /close\n/frobnicate', { actor: 'rhshourav' });
  assert.equal(s.state, 'open');
  assert.equal(s.reactions.length, 0);
  assert.equal(s.comments.length, 0);
});

test('comments: an API failure in one command is reported and does not stop the rest', async () => {
  const f = makeFake({ issue: issueOf(), permissions: { erin: 'write' }, repoLabels: ['bug'] });
  f.github.rest.issues.update = async () => {
    throw Object.assign(new Error('boom'), { status: 500 });
  };
  const comment = { id: 9, body: '/close\n/confirm', user: { login: 'erin', type: 'User' } };
  await comments({ github: f.github, core, context: context({ action: 'created', issue: issueOf(), comment, sender: comment.user }) });
  assert.ok(f.state.labels.has('confirmed'));
  assert.match(f.state.comments[0].body, /`\/close`: .*failed unexpectedly/);
});

test('comments: bot comments are ignored', async () => {
  const f = makeFake({ issue: issueOf() });
  const comment = { id: 1, body: '/close', user: { login: 'github-actions[bot]', type: 'Bot' } };
  await comments({ github: f.github, core, context: context({ action: 'created', issue: issueOf(), comment, sender: comment.user }) });
  assert.equal(f.state.state, 'open');
});

/* ------------------------- pull requests, labels ------------------------ */

test('pr: maintainers own their PRs, other contributors and bots get the maintainers', async () => {
  const run = async (user, permissions = {}) => {
    const f = makeFake({ permissions });
    await pr({ github: f.github, core, context: context({ pull_request: { number: 4, user, assignees: [] } }) });
    return [...f.state.assignees];
  };
  assert.deepEqual(await run({ login: 'rhshourav', type: 'User' }), ['rhshourav']);
  assert.deepEqual(await run({ login: 'frank', type: 'User' }, { frank: 'write' }), ['frank']);
  assert.deepEqual(await run({ login: 'zed', type: 'User' }, { zed: 'read' }), ['rhshourav']);
  assert.deepEqual(await run({ login: 'dependabot[bot]', type: 'Bot' }), ['rhshourav']);
});

test('pr: an already assigned PR is left alone', async () => {
  const f = makeFake();
  await pr({ github: f.github, core, context: context({ pull_request: { number: 4, user: reporter, assignees: [{ login: 'x' }] } }) });
  assert.equal(f.state.assignees.size, 0);
});

test('sync-labels: creates missing labels, fixes drift, deletes nothing', async () => {
  const created = [];
  const updated = [];
  const github = {
    paginate: async () => [
      { name: 'bug', color: 'd73a4a', description: 'Something is not working' },
      { name: 'ci', color: '000000', description: 'old' },
      { name: 'unrelated', color: 'ffffff', description: '' },
    ],
    rest: {
      issues: {
        listLabelsForRepo: () => {},
        createLabel: async (p) => created.push(p.name),
        updateLabel: async (p) => updated.push(p.name),
      },
    },
  };
  await syncLabels({ github, core, context: context({}) });
  assert.deepEqual(updated, ['ci']);
  assert.equal(created.length, lib.labelDefs.length - 2);
  assert.ok(!created.includes('bug') && !created.includes('ci'));
});
