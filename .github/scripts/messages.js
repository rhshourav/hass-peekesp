'use strict';
/** Text the bot posts. Kept in one place so the tone stays consistent. */

const list = (items) => items.join(', ');

function secretsNotice(kinds, what) {
  return [
    `I removed what looks like a **${list(kinds)}** from ${what}.`,
    '',
    "A pairing code or read token lets anyone read that machine's live stats from the relay, " +
      'so it should not be posted publicly.',
    '',
    'The original text is still in the edit history, so treat it as exposed: change the pairing ' +
      'code if your setup lets you, and ask a maintainer to delete the revision history if you ' +
      'want it gone. If I removed something that was not a secret, just edit it back in.',
  ].join('\n');
}

function needsEvidence(author) {
  return [
    `Thanks for the report, @${author}. To look into this I need **debug logs or a screenshot** ` +
      "(logs for sensor, setup and connection problems, a screenshot or recording for the card).",
    '',
    'Debug logging for the integration:',
    '',
    '```yaml',
    '# configuration.yaml, then restart Home Assistant and reproduce the problem',
    'logger:',
    '  default: warning',
    '  logs:',
    '    custom_components.peekesp: debug',
    '```',
    '',
    'Then paste what shows up in **Settings → System → Logs** (remember to remove any pairing ' +
      'code or token). If the log really is empty, say so.',
    '',
    'Edit the report above or reply here. I have marked it `needs-info`; it is closed ' +
      'automatically after about two weeks without a reply, and you can reopen it any time.',
  ].join('\n');
}

function needsInfoRequest(author, note) {
  const lines = [`@${author}, a maintainer needs a bit more information before this can move on.`];
  if (note) lines.push('', ...note.split('\n').map((l) => `> ${l}`));
  lines.push(
    '',
    'Reply here when you can. It is closed automatically after about two weeks without a ' +
      'reply, and you can reopen it any time.',
  );
  return lines.join('\n');
}

function commandHelp() {
  return [
    '**Commands** (a line that starts with `/`, outside code blocks and quotes)',
    '',
    '| Command | Who | What it does |',
    '|---|---|---|',
    '| `/assign` | anyone | assign yourself (not if another contributor already has it) |',
    '| `/unassign` | anyone | remove yourself |',
    '| `/assign @user` · `/unassign @user` | maintainers | assign or unassign someone else |',
    '| `/label a, b` · `/unlabel a, b` | maintainers | add or remove labels (comma separated) |',
    '| `/needs-info [message]` | maintainers | ask the reporter for details |',
    '| `/confirm` | maintainers | mark as confirmed |',
    '| `/duplicate #123` | maintainers | close as a duplicate |',
    '| `/wontfix [reason]` | maintainers | close as not planned |',
    '| `/close` · `/reopen` | maintainers (`/reopen` also the author) | close or reopen |',
    '| `/help` | anyone | this list |',
  ].join('\n');
}

function commandProblems(actor, problems) {
  return [`@${actor}, I could not do everything you asked:`, '', ...problems.map((p) => `- ${p}`)].join(
    '\n',
  );
}

module.exports = { secretsNotice, needsEvidence, needsInfoRequest, commandHelp, commandProblems };
