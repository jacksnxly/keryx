# Execution Protocols

Strict protocols for handling ambiguity and scope during implementation.

## Ambiguity Protocol

When the spec is unclear or you encounter a decision not covered by the spec:

### Step 1: STOP immediately

Do not write code. Do not guess.

### Step 2: Quote the unclear part

```
AMBIGUITY FOUND

Spec says: "[exact quote from spec]"

This is unclear because: [explanation of what's ambiguous]
```

### Step 3: Present interpretations

```
Possible interpretations:

A: [First interpretation]
   - Would implement as: [brief description]

B: [Second interpretation]
   - Would implement as: [brief description]

C: [Third interpretation, if applicable]
   - Would implement as: [brief description]
```

### Step 4: Ask explicitly

```
Which interpretation is correct?
```

### Step 5: Wait

Do NOT proceed until human answers. Do not pick the "most likely" option.

### Example

```
AMBIGUITY FOUND

Spec says: "Retry failed jobs with exponential backoff"

This is unclear because: No base delay or maximum delay specified.

Possible interpretations:

A: Use existing pattern from email-sender.ts (1s base, no max)
   - Would implement as: { type: 'exponential', delay: 1000 }

B: Use aggressive retry (100ms base, 30s max)
   - Would implement as: { type: 'exponential', delay: 100, maxDelay: 30000 }

C: Use conservative retry (5s base, 5min max)
   - Would implement as: { type: 'exponential', delay: 5000, maxDelay: 300000 }

Which interpretation is correct?
```

---

## Scope Boundary Protocol

When you notice an opportunity to add something not in the spec:

### Step 1: Recognize the temptation

Common triggers:
- "While I'm here, I could also..."
- "It would be better if we also..."
- "Users might expect..."
- "This would be more robust if..."
- "Best practice suggests..."

### Step 2: Log it, don't do it

```
SCOPE NOTE

While implementing [current task], noticed opportunity to add [feature/improvement].
This is NOT in the spec. Not implementing.
Logging for future consideration.
```

### Step 3: Continue without adding it

Proceed with only what's in the spec.

### Example

```
SCOPE NOTE

While implementing the scoring job, noticed we could add Slack notifications
when scoring fails. This would help ops team respond faster.

This is NOT in the spec. Not implementing.
Logging for future consideration.
```

---

## Pattern Deviation Protocol

When you find the spec requires something that conflicts with existing patterns:

### Step 1: STOP

Do not deviate from patterns without approval.

### Step 2: Report the conflict

```
PATTERN CONFLICT

Spec requires: [what the spec says]

Existing pattern: [what the codebase does]
Location: [file:line]

These conflict because: [explanation]
```

### Step 3: Present options

```
Options:

A: Follow spec (deviate from existing pattern)
   - Risk: Inconsistency in codebase

B: Follow existing pattern (deviate from spec)
   - Risk: Spec needs amendment

C: Other approach
   - [Description]

Which approach?
```

### Step 4: Wait for decision

---

## Spec Change Protocol

When implementation reveals the spec is wrong or incomplete:

### Step 1: STOP implementation

Do not work around it.

### Step 2: Report the issue

```
SPEC ISSUE FOUND

While implementing [component], discovered:
[Description of the problem]

This cannot be resolved within current spec because:
[Explanation]

Recommendation: [What needs to change in spec]
```

### Step 3: Wait for spec amendment

Do not continue until spec is updated or explicit guidance given.
