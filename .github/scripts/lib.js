'use strict';
/**
 * Shared helpers for the issue and pull request automation.
 *
 * Everything that does not need GitHub is a pure function so it can be unit
 * tested (see ./test). Everything that does takes the `github` client and
 * `context` that actions/github-script provides.
 *
 * Nothing here ever interpolates user text into a shell command or evaluates
 * it. Issue and comment bodies are only parsed as data.
 */
const fs = require('node:fs');
const path = require('node:path');

const GITHUB_DIR = path.resolve(__dirname, '..');
const readJson = (name) => JSON.parse(fs.readFileSync(path.join(GITHUB_DIR, name), 'utf8'));

const config = readJson('automation.json');
const labelDefs = readJson('labels.json');
const L = config.labels;

const BOT_MARKER = (name) => `<!-- peekesp-bot:${name} -->`;
const MAX_COMMANDS_PER_COMMENT = 10;
const MAINTAINER_ROLES = ['admin', 'maintain', 'write'];

/* ------------------------------------------------------------------ */
/* Pure helpers                                                        */
/* ------------------------------------------------------------------ */

/**
 * Parse the markdown GitHub renders for an issue form:
 *   ### Label\n\nanswer\n\n### Next label ...
 * Headings inside code fences are ignored (logs may contain "### ").
 * "_No response_" becomes "". Returns { label: answer }.
 */
