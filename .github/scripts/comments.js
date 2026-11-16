'use strict';
/**
 * Comments on issues and pull requests.
 *
 *   every comment   scrub pairing codes / tokens (also when edited)
 *   reporter reply  clears `needs-info`
 *   slash commands  /assign /unassign /label /unlabel /needs-info /confirm
 *                   /duplicate /wontfix /close /reopen /help
 *
 * Anyone can comment, so every privileged command checks the commenter's
 * repository permission first. Comment text is only ever parsed as data.
 */
const {
  L,
  BOT_MARKER,
  redactSecrets,
  parseCommands,
  parseLogins,
  parseLabelArgs,
  hasLabel,
  isConfiguredMaintainer,
  isMaintainer,
  addLabels,
  removeLabel,
  upsertComment,
  assign,
} = require('./lib');
const messages = require('./messages');

const OK = { ok: true };
const fail = (reason) => ({ ok: false, reason });
const MAINTAINERS_ONLY = 'only maintainers can do that';

module.exports = async function comments({ github, context, core }) {
  const { action, issue, comment, sender } = context.payload;
  if (!issue || !comment) return;
  if (sender?.type === 'Bot' || comment.user?.type === 'Bot') return;
  const number = issue.number;
  const actor = comment.user.login;

  // 1. Secrets.
  const scrubbed = redactSecrets(comment.body);
  if (scrubbed.kinds.length) {
    await github.rest.issues.updateComment({
      ...context.repo,
      comment_id: comment.id,
      body: scrubbed.text,
    });
    await addLabels(github, context, number, [L.secretsRedacted]);
    await upsertComment(
      github,
      context,
      number,
      BOT_MARKER(`secrets-comment-${comment.id}`),
      messages.secretsNotice(scrubbed.kinds, `a comment by @${actor}`),
    );
    core.info(`Redacted ${scrubbed.kinds.join(', ')} from comment ${comment.id}`);
  }
  if (action !== 'created') return;

  // 2. The reporter answered: it is the maintainers' turn again.
  if (actor === issue.user.login && hasLabel(issue, L.needsInfo)) {
    await removeLabel(github, context, number, L.needsInfo);
    await addLabels(github, context, number, [L.needsTriage]);
  }

  // 3. Commands.
  const commands = parseCommands(scrubbed.text).filter((c) => Object.hasOwn(HANDLERS, c.name));
  if (!commands.length) return;

  const ctx = { github, context, issue, number, actor, maintainer: undefined };
  const problems = [];
  const notes = [];
  for (const { name, args } of commands) {
    let result;
    try {
      result = await HANDLERS[name](ctx, args);
    } catch (err) {
      core.warning(`/${name} failed: ${err.message}`);
      result = fail(`\`/${name}\` failed unexpectedly (${err.status || 'error'}); a maintainer can look at the workflow log`);
    }
    if (!result.ok) problems.push(`\`/${name}\`: ${result.reason}`);
    if (result.note) notes.push(result.note);
  }

  await github.rest.reactions.createForIssueComment({
    ...context.repo,
    comment_id: comment.id,
    content: problems.length ? 'confused' : '+1',
  });
  const reply = [...notes, problems.length ? messages.commandProblems(actor, problems) : '']
    .filter(Boolean)
    .join('\n\n');
  if (reply) {
    await github.rest.issues.createComment({ ...context.repo, issue_number: number, body: reply });
  }
};

/* ------------------------------------------------------------------ */

async function requireMaintainer(ctx) {
  ctx.maintainer ??= await isMaintainer(ctx.github, ctx.context, ctx.actor);
  return ctx.maintainer;
}

async function labelExists(ctx, name) {
  try {
    const { data } = await ctx.github.rest.issues.getLabel({ ...ctx.context.repo, name });
    return data.name;
  } catch (err) {
    if (err.status === 404) return null;
    throw err;
  }
}

const closeIssue = (ctx, reason) =>
  ctx.github.rest.issues.update({
    ...ctx.context.repo,
    issue_number: ctx.number,
    state: 'closed',
    state_reason: reason,
  });

