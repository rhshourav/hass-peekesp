# Repository automation

What runs, what it does, and what to switch on once.

## What runs

| Workflow | When | What it does |
|---|---|---|
| **Issue triage** | issue opened / edited / reopened | Removes pasted pairing codes, tokens and stream IDs. Labels by the form's *Area*. Bug reports with no logs and no screenshot get `needs-info` and a comment that says exactly what to add. Assigns the maintainers. |
| **Issue comments** | comment created / edited | Same secret scrub for comments. A reply from the reporter clears `needs-info`. Runs the slash commands below. |
| **Pull requests** | PR opened / updated | Labels by changed files (`.github/labeler.yml`). Assigns the author if they are a maintainer, otherwise the maintainers. `CODEOWNERS` requests the review. |
| **Stale** | daily | `needs-info` issues: warn after 7 days, close after 7 more. Everything else: warn at 90 days, close 14 later (PRs: 30 + 14). `pinned`, `security`, `confirmed`, `help wanted` and `good first issue` are exempt. |
| **CodeQL** | push, PR, weekly | Security analysis of the Python integration and the JS card → *Security → Code scanning*. |
| **Lint** | push, PR | `ruff` (incl. bandit rules) on `custom_components`, JS syntax check, unit tests for these scripts, a consistency check between forms, labels and config, and `actionlint`. |
| **Release** | `manifest.json` changes on the default branch | Runs the tests, then tags `vX.Y.Z` and publishes a release with generated notes and a `peekesp.zip`. Skips versions that already have a release. A version with a hyphen (`0.2.0-beta.1`) is a pre-release. |
| **Sync labels** | `labels.json` changes | Creates and updates the labels. Never deletes one. |
| **Dependabot** | weekly | One grouped PR for GitHub Actions updates (all actions are pinned to commit SHAs). |

The existing **Tests** and **Validate** (HACS + hassfest) workflows are unchanged.

## Slash commands

Write one on its own line in an issue or PR comment. Lines inside code blocks or quotes are ignored.
`/help` lists them in the thread.

| Command | Who |
|---|---|
| `/assign` · `/unassign` | anyone (for themselves; `/assign` is refused if another contributor already has it) |
| `/assign @user` · `/unassign @user` | maintainers |
| `/label a, b` · `/unlabel a, b` | maintainers (labels must already exist) |
| `/needs-info [message]` · `/confirm` | maintainers |
| `/duplicate #123` · `/wontfix [reason]` · `/close` | maintainers |
| `/reopen` | maintainers and the issue's author |

"Maintainer" means anyone listed in `automation.json` or with write access to the repository.
A reaction on your comment shows the result: 👍 done, 😕 something was refused (the bot explains why).

## Switch on once

1. **Merge this.** *Sync labels* runs on that push and creates every label. Issue forms only apply
   labels that exist, so do this before announcing the templates.
2. **Settings → Advanced Security** (public repos get all of this free):
   - Code scanning: if *Default setup* is on, turn it off. It conflicts with `codeql.yml`.
   - Turn on Dependabot alerts, Secret scanning and **Push protection**.
3. **Publish 0.1.1:** *Actions → Release → Run workflow*. The workflow otherwise only fires when
   `manifest.json` changes, so the version you already have will not release itself.
4. Optional: in a branch protection rule, require `Lint`, `Tests`, `hassfest` and `Analyze`.

## Change how it behaves

| To change | Edit |
|---|---|
| Who gets assigned, which dropdown option maps to which label, what counts as "evidence" | `.github/automation.json` |
| Labels, colours, descriptions | `.github/labels.json` (also add them to `automation.json` / forms if used) |
| Which files get which PR label | `.github/labeler.yml` |
| Stale timings and messages | `.github/workflows/stale.yml` |
| What the bot says | `.github/scripts/messages.js` |
| Release note sections | `.github/release.yml` |
| Default branch other than `main` / `master` | the `branches:` lists in `codeql.yml`, `lint.yml`, `labels.yml`, `release.yml` |

If you rename an *Area* option in an issue form, change it in `automation.json` too.
`python .github/scripts/test/check_config.py` (also run by *Lint*) fails when they drift apart.

## Releasing

1. Bump `version` in `custom_components/peekesp/manifest.json` **and** `const VERSION` in
   `frontend/peekesp-card.js` (`tests/test_core.py` fails if they differ).
2. Merge to the default branch. The release appears a minute later and HACS offers it as an update.

## Safety notes

- Issue and comment text is never run, never put in a shell command, and never checked out as code.
  The scripts only parse it as data.
- `pull_request_target` is used only for labelling and assignment and checks out the base branch,
  never the PR's code. Keep it that way if you extend it.
- Every workflow declares the minimum `permissions`; actions are pinned to commit SHAs.
- Secret redaction is a safety net, not a guarantee: the original text stays in GitHub's edit
  history until a maintainer deletes the revision, so a leaked code should still be treated as exposed.

## Run the checks locally

```
node --test ".github/scripts/test/*.test.js"
pip install pyyaml && python .github/scripts/test/check_config.py
ruff check custom_components
```