function parseIssueForm(body) {
  const sections = {};
  let current = null;
  let fence = null;
  for (const line of String(body || '').split(/\r?\n/)) {
    const fenceMatch = line.match(/^\s*(`{3,}|~{3,})/);
    if (fenceMatch) {
      if (!fence) fence = fenceMatch[1][0];
      else if (fenceMatch[1][0] === fence) fence = null;
    } else if (!fence) {
      const heading = line.match(/^###\s+(.+?)\s*$/);
      if (heading) {
        current = heading[1];
        sections[current] = [];
        continue;
      }
    }
    if (current) sections[current].push(line);
  }
  const out = {};
  for (const [label, lines] of Object.entries(sections)) {
    const value = lines.join('\n').trim();
    out[label] = value === '_No response_' ? '' : value;
  }
  return out;
}

/** Label for the form's "Area" dropdown answer, or null. */
function areaLabelFor(answer) {
  return config.areas[String(answer || '').trim()] || null;
}

/**
 * Things that must not sit in a public issue: they let anybody read a
 * machine's live stats off the relay. Each rule is idempotent (its own
 * replacement never matches again) so re-running on an edited post is safe.
 */
const PAIRING_CLASS = 'A-HJ-NP-Z2-9'; // the pairing alphabet: no I, O, 0, 1
const SECRET_RULES = [
  {
    kind: 'read token',
    re: /(?<![0-9A-Za-z])[0-9a-f]{48}(?![0-9A-Za-z])/g,
    replace: () => '[redacted-token]',
  },
  {
    kind: 'relay stream ID or URL',
    re: /(\/telemetry\/)([A-Za-z0-9_-][^\s"'`)\]>?#/]*)/g,
    replace: (_m, prefix) => `${prefix}[redacted-stream]`,
  },
  {
    kind: 'bearer token',
    re: /(\bBearer\s+)(?!\[redacted)([A-Za-z0-9._~+/=-]{12,})/gi,
    replace: (_m, prefix) => `${prefix}[redacted-token]`,
  },
  {
    kind: 'token value',
    re: /(["']?\btoken["']?\s*[:=]\s*["']?)(?!\[redacted)([^\s"',}]{8,})/gi,
    replace: (_m, prefix) => `${prefix}[redacted-token]`,
  },
  {
    // "K7M2-P4QX-9R", the way the device screen groups it
    kind: 'pairing code',
    re: new RegExp(
      `(?<![0-9A-Za-z])[${PAIRING_CLASS}]{4}-[${PAIRING_CLASS}]{4}-[${PAIRING_CLASS}]{2}(?![0-9A-Za-z])`,
      'gi',
    ),
    replace: () => '[redacted-pairing-code]',
  },
  {
    // "K7M2P4QX9R": ten upper-case characters of the alphabet. Needs a digit
    // and a letter so ordinary upper-case words are left alone.
    kind: 'pairing code',
    re: new RegExp(`(?<![0-9A-Za-z])[${PAIRING_CLASS}]{10}(?![0-9A-Za-z])`, 'g'),
    accept: (m) => /\d/.test(m) && /[A-Z]/.test(m),
    replace: () => '[redacted-pairing-code]',
  },
];

/** Returns { text, kinds } where kinds lists what was removed (deduplicated). */
function redactSecrets(input) {
  let text = String(input ?? '');
  const kinds = new Set();
  for (const rule of SECRET_RULES) {
    text = text.replace(rule.re, (...args) => {
      const match = args[0];
      if (rule.accept && !rule.accept(match)) return match;
      kinds.add(rule.kind);
      return rule.replace(...args);
    });
  }
  return { text, kinds: [...kinds] };
}

/**
 * Slash commands: only lines that START with "/" count, and never inside a
 * code fence or a quote, so pasted logs and replies cannot trigger anything.
 */
function parseCommands(body) {
  const commands = [];
  let fenced = false;
  for (const line of String(body || '').split(/\r?\n/)) {
    if (/^\s*(```|~~~)/.test(line)) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    const m = line.match(/^\/([a-z][a-z-]*)(?:[ \t]+(.*?))?[ \t]*$/i);
    if (m) commands.push({ name: m[1].toLowerCase(), args: (m[2] || '').trim() });
  }
  return commands.slice(0, MAX_COMMANDS_PER_COMMENT);
}

const LOGIN_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;

/** "@a, @b me" -> ['a', 'b']. "me" and anything that is not a login is dropped. */
function parseLogins(args) {
  return String(args || '')
    .split(/[\s,]+/)
    .map((t) => t.replace(/^@/, ''))
    .filter((t) => t && t.toLowerCase() !== 'me' && LOGIN_RE.test(t));
}

/** "bug, area: card" -> ['bug', 'area: card']. Commas separate: names contain spaces. */
function parseLabelArgs(args) {
  return String(args || '')
    .split(',')
    .map((t) => t.trim().replace(/^["'`]|["'`]$/g, ''))
    .filter(Boolean)
    .slice(0, 5);
}

const hasLabel = (issue, name) => (issue.labels || []).some((l) => (l.name ?? l) === name);
const isConfiguredMaintainer = (login) =>
  config.maintainers.some((m) => m.toLowerCase() === String(login).toLowerCase());

/* ------------------------------------------------------------------ */
/* GitHub helpers                                                      */
/* ------------------------------------------------------------------ */

async function ensureLabels(github, context, names) {
  const { owner, repo } = context.repo;
  for (const name of names) {
    try {
      await github.rest.issues.getLabel({ owner, repo, name });
    } catch (err) {
      if (err.status !== 404) throw err;
      const def = labelDefs.find((d) => d.name === name) || {};
      await github.rest.issues.createLabel({
        owner,
        repo,
        name,
        color: def.color || 'ededed',
        description: def.description || '',
      });
    }
  }
}

async function addLabels(github, context, number, names) {
  const wanted = [...new Set(names.filter(Boolean))];
  if (!wanted.length) return;
  await ensureLabels(github, context, wanted);
  await github.rest.issues.addLabels({ ...context.repo, issue_number: number, labels: wanted });
}

async function removeLabel(github, context, number, name) {
  try {
    await github.rest.issues.removeLabel({ ...context.repo, issue_number: number, name });
  } catch (err) {
    if (err.status !== 404) throw err; // not on the issue: nothing to do
  }
}

/** The bot's own comment carrying a hidden marker, or undefined. */
async function findBotComment(github, context, number, marker) {
  const existing = await github.paginate(github.rest.issues.listComments, {
    ...context.repo,
    issue_number: number,
    per_page: 100,
  });
  return existing.find((c) => c.user?.type === 'Bot' && c.body?.includes(marker));
}

/** Create or update the bot's own comment identified by a hidden marker. */
async function upsertComment(github, context, number, marker, body) {
  const full = `${body}\n\n${marker}`;
  const mine = await findBotComment(github, context, number, marker);
  if (mine) {
    await github.rest.issues.updateComment({ ...context.repo, comment_id: mine.id, body: full });
  } else {
    await github.rest.issues.createComment({ ...context.repo, issue_number: number, body: full });
  }
}

async function isMaintainer(github, context, login) {
  if (isConfiguredMaintainer(login)) return true;
  try {
    const { data } = await github.rest.repos.getCollaboratorPermissionLevel({
      ...context.repo,
      username: login,
    });
    return MAINTAINER_ROLES.includes(data.role_name) || MAINTAINER_ROLES.includes(data.permission);
  } catch (err) {
    if (err.status === 404) return false;
    throw err;
  }
}

/** Assign; returns the logins GitHub actually accepted (it silently drops the rest). */
async function assign(github, context, number, logins) {
  const wanted = [...new Set(logins)];
  if (!wanted.length) return [];
  const { data } = await github.rest.issues.addAssignees({
    ...context.repo,
    issue_number: number,
    assignees: wanted,
  });
  const got = new Set((data.assignees || []).map((a) => a.login.toLowerCase()));
  return wanted.filter((l) => got.has(l.toLowerCase()));
}

module.exports = {
  config,
  labelDefs,
  L,
  BOT_MARKER,
  parseIssueForm,
  areaLabelFor,
  redactSecrets,
  parseCommands,
  parseLogins,
  parseLabelArgs,
  hasLabel,
  isConfiguredMaintainer,
  ensureLabels,
  addLabels,
  removeLabel,
  findBotComment,
  upsertComment,
  isMaintainer,
  assign,
};
