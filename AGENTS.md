# AGENTS.md — ts-py-anchor-guard

Standalone public package. It has no relation to any private repository, and must not
grow one: no path, asset name or project detail from a consumer of these checks may
appear here. The fixtures are synthetic on purpose.

## Contract

- **Exit codes are the API**: `0` conforming · `1` diverging (cause named) · `2` not
  measured (never 0) · `20` bad invocation. A check that cannot measure says so.
- **No dependencies.** Standard library only, Python ≥ 3.11. A clone must be testable with
  `python -m unittest discover -s tests -t .` without installing anything.
- **Tolerance is declared, never baked in.** The default is `0.0`; relaxing it is the
  caller's explicit decision.
- **A receipt names a locus**: the anchor and point, the cause, the rounding residual. A
  verdict without a locus is not a result.
- **`--self-test` in every module**, and it must fail if the module's claim fails. An
  assertion that cannot fail is documentation, not a test.
- **The reader's scope is published, not implied.** `--censo` prints exactly the anchors the
  reader sees, and a reference naming anything else is `NO_MEDIDO`. A docstring sentence
  about what the reader refuses is a claim about code: it needs a test that runs the reader
  against the shape it describes. A reader that silently reads 3 of 31 declarations, and a
  reader that raises a traceback instead of reporting a gap, are the same defect — the
  verdict is wrong and it is not visibly wrong.

## Style

Docstrings state the invariant and why the naive version is wrong. Comments only where the
code cannot carry the reason. British-neutral technical English in docs, identifiers in
Spanish where the domain word is Spanish (`ancla`, `ventana`, `lona`, `escala`).

## What not to add

- A GPU, browser or E2E dependency.
- Network access in any test.
- A tolerance constant without naming the measurement that justifies it.
