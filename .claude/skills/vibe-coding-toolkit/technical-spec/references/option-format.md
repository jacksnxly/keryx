# Option Presentation Format

Use this format for every major technical decision.

## Template

```markdown
## Decision: [What needs to be decided]

### Option A: [Name]

**Description:** [1-2 sentences on how it works]

**Pros:**
- [Benefit 1]
- [Benefit 2]

**Cons:**
- [Drawback 1]
- [Drawback 2]

**Existing usage:** [Where this pattern exists in codebase, or "None"]

### Option B: [Name]

**Description:** [1-2 sentences]

**Pros:**
- [Benefit 1]
- [Benefit 2]

**Cons:**
- [Drawback 1]
- [Drawback 2]

**Existing usage:** [Where in codebase, or "None"]

### Option C: [Name] (if applicable)

[Same format...]

---

**Key tradeoff:** [One sentence comparing the fundamental difference]

**Your choice?**
```

## Rules

1. **Always present at least 2 options** - Even if one seems obviously better
2. **Include "existing usage"** - This is critical for pattern consistency
3. **No recommendations** - Present neutrally, let human decide
4. **Concrete pros/cons** - Not abstract ("more flexible" → "supports X and Y use cases")
5. **One decision at a time** - Wait for answer before presenting next

## Example

```markdown
## Decision: Job Queue for Background Scoring

### Option A: BullMQ (Redis-based)

**Description:** Use existing BullMQ setup for job processing with Redis as broker.

**Pros:**
- Already configured and running
- Team has experience
- Built-in retry, backoff, and dashboard

**Cons:**
- Redis is single point of failure
- Limited to ~10k jobs/sec

**Existing usage:**
- `src/jobs/email-sender.ts`
- `src/jobs/report-generator.ts`
- `src/jobs/sync-contacts.ts`

### Option B: Synchronous Processing

**Description:** Process scoring inline during API request.

**Pros:**
- No infrastructure dependency
- Simpler error handling
- Immediate feedback to user

**Cons:**
- Blocks request for 2-5 seconds
- No automatic retry on failure
- User waits for external API

**Existing usage:** None for slow operations

### Option C: AWS SQS + Lambda

**Description:** Use managed AWS queue with Lambda for processing.

**Pros:**
- Auto-scaling
- Managed infrastructure
- Pay per use

**Cons:**
- New infrastructure to set up
- Different deployment model
- Team unfamiliar

**Existing usage:** None

---

**Key tradeoff:** BullMQ is proven in this codebase vs. SQS offers better scaling but requires new infrastructure.

**Your choice?**
```

## After Decision

Once human chooses, document:

```markdown
**Decision:** Option A - BullMQ

**Reasoning:** Already in use, team familiar, scaling not a concern for expected volume (~100 jobs/day)
```

Then generate constraint:

```
CONSTRAINT: Use BullMQ for job processing. Job class must be in /src/jobs/ following existing pattern in email-sender.ts.
```
