---
name: hotfix
description: Use only when the owner asks for a hotfix or an urgent fix, or says production is broken right now — keryx's hotfix lane: the session fixes it fast and safely itself, then opens a follow-up run for the lasting fix. Never for work that is merely small or "quick" (that is keryx size S).
---

# keryx hotfix

The hotfix lane of keryx. Read `../keryx/SKILL.md` for the loop and the run log, then follow
`../keryx/references/hotfix.md` step by step. The session's own model fixes it, with no plan file and no executor, and
`keryx.py finish` closes the run only once the follow-up run for the lasting fix exists.
