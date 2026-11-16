'use strict';
/**
 * Make the repository's labels match .github/labels.json: create the missing
 * ones, fix colour and description on the rest. Labels that are not listed
 * are left alone, so nothing is ever deleted.
 */
const { labelDefs } = require('./lib');

module.exports = async function syncLabels({ github, context, core }) {
  const { owner, repo } = context.repo;
  const existing = await github.paginate(github.rest.issues.listLabelsForRepo, {
    owner,
    repo,
    per_page: 100,
  });
  const byName = new Map(existing.map((l) => [l.name.toLowerCase(), l]));

  for (const def of labelDefs) {
    const current = byName.get(def.name.toLowerCase());
    if (!current) {
      await github.rest.issues.createLabel({ owner, repo, ...def });
      core.info(`created  ${def.name}`);
    } else if (
      current.color.toLowerCase() !== def.color.toLowerCase() ||
      (current.description || '') !== def.description
    ) {
      await github.rest.issues.updateLabel({
        owner,
        repo,
        name: current.name,
        new_name: def.name,
        color: def.color,
        description: def.description,
      });
      core.info(`updated  ${def.name}`);
    }
  }
};
