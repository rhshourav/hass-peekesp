'use strict';
/**
 * Minimal in-memory stand-in for the parts of Octokit the automation uses.
 * It records what happened so tests can assert on outcomes, not on calls.
 */
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { status });

function makeFake({
  repoLabels = [],
  permissions = {},
  existingIssues = [],
  assignable = null, // null: everyone can be assigned; otherwise a list of logins
  issue = {},
} = {}) {
  const state = {
    repoLabels: new Map(repoLabels.map((n) => [n, { name: n }])),
    labels: new Set((issue.labels || []).map((l) => l.name ?? l)),
    assignees: new Set((issue.assignees || []).map((a) => a.login)),
    comments: [],
    reactions: [],
    state: issue.state || 'open',
    stateReason: null,
    body: issue.body,
    updatedComments: new Map(),
    nextId: 1000,
  };

  const rest = {
    issues: {
      getLabel: async ({ name }) => {
        if (!state.repoLabels.has(name)) throw httpError(404);
        return { data: state.repoLabels.get(name) };
      },
      createLabel: async ({ name }) => {
        state.repoLabels.set(name, { name });
        return { data: { name } };
      },
      addLabels: async ({ labels }) => {
        labels.forEach((l) => state.labels.add(l));
        return { data: [...state.labels].map((name) => ({ name })) };
      },
      removeLabel: async ({ name }) => {
        if (!state.labels.delete(name)) throw httpError(404);
        return { data: [] };
      },
      addAssignees: async ({ assignees }) => {
        assignees
          .filter((l) => assignable === null || assignable.includes(l))
          .forEach((l) => state.assignees.add(l));
        return { data: { assignees: [...state.assignees].map((login) => ({ login })) } };
      },
      removeAssignees: async ({ assignees }) => {
        assignees.forEach((l) => state.assignees.delete(l));
        return { data: {} };
      },
      get: async ({ issue_number }) => {
        if (!existingIssues.includes(issue_number)) throw httpError(404);
        return { data: { number: issue_number } };
      },
      update: async (params) => {
        if (params.body !== undefined) state.body = params.body;
        if (params.state) {
          state.state = params.state;
          state.stateReason = params.state_reason || null;
        }
        return { data: {} };
      },
      listComments: async () => ({ data: state.comments }),
      createComment: async ({ body }) => {
        const c = { id: state.nextId++, body, user: { type: 'Bot', login: 'github-actions[bot]' } };
        state.comments.push(c);
        return { data: c };
      },
      updateComment: async ({ comment_id, body }) => {
        const c = state.comments.find((x) => x.id === comment_id);
        if (c) c.body = body;
        else state.updatedComments.set(comment_id, body); // a human's comment being scrubbed
        return { data: {} };
      },
    },
    reactions: {
      createForIssueComment: async ({ content }) => {
        state.reactions.push(content);
        return { data: {} };
      },
    },
    repos: {
      getCollaboratorPermissionLevel: async ({ username }) => {
        if (!(username in permissions)) throw httpError(404);
        return { data: { permission: permissions[username], role_name: permissions[username] } };
      },
    },
  };

  const github = {
    rest,
    paginate: async (fn, params) => (await fn(params)).data,
  };
  return { github, state };
}

const context = (payload) => ({ repo: { owner: 'o', repo: 'r' }, payload });
const core = { info() {}, warning() {} };

/** Form body as GitHub renders it. */
function bugBody({ area = 'Dashboard card', logs = '', shot = '', secret = '' } = {}) {
  const v = (x) => x || '_No response_';
  return [
    '### Area',
    '',
    area,
    '',
    '### What happened?',
    '',
    `The card is blank. ${secret}`.trim(),
    '',
    '### Logs',
    '',
    v(logs),
    '',
    '### Screenshot or recording',
    '',
    v(shot),
  ].join('\n');
}

module.exports = { makeFake, context, core, bugBody };
