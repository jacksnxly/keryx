# Technical Spec Template

```markdown
---
status: APPROVED FOR IMPLEMENTATION
author: [Tech Lead Name]
created: [YYYY-MM-DD]
feature: [Feature Name]
brief: .agent/briefs/BRIEF-[name]-[date].md
---

# Technical Spec: [Feature Name]

## Summary

[One paragraph describing the technical approach at a high level]

## Decisions

### 1. [Decision Area]

**Choice:** [What was chosen]

**Alternatives considered:**
- [Option B] - rejected because [reason]
- [Option C] - rejected because [reason]

**Reasoning:** [Why this choice was made]

### 2. [Decision Area]

**Choice:** [What was chosen]

**Alternatives considered:**
- [Alternative] - rejected because [reason]

**Reasoning:** [Why]

[Continue for all major decisions...]

## Data Model

### New Tables/Collections

```sql
-- Example for SQL
CREATE TABLE feature_table (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- fields...
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Schema Changes

```
-- Existing table modifications
ALTER TABLE existing_table ADD COLUMN new_field TYPE;
```

### Indexes

```sql
CREATE INDEX idx_name ON table(column);
```

## API Contract

### Endpoints

#### POST /api/v1/resource

**Request:**
```json
{
  "field": "value"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "field": "value"
}
```

**Errors:**
- 400: Validation error
- 401: Unauthorized
- 404: Resource not found

[Continue for all endpoints...]

## Integration Points

### External Services

| Service | Purpose | Auth | Wrapper Location |
|---------|---------|------|------------------|
| [Name] | [Why] | [Type] | [File path] |

### Internal Services

| Service | Purpose | Communication |
|---------|---------|---------------|
| [Name] | [Why] | [REST/Event/etc] |

### Events Published

| Event | Payload | When |
|-------|---------|------|
| [Name] | [Shape] | [Trigger] |

### Events Consumed

| Event | Handler | Action |
|-------|---------|--------|
| [Name] | [File] | [What happens] |

## Security Considerations

### Authentication

[How requests are authenticated]

### Authorization

[What permissions are required, how they're checked]

### Data Sensitivity

[Any PII, encryption requirements, audit logging]

### Input Validation

[Validation approach, sanitization]

## Implementation Constraints

These are specific, verifiable requirements derived from the decisions above.

1. [Constraint - specific and testable]
2. [Constraint]
3. [Constraint]
4. [Constraint]
5. [Constraint]

[Minimum 5, maximum 15]

## Testing Requirements

### Unit Tests

- [ ] [Component] - [What to test]
- [ ] [Component] - [What to test]

### Integration Tests

- [ ] [Flow] - [What to verify]
- [ ] [Flow] - [What to verify]

### Manual QA

- [ ] [Scenario to manually verify]
- [ ] [Scenario]

## Rollout

### Feature Flag

- Flag name: `feature_[name]`
- Default: off
- Rollout plan: [Percentage ramp or criteria]

### Migration

[Any data migration needed, rollback plan]

### Monitoring

- [ ] [Metric to track]
- [ ] [Alert to set up]

### Rollback Plan

[How to revert if issues found]

---

**Approved by:** [Tech Lead]
**Date:** [YYYY-MM-DD]
```

## Quality Checklist

Before finalizing:

- [ ] All decisions have documented reasoning
- [ ] Codebase was actually searched (not generic recommendations)
- [ ] Existing patterns referenced with file paths
- [ ] Constraints are specific and verifiable
- [ ] Data model matches existing conventions or deviation justified
- [ ] Security explicitly addressed
- [ ] API contract includes error responses
- [ ] Testing requirements cover happy path and edge cases
- [ ] Rollback plan exists
