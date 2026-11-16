'use strict';
/**
 * Assign new pull requests so none sit without an owner.
 *   - maintainers' own PRs: assigned to the author
 *   - everyone else (and bots): assigned to the maintainers
 * Review requests come from CODEOWNERS, so they are not repeated here.
 *
 * Runs on pull_request_target, so it must never check out or run PR code.
 */
const { config, isMaintainer, assign } = require('./lib');

module.exports = async function pr({ github, context, core }) {
  const pull = context.payload.pull_request;
  if (!pull || pull.assignees?.length) return;

  const author = pull.user.login;
  const authorOwnsIt = pull.user.type !== 'Bot' && (await isMaintainer(github, context, author));
  const assignees = authorOwnsIt ? [author] : config.maintainers;

  const assigned = await assign(github, context, pull.number, assignees);
  core.info(`Assigned PR #${pull.number} to ${assigned.join(', ') || 'nobody'}`);
};
