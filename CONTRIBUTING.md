# Contributing

Thanks for wanting to improve keryx.

## Before you change the workflow

Every rule in `skills/keryx/` carries where it comes from: *fact*, *owner* (a maintainer's decision), *evidence* (seen in real runs) or *borrowed* (a tactic not yet proven here). A change to a rule should say which kind it is and, for *evidence*, what was seen. Changes that make the workflow longer need a reason; the skill is read by a model on every run, so every line costs tokens.

## Tests

```bash
(cd skills/keryx && python3 -m unittest discover -s tests)
(cd field && python3 -m pytest -q)
(cd bench && python3 -m pip install -r requirements.txt && python3 -m pytest -q)
```

No test calls a model or the network. New behaviour in `scripts/keryx.py` comes with a test that fails without it.

## Pull requests

- One change per pull request, with the tests above passing.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).
- No credentials, private paths or names of private projects in code, tests, fixtures or docs; build token-shaped test values at run time.

By contributing you agree that your contribution is licensed under the MIT license in `LICENSE`.
