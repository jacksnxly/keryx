# Security

## Reporting a vulnerability

Please report security problems privately through GitHub: **Security → Report a vulnerability** on this repository. Do not open a public issue for them.

Include what you found, how to reproduce it, and what it lets someone do. You will get an answer within a week.

## What counts

keryx runs coding agents on your machine. Reports are especially welcome when keryx:

- lets an executor read credentials it should not see (the GLM runner strips secret variables and denies `.env` files and key folders; the Cursor and subagent runners rely on their own permission settings);
- lets an executor push, deploy or reach production without the owner's go;
- writes a secret into a run log, a report or keryx memory;
- runs untrusted text from a repository, a review or an executor's report as an instruction.

## Supported versions

Only the latest release gets fixes.
