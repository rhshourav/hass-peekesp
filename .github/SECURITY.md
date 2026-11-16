# Security

## Reporting a problem

Please **do not open a public issue** for anything that could expose someone's data.
Report it privately through
[GitHub security advisories](https://github.com/rhshourav/hass-peekesp/security/advisories/new).

Include what you found, how to reproduce it, and the PeekESP and Home Assistant versions. You will
get an answer as soon as the maintainer can read it; this is a small, volunteer-run project.

## Pairing codes and tokens are credentials

The pairing code on the device derives the relay stream ID and the read token. Anyone who has either
can read that machine's live stats (CPU, RAM, storage, temperatures, host name, uptime) from the
relay.

- Never post a code, token or stream URL in an issue, comment, screenshot or log.
- If one was posted, treat it as exposed and change it on the device if your setup allows it.
- Issue and comment text is scanned by a bot that removes what it recognises, but the original stays
  in the edit history until a maintainer deletes the revision.

## Supported versions

Only the latest release receives fixes.
