'use strict';
/**
 * New and edited issues.
 *
 *   opened    scrub pairing codes / tokens, label by Area, ask for evidence on
 *             bug reports that have none, assign the maintainers
 *   edited    scrub again; if the reporter added the missing evidence, clear
 *             `needs-info`
 *   reopened  drop `stale`
 *
 * Runs on the `issues` event with a read/write token, so it only ever treats
 * the issue text as data.
 */
const {
  config,
  L,
  BOT_MARKER,
  parseIssueForm,
  areaLabelFor,
  redactSecrets,
  hasLabel,
  addLabels,
  removeLabel,
  findBotComment,
  upsertComment,
  assign,
} = require('./lib');
const messages = require('./messages');

const NEEDS_INFO_MARKER = BOT_MARKER('needs-evidence');

const isBugForm = (fields) =>
  config.form.evidenceFields.every((f) => Object.hasOwn(fields, f));
const hasEvidence = (fields) =>
  config.form.evidenceFields.some((f) => (fields[f] || '').trim() !== '');

module.exports = async function triage({ github, context, core }) {
  const { action, issue, sender } = context.payload;
  if (!issue || issue.pull_request || sender?.type === 'Bot') return;
  const number = issue.number;

  if (action === 'reopened') {
    await removeLabel(github, context, number, L.stale);
    return;
  }

  // 1. Secrets first: nothing below should read or quote an unredacted body.
  const scrubbed = redactSecrets(issue.body);
  if (scrubbed.kinds.length) {
    await github.rest.issues.update({ ...context.repo, issue_number: number, body: scrubbed.text });
    await addLabels(github, context, number, [L.secretsRedacted]);
    await upsertComment(
      github,
      context,
      number,
      BOT_MARKER('secrets-issue'),
      messages.secretsNotice(scrubbed.kinds, 'your report'),
    );
    core.info(`Redacted ${scrubbed.kinds.join(', ')} from #${number}`);
  }

  const fields = parseIssueForm(scrubbed.text);

  // 2. The reporter filled in what we asked for by editing the report.
  if (action === 'edited') {
    const reporterEdited = sender?.login === issue.user.login;
    if (reporterEdited && hasLabel(issue, L.needsInfo) && isBugForm(fields) && hasEvidence(fields)) {
      if (await findBotComment(github, context, number, NEEDS_INFO_MARKER)) {
        await removeLabel(github, context, number, L.needsInfo);
        await addLabels(github, context, number, [L.needsTriage]);
      }
    }
    return;
  }

  // 3. New issue.
  const needsInfo = isBugForm(fields) && !hasEvidence(fields);
  const area = areaLabelFor(fields[config.form.areaField]);
  await addLabels(github, context, number, [area, needsInfo ? L.needsInfo : L.needsTriage]);

  if (needsInfo) {
    // The form template applies needs-triage itself; this one is waiting on the reporter.
    await removeLabel(github, context, number, L.needsTriage);
    await upsertComment(
      github,
      context,
      number,
      NEEDS_INFO_MARKER,
      messages.needsEvidence(issue.user.login),
    );
  }

  if (!issue.assignees?.length) {
    const assigned = await assign(github, context, number, config.maintainers);
    core.info(`Assigned #${number} to ${assigned.join(', ') || 'nobody'}`);
  }
};
