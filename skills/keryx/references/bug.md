# Bug mode (and red CI)

## Reproduce before anything else

- Reproduce the bug yourself on the surface it was reported on (the real API, page, CLI, job), and see the exact symptom twice. Inspecting state may confirm what you saw; it must not inject the symptom. No reproduction, no fix. *(evidence)*
- When it will not reproduce, tighten the conditions, synthesize the trigger or add logging until it does. *(borrowed)*
- Save the commands and raw output under `<state>/repro/` (S: in the report). The same check runs again after the fix. *(evidence)*

## Root cause, not symptom

List the candidate causes and rule them out with runtime evidence until one survives; confirm that mechanism before writing the fix. After three failed hypotheses, question the design instead of trying a fourth. *(borrowed)*

The reproduction becomes the locked failing test. It must fail on the base for the stated reason, then pass after the fix, and the original symptom must be gone on the real surface. *(owner)* When the bug breaks a domain rule, pin the rule where it lives too (the type or function that owns that state), so the next path to it is covered as well (`domain.md`). *(borrowed)*

## Red CI

A red job is a bug whose reproduction is the failing job. *(owner)*

1. Read the failing step's log (`gh run view <id> --log-failed`), not the summary. Classify: code, test, flaky, environment, config, external service.
2. Run the failing command locally with the job's versions and environment. Fix there; push only what is verified locally. Pushes are rare and batched: CI minutes are a budget. *(owner)*
3. **Flaky** is a finding, not an excuse: rerun once to classify, then show the cause (timing, order, shared state) or mark it with the evidence and a follow-up. Never retry until green. *(evidence)*
4. Services that return errors inside an HTTP 200 body are checked at the body level before the payload is trusted. *(evidence)*
5. After a push, watch the run in the background (`gh run watch <id>`) and keep working.