const HANDLERS = {
  async assign(ctx, args) {
    const others = parseLogins(args);
    if (others.length) {
      if (!(await requireMaintainer(ctx))) return fail(`assigning other people: ${MAINTAINERS_ONLY}`);
      const done = await assign(ctx.github, ctx.context, ctx.number, others);
      const missed = others.filter((l) => !done.includes(l));
      return missed.length
        ? fail(`GitHub would not assign ${missed.map((l) => `@${l}`).join(', ')} (they need repository access or to have commented here)`)
        : OK;
    }
    if (ctx.issue.state === 'closed') return fail('this is closed, reopen it first');
    const held = (ctx.issue.assignees || [])
      .map((a) => a.login)
      .filter((l) => l !== ctx.actor && !isConfiguredMaintainer(l));
    if (held.length) return fail(`already assigned to @${held[0]}; ask a maintainer to reassign`);
    const done = await assign(ctx.github, ctx.context, ctx.number, [ctx.actor]);
    return done.length ? OK : fail('GitHub would not let me assign you');
  },

  async unassign(ctx, args) {
    const others = parseLogins(args);
    if (others.length && !(await requireMaintainer(ctx))) {
      return fail(`unassigning other people: ${MAINTAINERS_ONLY}`);
    }
    await ctx.github.rest.issues.removeAssignees({
      ...ctx.context.repo,
      issue_number: ctx.number,
      assignees: others.length ? others : [ctx.actor],
    });
    return OK;
  },

  async label(ctx, args) {
    if (!(await requireMaintainer(ctx))) return fail(MAINTAINERS_ONLY);
    const found = [];
    const unknown = [];
    for (const name of parseLabelArgs(args)) {
      const real = await labelExists(ctx, name);
      (real ? found : unknown).push(real || name);
    }
    if (found.length) await addLabels(ctx.github, ctx.context, ctx.number, found);
    return unknown.length ? fail(`no such label: ${unknown.map((n) => `\`${n}\``).join(', ')}`) : OK;
  },

  async unlabel(ctx, args) {
    if (!(await requireMaintainer(ctx))) return fail(MAINTAINERS_ONLY);
    for (const name of parseLabelArgs(args)) {
      await removeLabel(ctx.github, ctx.context, ctx.number, name);
    }
    return OK;
  },

  async 'needs-info'(ctx, args) {
    if (!(await requireMaintainer(ctx))) return fail(MAINTAINERS_ONLY);
    await addLabels(ctx.github, ctx.context, ctx.number, [L.needsInfo]);
    await removeLabel(ctx.github, ctx.context, ctx.number, L.needsTriage);
    return { ok: true, note: messages.needsInfoRequest(ctx.issue.user.login, args) };
  },

  async confirm(ctx) {
    if (!(await requireMaintainer(ctx))) return fail(MAINTAINERS_ONLY);
    await addLabels(ctx.github, ctx.context, ctx.number, [L.confirmed]);
    await removeLabel(ctx.github, ctx.context, ctx.number, L.needsTriage);
    await removeLabel(ctx.github, ctx.context, ctx.number, L.needsInfo);
    return OK;
  },

  async duplicate(ctx, args) {
    if (!(await requireMaintainer(ctx))) return fail(MAINTAINERS_ONLY);
    const target = Number((args.match(/#?(\d+)/) || [])[1]);
    if (!target || target === ctx.number) return fail('use it as `/duplicate #123`');
    try {
      await ctx.github.rest.issues.get({ ...ctx.context.repo, issue_number: target });
    } catch (err) {
      if (err.status === 404) return fail(`#${target} does not exist`);
      throw err;
    }
    await addLabels(ctx.github, ctx.context, ctx.number, [L.duplicate]);
    await closeIssue(ctx, 'not_planned');
    return { ok: true, note: `Closing as a duplicate of #${target}. Please continue the discussion there.` };
  },

  async wontfix(ctx, args) {
    if (!(await requireMaintainer(ctx))) return fail(MAINTAINERS_ONLY);
    await addLabels(ctx.github, ctx.context, ctx.number, [L.wontfix]);
    await closeIssue(ctx, 'not_planned');
    return { ok: true, note: `Closing as not planned.${args ? `\n\n> ${args}` : ''}` };
  },

  async close(ctx) {
    if (!(await requireMaintainer(ctx))) return fail(MAINTAINERS_ONLY);
    await closeIssue(ctx, 'completed');
    return OK;
  },

  async reopen(ctx) {
    const isAuthor = ctx.actor === ctx.issue.user.login;
    if (!isAuthor && !(await requireMaintainer(ctx))) return fail(`reopening: ${MAINTAINERS_ONLY} or the author`);
    await ctx.github.rest.issues.update({
      ...ctx.context.repo,
      issue_number: ctx.number,
      state: 'open',
      state_reason: 'reopened',
    });
    return OK;
  },

  async help() {
    return { ok: true, note: messages.commandHelp() };
  },
};

module.exports.HANDLERS = HANDLERS;
