## What and why

<!-- One or two sentences. Link the issue: "Fixes #123". -->

## How it was checked

<!-- Delete what does not apply. -->
- [ ] `python tests/test_core.py`
- [ ] `node tests/test_card.js` (needs `npm i jsdom`)
- [ ] Tried in a real Home Assistant: <!-- version -->
- [ ] Looked at the card in a browser: <!-- browser -->

## Checklist

- [ ] If behaviour changed: `version` in `manifest.json` **and** `const VERSION` in `peekesp-card.js` are bumped together (a test checks they match). Merging a new version publishes a release.
- [ ] README updated if options, entities or the card changed
- [ ] No pairing codes, tokens or relay stream IDs in the diff, logs or screenshots
