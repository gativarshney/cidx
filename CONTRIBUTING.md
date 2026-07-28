# Contributing to cidx

Thanks for your interest. cidx is a solo-maintained project with a strict
scope, so please read this page before opening a pull request. The full
engineering contract lives in [AGENTS.md](AGENTS.md); this page is the
practical summary.

## Ground rules

- **Scope is law.** v1 indexes exactly two languages (Python, TypeScript/JavaScript)
  and exposes exactly five read-only MCP tools. The
  [do-not-build list](AGENTS.md#do-not-build-list) (embeddings, more languages,
  write tools, HTTP transport, editor plugins, and more) is decided, with
  reasons in [DECISIONS.md](DECISIONS.md). PRs that expand scope will be
  declined with a pointer to that list.
- **Dependencies are capped.** Runtime: `tree-sitter`, grammar wheels,
  `watchdog`, `mcp`. Dev: `pytest`, `hypothesis`, `ruff`. Anything else needs a
  DECISIONS.md entry approved by the maintainer *before* the PR.
- **Every behavior change ships with tests in the same PR.** No exceptions.
- **The convergence invariant is sacred:** the incremental index must always
  equal a cold rebuild. A red convergence suite blocks every merge.

## Workflow

1. Open or comment on an issue first for anything non-trivial, so the approach
   is agreed before you write code.
2. Branch from `main`: `feat/…`, `fix/…`, `test/…`, `docs/…`, `bench/…`, or
   `chore/…`. Never commit to `main` directly.
3. Use [conventional commits](https://www.conventionalcommits.org/):
   `feat:`, `fix:`, `test:`, `docs:`, `bench:`, `chore:`.
4. Keep PRs small and single-concern; every diff gets a full human review.
5. User-visible changes update `CHANGELOG.md` in the same PR.

## Development setup

Requires Python 3.11+ (3.12 recommended).

```bash
git clone https://github.com/gativarshney/cidx
cd cidx
python -m venv .venv
# Windows: .venv\Scripts\activate    POSIX: source .venv/bin/activate
pip install -e .[dev]
```

## Before you push

Run the same checks CI runs — all three must pass on your machine:

```bash
ruff check .
ruff format --check .
pytest -q
```

CI repeats these on {Ubuntu, macOS, Windows} x {Python 3.11, 3.12, 3.13}.
Windows is first-class: never use POSIX-only paths or APIs without a fallback,
and use `pathlib` for all filesystem work.

## Code style

- Complete type hints; `ruff` clean (lint and format).
- No clever metaprogramming, no premature abstraction, no speculative
  generality. Prefer boring stdlib solutions.
- Public functions get docstrings that state the contract, not narration.
- Error messages tell the user what to do next.

## Licensing

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE). There is no CLA.
