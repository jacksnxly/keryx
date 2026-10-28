# Domain first

Apply domain-driven design wherever the change touches a business rule, state that changes under rules, data one part of the system owns, or an integration with another part or an outside system. Elsewhere (plain CRUD, glue, configuration, styling, scripts) follow the code that is there and add no patterns. *(owner)*

The repository's own model comes first: its ADRs, `CLAUDE.md` / `AGENTS.md`, context maps, module layout and dependency rules outrank this file. Where they say nothing, use what follows. *(owner)*

Before you create a context, a layer or a family of modules, read the ADRs and decisions that govern that area and follow them: "apply DDD" never means adding a context the repository has ruled out. *(evidence: a design put new code into a context an ADR had stopped, and the executor then loosened the guard tests so it would pass)*

Spend the care on the core, the part that makes the product worth paying for. Generic parts (accounts, email, payment plumbing) follow the library or the code already there. *(borrowed: Evans, core domain and generic subdomains)*

## Intake: the domain facts

Part of the ground truth, one line each, with the file or doc you read it from:

- **Context**: the bounded context the change lives in, and the folder, crate or service that is its home. A change that spans two contexts names both and the contract between them.
- **Terms**: the words the code, docs and owner use for what the change touches. New names use those words; a new term, or one word used with two meanings, is a decision. *(borrowed: ubiquitous language)*
- **Invariants**: the rules that must hold after every operation (a booking never ends before it starts; one payment event grants the entitlement once, however often it is processed).
- **Owner of the data**: which context writes each table or store the change writes. One writer per table: a second writer is the owner's decision, never a side effect of a task. *(owner)*
- **Direction**: what may import what. Domain code imports no framework, transport, ORM or provider code; adapters depend on the domain, never the reverse. *(owner)*

## Plan: the Domain block (M and L)

Under Decisions in `PLAN.md`:

- Context, terms, and the layer of each new name: domain (rules and state), application (one use case, one transaction), adapter (HTTP, database, provider, UI).
- Each invariant, where it is enforced and the locked test that proves it. Enforce it where the state lives (the type or aggregate that owns it), with a database constraint where the data allows; a rule checked only in the UI or in one caller is not enforced. *(borrowed: Evans, assertions)*
- The consistency boundary: what must change together in one transaction (one aggregate) and what may catch up later (another aggregate or context, by an event, a job or a re-read). Keep it as small as the invariant allows, and refer to other aggregates by id. *(borrowed: Vernon, effective aggregate design)* A wider transaction needs a stated reason (no async mechanism, a screen that edits many at once, a query that cannot do without) and a ruling.
- Integration: another context's data comes through its API, its published events or a read model it owns, never by writing its tables. An outside system's payload is translated at the edge into our own types, including its error quirks, and nothing past the edge sees its shapes. *(borrowed: Evans, anticorruption layer; evidence: an analysis of one product's backend-for-frontend found 56+ direct exchange calls in its routes)*
- L slices follow contexts: a slice owns one context's change, and one aggregate never spans two slices. *(owner)*

## Check

- The repository's dependency rules (dependency-cruiser, import-linter, ArchUnit, workspace or lint boundaries) are among the done-when commands. *(evidence: a dependency rule caught a wrong import in a locked test)*
- A boundary the plan adds gets a rule in the repository's tool, and a probe shows the rule fails on a forbidden import. Without such a tool, a test that fails on the forbidden import; adding a new tool is its own task. *(borrowed)*
- Invariants get mutation probes like any behaviour (`check.md`): break the rule in a scratch copy, and its locked test must fail.

## Review

The fresh reviewer also gets the repository's architecture rules and reports breaks of them (`review.md`). A finding cites the rule (ADR or `CLAUDE.md` line) and the concrete consequence: a second writer, an invariant reachable through another path, an outside payload past the edge, domain code importing an adapter. A textbook preference with no rule and no consequence is a minor: log only. *(owner)*

## Not in scope

- No ceremony: no repository, factory, event bus or command/query split the change does not need. A messy area gets a boundary drawn around it, not a model inside it. *(borrowed: Evans, big ball of mud)*
- Existing structure that falls short of this file is not fixed inside the task: log it and propose it as its own task. *(evidence)*

Sources: E. Evans, *Domain-Driven Design Reference* (2015, CC BY 4.0); V. Vernon, *Effective Aggregate Design*, parts I–II (2011); M. Fowler, *BoundedContext* (2014); Microsoft, *Use domain analysis to model microservices*.
