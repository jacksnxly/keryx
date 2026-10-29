# Hotfix

A hotfix stops harm that is happening now; the lasting fix follows in its own run. Urgency is a second axis next to
size: an S, M or L task can be a hotfix. *(owner)*

## When

- The owner says so: "hotfix", "urgent", "prod is down", or `/keryx:hotfix`. *(owner)*
- Or keryx finds live harm while it investigates: a production health check failing, users getting errors now, an
  outage, a red main that blocks every deploy, an exposed secret. Then propose the lane in one line, with the
  evidence, and switch only on the owner's yes. *(owner)*
- Never because a task is small (that is size S) or because the request says "quick". *(owner)*

## The lane

The session's own model does the work: no plan file, no executor round. *(owner; evidence: GLM and Cursor rounds took
16–40 minutes in the field runs, and some stalled)*

1. **Intake in a minute.** Log `intake "size <S|M|L> · lane hotfix: <what is broken, for whom, since when>"`, and ask
   the autonomy question at once (push, merge, deploy): it is the critical path. The repository's rules and the
   owner's standing grants still hold. *(owner)*
2. **See the harm yourself** on the surface where it happens: the failing request, the error in the logs, the red
   check. *(evidence)*
3. **The fastest safe action first.** If a revert, a feature flag, a config change or a rollback stops the harm
   before any new code, that is the hotfix. *(borrowed)*
4. **Otherwise the smallest change**, with a regression test that fails first and passes after, and the tests of the
   area it touches. *(owner)*
5. **One fast fresh review**: `keryx.py review-brief --slug <slug> --hotfix --base <the commit before the fix>
   --head <the fix>` — a hotfix has no executor run, so both commits are named (add `--risk` for auth, money or
   privacy). The reviewer reads the diff only and reports P0 and P1; dispatch it before CI starts, so it adds no wait.
   A P0 or P1 is fixed before the change ships. *(owner)*
6. **Ship within the autonomy**, with a written rollback, and check production afterwards: the harm you saw is gone.
   *(owner)*

Left to the follow-up: the root cause, the proper design, mutation probes, the full review, refactors, docs. *(owner)*

## The follow-up

A hotfix is finished only when the lasting fix has its own run. *(owner)*

- Log `followup "<slug>-root: <what the lasting fix must do>"` with the root cause as far as you know it, then open
  that run with its intake (`keryx.py log --slug <slug>-root intake …`). It runs the normal lane for its size: plan,
  executors, probes, the full review.
- When the hotfix already is the lasting fix (a clean revert of the change that broke it), log
  `Ruling: no follow-up — <why>` instead.
- `keryx.py finish --slug <slug> --head <the shipped commit>` refuses a hotfix run until every follow-up row names a
  run opened for it (its own intake, logged after the hotfix began) or the waiver stands; the report names the same
  follow-ups. A follow-up row logged by mistake (a typo, a plan dropped) is withdrawn with
  `Ruling: drop follow-up <slug> — <why>`. Note it in the repository's memory too (`keryx.py remember --repo`), so the next
  session picks it up.
