# Evals

`claude plugin eval . --tag hotfix-trigger --ablation none` checks that the hotfix lane fires only when it
should: three prompts that describe harm happening now must invoke `keryx:hotfix`; four that are small, quick or
ordinary must not. Each run is capped at three turns and may only read, so it tests the choice, not the fix.
