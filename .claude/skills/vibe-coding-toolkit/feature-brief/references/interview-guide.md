# Interview Guide

Probing questions for each interview section. Use these to push past surface-level answers.

## Problem Discovery

### Persona
- "Who specifically experiences this problem?" (reject "users" or "customers")
- "What is their role? What do they do day-to-day?"
- "How technical are they?"

### Trigger
- "What moment causes them to need this?"
- "What are they trying to accomplish when this happens?"
- "How often does this occur?"

### Current State
- "What do they do today to solve this?"
- "Walk me through the exact steps they take"
- "What tools do they use?"

### Pain
- "What's wrong with the current approach?"
- "How much time does it take?"
- "What errors or failures occur?"
- "What's the cost of getting it wrong?"

## Solution Walkthrough

For each step in the user journey:
- "What does the user see?"
- "What action do they take?"
- "What feedback do they receive?"
- "How do they know it worked?"

Push for specifics:
- "What fields are on this form?"
- "What options are in this dropdown?"
- "What does the success message say?"

## Edge Case Extraction

For EACH step in the journey, ask:

| Scenario | Question |
|----------|----------|
| Missing input | "What if they leave [field] blank?" |
| Invalid input | "What if they enter [invalid value]?" |
| External failure | "What if [service] is down?" |
| Duplicate action | "What if they submit this twice?" |
| Concurrent users | "What if two people do this simultaneously?" |
| Cancellation | "What if they cancel midway?" |
| Timeout | "What if this takes too long?" |
| Permissions | "What if they don't have access?" |

## Scope Boundaries

- "What might someone expect this feature to do that it won't?"
- "What's a natural extension we're explicitly not building?"
- "What related problem are we leaving unsolved?"
- "Are there user types we're not supporting?"

Require minimum 3 out-of-scope items. Push harder if stakeholder struggles:
- "If this feature is successful, what would v2 add?"
- "What did you consider but decide against?"

## Priority Context

- "Why build this now instead of later?"
- "What's blocked without this feature?"
- "What's the cost of delaying by one month?"
- "How does this compare to other priorities?"

## Challenge Patterns

When stakeholder says... | Respond with...
------------------------|----------------
"Users" | "Which users specifically? What's their role?"
"Handle it gracefully" | "What does graceful mean here? What do they see?"
"It should just work" | "Walk me through what 'working' looks like step by step"
"Standard error handling" | "What error message should they see? What action can they take?"
"Similar to [other product]" | "Describe the specific behavior you want, not a reference"
"Obviously" or "Simply" | "Spell it out for me—what exactly happens?"
