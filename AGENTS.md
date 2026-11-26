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
- **Reading and measuring are different claims.** The reader decides what exists; the value
  comes from the engine's own runtime when one is available (`live_oracle`, node ≥ 22.6,
  type stripping, no bundler). A receipt names the backend, because comparing a port against
  a second implementation of the same formula is weaker evidence than comparing it against
  the interpreter that runs it. A requested backend that cannot run is `NO_MEDIDO`; falling
  back quietly would make the mode undeclared, which is worse than the gap.
- **An answer is a function of its inputs, and the tree is an input.** A check that changes
  its verdict because an earlier run left `__pycache__` behind is measuring the run. Pin the
  property where it can be seen (a cold copy) or pin the predicate on the events it actually
  receives — never on a count that a warm tree hides. The same rule governs a repeat: the
  second run has to start from the first run's initial state, not from what it left behind, and
  it must not be compared against the first run's location. Two copies that fail the same test
  differ in their temporary path; reading that as non-determinism turns a reproducible kill
  into a `FLAKY`, which is the same class of error as counting a flake as a kill.
- **A cell that is empty is a measurement, not an omission.** A published contract that lists
  four codes over four modules is a grid of sixteen claims, and the ones a module cannot emit
  are the ones a reader will assume it can. Declare the empty cell with the code it *does*
  return and the reason, and let a script go red when it starts firing. Never infer a cell
  from a flag's name: `--referencia` says compare, and one of these modules only reads its
  keys. And a negative control that breaks the way the subject breaks proves nothing.
- **A filter reads the event, never the excerpt.** A predicate applied to `repr(args)[:160]`
  agrees with the argument until a path is long enough to lose its suffix to the cut, and then
  it classifies the wrong thing without failing: on macOS, system Python caches bytecode under
  `~/Library/Caches/com.apple.python/<path>-39.pyc`, so three modules "opened data" with zero
  data opened. Truncate for printing, never for judging.
- **A rule the report cannot display needs a test on the event.** Two exclusions in the probe —
  the interpreter's own tree, and bytecode written through a descriptor — never fire in a
  clean run, because the child runs with `-B`. Nothing was watching them, and two mutants that
  removed them survived: a guard the suite cannot exercise is a guard the suite does not have.
  Feed the predicate the events a real run would produce, with a data write as the control.
- **A resource the machine cannot give is a motive, not an exception.** `medir()` wrapped only
  the `node` call, so a temp filesystem out of space escaped as `OSError` and read as a failure
  of the package — three times in 72 stress passes. Every state the package cannot measure
  leaves through `({}, motivo)`; a `try` that covers the external process but not the scratch
  writes around it covers the wrong half.

## Style

Docstrings state the invariant and why the naive version is wrong. Comments only where the
code cannot carry the reason. British-neutral technical English in docs, identifiers in
Spanish where the domain word is Spanish (`ancla`, `ventana`, `lona`, `escala`).

## What not to add

- A GPU, browser or E2E dependency.
- Network access in any test.
- A tolerance constant without naming the measurement that justifies it.
