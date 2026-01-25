# Brief Template

Use this structure for the output document.

```markdown
---
status: PENDING TECHNICAL REVIEW
author: [Stakeholder Name]
created: [YYYY-MM-DD]
feature: [Feature Name]
---

# Feature Brief: [Feature Name]

## Problem

**Persona:** [Specific role, not "users"]

**Trigger:** [The moment that causes the need]

**Current State:** [What they do today, step by step]

**Pain:** [Quantifiable cost—time, errors, money]

## Solution

[Step-by-step user journey from trigger to completion]

### Step 1: [Action]
- User sees: [What's displayed]
- User does: [What action they take]
- Result: [What happens]

### Step 2: [Action]
[Continue for all steps...]

## Examples

### Happy Path
**Scenario:** [Specific situation with named inputs]
**Steps:** [What happens]
**Expected Result:** [Specific output]

### Edge Case
**Scenario:** [Unusual but valid situation]
**Steps:** [What happens]
**Expected Result:** [How system handles it]

### Error Case
**Scenario:** [Something goes wrong]
**Steps:** [What happens]
**Expected Result:** [Error handling behavior]

## Scope

### In Scope
- [Feature/behavior we ARE building]
- [Feature/behavior we ARE building]

### Out of Scope
- [Feature/behavior we are NOT building]
- [Feature/behavior we are NOT building]
- [Feature/behavior we are NOT building]
(Minimum 3 items required)

## Open Questions

- [Anything unresolved that needs clarification]

## Priority

**Urgency:** [Why now]
**Blocked:** [What's waiting on this]
**Cost of Delay:** [Impact of not building this]
```

## Quality Checklist

Before finalizing, verify:

- [ ] Persona is specific (role, not "users")
- [ ] Trigger describes a concrete moment
- [ ] Current state includes actual steps, not "they struggle"
- [ ] Pain is quantifiable (time, money, error rate)
- [ ] Solution describes UX, not implementation
- [ ] Happy path has specific inputs and outputs
- [ ] Edge case covers a realistic scenario
- [ ] Error case specifies what user sees
- [ ] At least 3 out-of-scope items listed
- [ ] No technical decisions (database, API, stack)
- [ ] No assumptions filled in without stakeholder confirmation
