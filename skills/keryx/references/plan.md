# Plan (M and L)

A plan is the set of decisions an implementer who has never seen this codebase cannot make alone. It holds no implementation code except the locked tests. One slice fits on one or two screens plus its tests. *(owner; evidence: plans of 3k–22k lines that contained the code got it written twice)*

Save it as `<git-common-dir>/cursor-loop/<slug>/PLAN.md` (never committed). The executor cannot read that folder: paste the plan into its brief.

```markdown
# <slug>: <one-line goal>

## Acceptance check
<command or procedure> — on the base: <failing output, one or two lines>.

## Ground truth
- Fact: … (source)
- Assumption: … — disproved by: … — tested: yes/no, result

## Decisions
- Files and what changes in each; new names and signatures.
- Domain (where `domain.md` applies): context and terms; the layer of each new name; each invariant, where it is enforced and its locked test; the consistency boundary; who writes each table touched; how other contexts and outside systems are reached.
- Invariants that must keep holding.
- Out of bounds: files, behaviours and side effects not to touch.

## Locked tests
<exact test code, with exact values — the acceptance criteria>

## Done when
- `<command>` → <what passing output looks like>   (run on the base: <result>)

## Slices (L only)
- <slice>: owns <files> in <context>; depends on <slice or none>

## Review focus
- The inputs most likely to break this that no test covers yet.
```

## Before dispatch

- **Lock the tests.** For each locked block write `<state>/locked/NN.json` = `{"path": "<repo-relative file>", "block": "<exact code>"}`; `cursor.py locked` later proves each block is still there verbatim. *(evidence)*
- **Preflight.** Run every done-command once on the base. A command that is already broken, or stricter than the repository's own gate, is fixed now, not discovered by an executor. *(evidence: two loops lost a round to a done-command that could never pass)*
- **Take the done-commands from CI.** Read the repository's CI workflows and copy, for the jobs the change touches, the same commands, flags and environment (including jobs that run a subset of tests without the shared setup, and lists of known failures that turn an unexpected pass into a failure). Name the jobs you could not run here. *(evidence: one PR went through four CI rounds on tests and jobs its done-commands never ran)*
- **Real paths.** Locked tests may fake what the change does not reach; for each outside dependency the change calls, at least one locked test or QA step goes through the real thing (`check.md`). *(evidence)*
- **Check for design choices.** A locked assertion that encodes one of several reasonable designs is a decision: keep it and note it in the report, or loosen it. *(evidence)*
- **Slices** never share a file. Two slices that must touch one file are one slice. *(fact)* One aggregate never spans two slices. *(owner)*
- **Boundaries.** The repository's dependency rules are among the done-when commands (`domain.md`). *(evidence)*
