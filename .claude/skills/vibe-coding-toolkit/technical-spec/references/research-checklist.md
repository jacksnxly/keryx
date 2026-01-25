# Codebase Research Checklist

Use this checklist for each technical component identified in the brief.

## For Each Component

### 1. Similar Functionality

Search for existing implementations:

```
# Pattern searches
grep -r "similar_keyword" src/
find . -name "*related*" -type f
```

Document:
- Where similar functionality exists
- What pattern it uses
- Why it was built that way (check git blame/history if unclear)

### 2. Data Model

Check existing schema:

```
# Common locations
src/models/
src/entities/
prisma/schema.prisma
db/migrations/
```

Document:
- Related tables/collections
- Field naming conventions
- Relationship patterns (FK, embedded, etc.)
- Soft delete vs hard delete pattern
- Timestamp conventions (created_at, updated_at)

### 3. Integration Points

For external services:

```
# Find existing wrappers
grep -r "api" src/services/
grep -r "client" src/lib/
```

Document:
- Existing service wrappers
- Authentication patterns
- Error handling approach
- Retry/timeout configuration
- Rate limiting handling

For internal services:

```
# Find event patterns
grep -r "emit" src/
grep -r "publish" src/
grep -r "subscribe" src/
```

Document:
- Event bus/queue usage
- Message formats
- Async patterns

### 4. Background Processing

```
# Find job patterns
ls src/jobs/
grep -r "queue" src/
grep -r "worker" src/
```

Document:
- Job framework (BullMQ, Celery, etc.)
- Job registration pattern
- Retry configuration
- Timeout handling
- Error reporting

### 5. API Patterns

```
# Find route patterns
ls src/routes/ src/controllers/ src/api/
```

Document:
- Route naming convention
- Request validation approach
- Response format
- Error response format
- Authentication middleware

### 6. UI Patterns

```
# Find component patterns
ls src/components/
```

Document:
- Component library (if any)
- State management approach
- Form handling pattern
- Error display pattern

## Red Flags

Stop and escalate if you find:

- [ ] Multiple conflicting patterns for same thing
- [ ] No existing pattern (greenfield decision needed)
- [ ] Deprecated patterns still in use
- [ ] Security-sensitive area with no clear owner
