# ts-py-anchor-guard

Three checks for ports of layout and camera engines from TypeScript to Python — the three
that decide whether the port is the same *function* as the source and not merely a
renderer that looks close.

They answer, each with a receipt and an exit code:

| module | question |
|---|---|
| `anchor_oracle` | Do the numbers the TypeScript source *declares* evaluate to what the Python port computes? |
| `viewport_embed` | Is a 1:1 sub-viewport placed inside a larger canvas, or was it silently stretched to fill it? |
| `subpixel_probe` | How far is one luma profile from another below one pixel, and does the difference grow with position? |

No browser, no GPU, no E2E suite, no third-party dependency. Pure standard-library
Python, so a fresh clone runs the checks without installing anything. Cost per check,
measured 2026-11-25 on macOS with Python 3.12.13, self-test included: `viewport_embed`
107 ms, `subpixel_probe` 138 ms, `anchor_oracle` 186 ms, the fixture conformance 975 ms,
and `live_oracle` 1.49 s because it spawns node twice. So the static checks are hundreds
of milliseconds and the runtime backend costs about a second and a half — not
"milliseconds", and still far from a suite that renders frames.

```console
$ python -m ts_py_anchor_guard.anchor_oracle --fuente fixtures/engine.ts \
      --referencia fixtures/anchors.json
CONFORME · 21 ancla(s) · 40 punto(s) · peor error absoluto 0.000e+00
```

## Why these three

A port can score zero visual difference on the frames anyone happened to look at and still
be wrong in two ways that no screenshot shows:

**1. It quantises a quantity the engine keeps fractional.** Scale a 768×1344 plate by a
non-integer factor and the scaled canvas is `985.714…`. A port that stores `986` — `round`,
`floor`, `ceil`, any of them — is off by a fraction of a pixel *that grows with the
coordinate*. Trajectories still match to `0.000e+00`; the frame drifts. `anchor_oracle`
reports the divergence, and `residuo_px` / `cuantizacion` name the rounding policy that
reproduces the port's number, so the fix is known instead of guessed.

**2. It stretches a sub-viewport to fill the frame.** Compositing a 864×960 window
centred in a 1080×1920 canvas is not the same as painting the window across the whole
canvas: that is a 0.8×0.5 rescale, a 1.6× aspect distortion that a trajectory test cannot
see. `viewport_embed` computes the exact rect and refuses the rescale, naming the cause —
`ESCALA`, `RECORTE` or `DESBORDA` — because "bad geometry" is not a diagnosis.

And one that only a pixel measurement settles: a compositor that snaps layers to integer
pixels loses sub-pixel motion. `subpixel_probe` recovers the offset of one profile against
another from a single pair of rows or columns, at 1/50 px resolution, and separates
*translation* (slope ≈ 0) from *anisotropy* (slope = relative scale error).

## Install

**Not on PyPI yet.** `https://pypi.org/pypi/ts-py-anchor-guard/json` answers `404` as of
2026-11-25, so `pip install ts-py-anchor-guard` fails today. Two routes do work:

```console
$ pip install "git+https://github.com/alexisromtz-lab/ts-py-anchor-guard"
$ python -m ts_py_anchor_guard.anchor_oracle --self-test
AUTOTEST OK: 33 anclas de oraculo
```

Measured on 2026-11-25 in an empty venv on Python 3.12.13: the package lands in
`site-packages` and the self-test exits 0. The same command under Python 3.9.6 is refused
by pip, which is the intended effect of `requires-python = ">=3.11"` and not a defect.

Or vendored, with nothing installed:

```console
$ git clone https://github.com/alexisromtz-lab/ts-py-anchor-guard
$ cd ts-py-anchor-guard && python -m ts_py_anchor_guard.anchor_oracle --self-test
```

`pyproject.toml` is in place (`name = "ts-py-anchor-guard"`, version `0.4.3`), so a plain
`pip install ts-py-anchor-guard` becomes true the moment a wheel is published — and not
before. No dependencies. Each module is standalone, importable and has a `main()`.

The minor version moved from `0.1.0` to `0.2.0` once the exit codes started meaning what the
table says: `20` on a bad invocation instead of `argparse`'s `2`, and `2` for a missing input
instead of a traceback that left the process on `1`. A caller that branched on `rc == 1` to
mean "this port diverges" was getting `1` for "you typed the flag wrong", which is the one
conflation this package exists to prevent.

`0.3.0` adds no new module and changes no exit code. It adds `tools/mutate.py` and the tests
that came out of it, so the sentence "the suite would notice if the code were wrong" is a
number a reader can re-run instead of a claim in a README. The minor version moves because the
set of shipped files changed, not the contract.

`0.4.0` adds `tools/contrato_censo.py`, which runs each CLI once per exit-code cell and
compares the code with what the process actually returned — no expectation is taken from a
flag's name. It found one: `--referencia` in `live_oracle` reads the *names* to evaluate and
never compares the values, while the flag name promised a comparison. The help text now says
so, and the code is unchanged; the judging variant is `anchor_oracle --backend node`. Again the
minor version moves because a file was added, not because an exit code changed.

`0.4.1` adds four mutants over the self-test probe's predicates, two of which survived the
first run — the exclusion for the interpreter's own tree and the filter for bytecode written
through a descriptor, neither of which any run can display, because the child runs with `-B`.
One test now feeds those events straight to the predicate. The patch moves because the harness
grew and the shipped files did not.

`0.4.2` closes the only place where `live_oracle` could still raise instead of answering. A
stress run of the suite under parallel load failed three times in 72 passes with
`OSError: [Errno 28] No space left on device` — the machine's temp filesystem, at 121 MiB free,
refused the two files `medir()` writes into its scratch box. `medir()` wrapped only the `node`
call, so a full temp filesystem escaped as an exception and read as a failure of the package.
It now creates and writes the box inside the same contract as everything else: it returns
`({}, "caja temporal no escribible: ...")`. One mutant (`lo_caja_llena`) restores the `raise`
and one test kills it. The exit codes are unchanged; the patch moves because a return path was
added.

`0.4.3` is the half of that fix the harness was missing. The free-space condition is now
checked before the first copy is made: under 64 MiB free, `mutate.py` prints `NO_MEDIDO` with
the amount it found and returns `2`, instead of running 38 copies of a suite that will go red
for the disk. Two tests pin it — one for a full filesystem, one for a `disk_usage` that cannot
answer at all.

`0.4.4` makes the exit code mean one thing. `1` says "the subject diverges", and it is also
what a Python process returns when an exception escapes: a crash inside the instrument was being
read as a verdict about the subject, and part of the evidence for it was a test that compared a
traceback's `1` with an expected `1` and called the cell measured. Four escape routes were found
by asking what happens to an input that *cannot* be measured rather than to a correct one — a
profile too short for its bands, a reference with no names, a reference that is not an object,
and a source that exports none of the names it was asked about. Each now answers `2` with a
motive; the boundary that translates a crash (`_cli.correr`) is exercised by a test that
provokes one; and the census refuses a run whose stderr carries a traceback in a row expecting
`1`. The exit codes are unchanged for every input that was already contracted: the patch moves
because return paths were added.

## `anchor_oracle`: exact arithmetic parity

Reads the declaration subset where exact comparison is meaningful — numeric constants,
arithmetic over them, and single-expression arrow functions:

```ts
export const CANVAS_W = 1080;
export const SCALE = 1725 / 1344;
export const PLATE_W = 768 * SCALE;
export const OFFSET_X = Math.floor((CANVAS_W - 864) / 2);
export const ease = (u: number) => u * u * u;
export const pulse = (u: number) => 17.4 * (u ** 3 - 3 * u ** 2 + 3 * u);
```

It evaluates them without a TypeScript toolchain and compares against the values the
Python side computes. The default tolerance is `0.0`: two implementations of the same
closed form over the same inputs return the same float, so a tolerance is a decision the
caller declares (`--tolerancia`), not a number quietly baked in to make a test pass.

`Math.round` follows JavaScript (`floor(x + 0.5)`, halves towards `+Infinity`), which is
**not** Python's `round()`; a port that uses `round()` diverges at exactly `.5`, and that
is worth finding.

### What the reader reads, and what it refuses

Declared scope, because a verifier that quietly reads less than you think is worse than no
verifier:

- **Module depth only.** A `const` declared inside a function body is not an anchor. Reading
  locals as anchors promotes `m`, `x` or `k` to module constants and silently overwrites the
  real one that shares the name.
- **Values it can evaluate:** numeric constants, arithmetic over them, unary signs, `??`
  against `undefined`, object and array literals (`as const` dropped), member access
  (`BOX.w`, `PLACAS.sundial.nativo`), and single-expression arrows — including arrow bodies
  that span lines, annotate their return type (`(v: number): boolean =>`), or return an
  object literal to be read field by field.
- **Calls:** `Math.floor`, `ceil`, `round`, `abs`, `sqrt`, `sign`, `min`, `max`, `pow`, and
  the constants `Math.PI` / `Math.E`.
- **Refused, by name:** block bodies, loops, destructuring, and calls into anything not in
  the list above (`reduce`, `map`, helpers of the project). A refused anchor surfaces as
  `NO_MEDIDO · ANCLA_NO_EVALUABLE` and is listed under `no_evaluables` — never a pass, and
  never an exception. A whole object literal compared against a number is refused the same
  way: name a field (`rectView.left`) and it compares.

Precedence in the receipt: a measured divergence (`RC 1`) outranks a gap (`RC 2`), because
a number that is wrong is a fact while a number that is unreadable is a hole in the census.

`--censo` prints exactly the population the reader sees — useful to keep the acceptance set
honest when the source grows:

```
$ python -m ts_py_anchor_guard.anchor_oracle --fuente fixtures/engine.ts --censo
CANVAS_W · const · 1080
...
CENSO · 19 ancla(s) · las funciones con cuerpo de bloque y las variables locales no se leen
```

```python
from ts_py_anchor_guard import comparar

recibo = comparar(open("fixtures/engine.ts").read(), {
    "PLATE_W": 986.0,                                    # the port stores an int
    "ease": {"puntos": [0, 0.5, 1], "valores": [0, 0.125, 1]},
})
assert recibo["rc"] == 1
fila = next(f for f in recibo["anclas"] if f["ancla"] == "PLATE_W")
assert fila["cuantizacion"] == "round" and fila["residuo_px"]["round"]["residuo"] < 0
```

### Backend: measured by the engine's own runtime, or by this module

By default the module evaluates the declarations it reads with its own arithmetic — a
second implementation of the same formulas, and two implementations can agree because they
share a misreading of the source. `--backend node` removes the middleman: node strips type
annotations natively since 22.6, so the `.ts` file is imported and its exported constants
and pure functions are called directly. No bundler, no `package.json`, no network, no
browser.

#### The runtime threshold, measured rather than cited

The versions below each imported a two-line TypeScript module exporting one constant and one
pure function from an `.mjs` probe, using the binaries published on npm as
`npx -y node@<version>`:

| node | without flag | with `--experimental-strip-types` | stderr without flag |
|---|---|---|---|
| 22.6.0 | `ERR_UNKNOWN_FILE_EXTENSION` | value | — |
| 23.5.0 | `ERR_UNKNOWN_FILE_EXTENSION` | value | — |
| 23.6.0 | value | value | 2 lines (`ExperimentalWarning`) |
| 24.15.0 | value | value | 0 lines |

Below 22.6 there is no path at all, which is why `version_de_nodo()` returns `None` there and
`--backend node` answers `NO_MEDIDO · SIN_ORACULO_VIVO` instead of measuring something else.
The warning on 23.6 goes to stderr and the exit code stays 0; `medir()` reads stderr only when
the exit code is non-zero, so a warning never degrades a measurement.

```
$ python -m ts_py_anchor_guard.anchor_oracle --fuente fixtures/engine.ts \
    --referencia fixtures/anchors.json
CONFORME · 21 ancla(s) · 40 punto(s) · peor error absoluto 0.000e+00 · oraculo node v24.15.0
```

The receipt always names the backend that produced the reference values, because a number
measured by an interpreter and a number measured by a model of that interpreter are not the
same evidence. `--backend estatico` forces the model; `--backend node` fails with
`NO_MEDIDO · SIN_ORACULO_VIVO` when no suitable node is present; `auto`, the default, uses
node when it can. There is no silent fallback — a mode that was asked for and could not run
is a gap, not a demotion to the other one.

The two modes do not cover the same population, and both say so. On a 627-line production
camera module:

| backend | what it measured | verdict |
|---|---|---|
| `estatico` | 9 anchors · 10 points | `NO_MEDIDO`, naming the one anchor it refuses (a `reduce`) |
| `node` | 10 anchors · 12 points | `0.000e+00`, the refused anchor included |

The static reader stays the one that decides *what exists* — a typo or a dotted path that
resolves to nothing is caught there — and node decides *what it is worth*. Reading and
measuring are separate claims, so they get separate instruments.

## `viewport_embed`: the 1:1 invariant

```python
from ts_py_anchor_guard import rect_de, verificar_1a1

rect_de((1080, 1920), (864, 960))                  # (108, 480, 864, 960)
verificar_1a1((1080, 1920), (864, 960))["rc"]      # 0
verificar_1a1((1080, 1920), (864, 960),
              rect=(0, 0, 1080, 1920))["causa"]    # 'ESCALA', a 0.8x0.5 stretch
```

Centring floors the margin, so the rect is always inside the canvas: rounding *up* leaves
the window half a pixel outside its own frame. An oversized window raises
`VentanaNoCabe` instead of being clipped or shrunk — clipping changes the visible extent,
shrinking changes the scale the destination engine uses.

## `subpixel_probe`: phase and anisotropy from one pair of profiles

```python
from ts_py_anchor_guard.subpixel_probe import perfil_sintetico, fase_subpixel, anisotropia

a = perfil_sintetico(256, fase=0.0)
b = perfil_sintetico(256, fase=0.25)      # a quarter of a pixel to the right
fase_subpixel(a, b)["desplazamiento"]     # 0.24987121564142314  -> +0.2499 px
anisotropia(a, b)["error_de_escala"]      # 4.348604381017845e-06 -> +0.0004 % per band
```

The same pair written to disk gives the same two numbers from the CLI:

```console
$ python -m ts_py_anchor_guard.subpixel_probe --a a.txt --b b.txt
+0.2499 px (50/px de resolucion) · error de escala +0.0004 % por banda
```

The `+0.0004 %` is real and is printed instead of being folded into a tolerance: three
sines sampled over a finite window are not exactly band-limited, so a pure translation
recovers as a scale error of about 4·10⁻⁶ per band rather than as zero.

The integer minimum of the sum of squared differences is refined by the vertex of the
parabola through its three neighbouring costs. A flat or inverted parabola means the
minimum is not a minimum, and the answer is `NO_MEDIDO` with the reason — `BORDE` when the
minimum falls on the edge of the search, `SIN_MINIMO` when the parabola does not open. The
estimator never returns a number it cannot support.

Splitting the profiles into bands and fitting the local shift against the band centre
separates a translation (slope ≈ 0) from a relative scale error: if `b[i] = a[i·(1+k)]`
the fit gives `error_de_escala = k`.

`perfil_sintetico()` generates deterministic band-limited profiles for testing the probe
itself: three incommensurable sines, sampled analytically at a fractional offset, so a miss
is the estimator's and not an interpolation's. Frequencies above Nyquist are rejected —
aliasing makes a sub-pixel offset and an integer one cost the same, which would let a
broken estimator look right for the wrong reason.

## What each claim rests on

A verification tool that lets its own numbers pass unexamined is asking for the trust it
does not extend. Every quantitative claim above is listed here with the population it was
measured on, and whether a reader can reproduce it from a fresh clone.

| claim | measured against | reproducible from a fresh clone |
|---|---|---|
| `CONFORME · 21 ancla(s) · 40 punto(s) · 0.000e+00` | `fixtures/engine.ts`, synthetic and self-contained | yes, command above |
| `pip install "git+https://…"` → `AUTOTEST OK` | empty venv, Python 3.12.13, package resolved into `site-packages` | yes |
| `10 anchors / 12 points · 0.000e+00` on a 627-line module | a real camera engine, executed by node, read-only, **outside this repository** | **no** — that source is not redistributed. The receipt is the evidence; the run is not |
| object literals and `??` read, block bodies refused | `fixtures/engine.ts`, which reproduces those shapes | yes |
| `+0.2499 px at 1/50 px` | `perfil_sintetico(256, fase=0.25)`, analytic sampling | yes |
| `+0.0004 % per band` | the same pair; the residual of a 3-sine finite window | yes |
| node `22.6` / `23.5` / `23.6` / `24.15` table | real binaries published on npm, `npx -y node@<version>` | yes, four downloads |
| per-check cost (`107`–`1490` ms) | wall clock around each `--self-test`, Python 3.12.13, macOS | yes, the clock differs, the order does not |
| `rc == 0` for a 1:1 embed | exact integer algebra, nothing measured | yes, no process spawned |
| `20` for a bad invocation, in all four CLIs | subprocess exit codes for an unknown flag and for a mistyped `--bandas`, Python 3.12.13 | yes, `python -m unittest tests.test_contrato_cli` |
| `2` for a missing input, `1` + `DESBORDA` for an oversized window | the same run; the receipt keys of the diverging case are compared with the conforming one | yes, same module, no network |
| `--self-test` opens no data file and no socket, in three of four | `sys.addaudithook` around each module's `--self-test`, one process per module; events under `sys.prefix` and module loading (`.py`, `.pyc`) excluded, so what is counted is data I/O | yes, the probe ships as `tools/audit_self_test.py` and prints the events it saw |
| `no third-party dependency`; a `main()` in each module; `--json` in three of four | AST import scan against `sys.stdlib_module_names`, plus each module's `--help` | yes, one loop over `ts_py_anchor_guard/*.py` |
| `40` of `44` mutants killed; the other `4` cannot be reached by any input | 44 curated single-line mutations across eight sites (four modules, the CLI, three harness probes), each in a fresh copy, every kill repeated on a second fresh copy | yes — `python3 tools/mutate.py`, which ships the 44 mutations and names the four exemptions with their reason |
| `15` of `18` contract rows measured; the other `3` declared with their motive | every CLI run once per row, its exit code compared with the process's, a row expecting `1` refusing a run whose stderr carries a traceback, and no expectation taken from a flag's name | yes — `python3 tools/contrato_censo.py` |

Two boundaries are declared rather than measured, and no claim here crosses them:

- **No browser and no compositor are observed.** `subpixel_probe` measures profiles you give
  it. Whether a real compositor snaps layers to integer pixels, and at what phase, is a
  property of that compositor, measured elsewhere; this package can feed the measurement but
  cannot stand in for it.
- **`0.000e+00` is agreement between two executables, not proof of a correct engine.** If
  the TypeScript source is wrong, both the source and the port are wrong together, and the
  verifier is silent by construction. It answers "same function", never "right function".

### What the tests would notice: 44 mutations, 40 killed

A suite can read its fixtures and still assert nothing. The question is not "does this test
open the fixture" but "if the code were wrong, would anything go red" — so 44 one-line
mutations are applied across eight sites (the four modules, the CLI, and the three harness
probes), each in a fresh copy, each followed by the whole suite.

- **17 of 25 died** on the suite as it stood before the first pass of this section. Five of the
  eight survivors were live coverage gaps, and each now has a test that fails on the mutant and
  passes on the code: the left edge of the search window (`-max_shift` was never exercised,
  only `+max_shift`), the reason a band count is refused (the short bands raised further down,
  for a different reason, so the guard could be deleted and the test still passed), an aspect
  stretch on the vertical axis only (`escala[0] == 1.0` was checked, `escala[1]` was not),
  `round` implemented as `floor(x + 0.4)` (indistinguishable from `floor(x + 0.5)` unless the
  fraction lands in `(0.4, 0.5)`, which the fixture did not contain), and the relative error
  reported as the absolute one.
- **22 of 25 died** once those five tests existed. The set then grew to 33 when the exit-code
  census and the self-test probe were brought under the same instrument.
- **Four mutants were then added over the probe's own predicates, and two survived.** The
  probe's last fix came from a false red and nothing was watching the function that fixed it.
  Reverting `repr(args)` to the 160-character excerpt, and making the `.pyc` branch blind to
  case, both died at once — killed by the test that pins the long path. Removing the
  interpreter-tree exclusion and removing the descriptor filter survived, because neither is
  reachable from the report: the child runs with `-B`, so no `.pyc` is written through a
  descriptor, and nothing under `sys.prefix` is opened. A rule no run can display is a rule no
  test holds, so `test_lo_que_abre_el_interprete_no_es_io_de_datos` now feeds the four events
  straight to the predicate, with a `.ts` write as the positive control.
- **34 of 38 died** while the escape routes of `0.4.4` were still open, and the four
  survivors were the declared ones in the table below.
- **40 of 44 die now.** Four mutants were added over the routes that let a crash look like a
  verdict, and all four die: one that removes the boundary's translation (`cli_choque_escapa`),
  one that turns the translated crash back into `1` (`cli_choque_es_uno`), one that lets an
  empty reference conform again (`ao_ref_vacia_ok`), one that lets the reader print nulls with `0`
  (`lo_nulos_conforman`) — plus the short profile (`sp_perfil_escapa`) and the census's own
  blind spot (`ce_choque_conforma`). The four survivors are the declared ones below, and the
  script reports `huecos de cobertura: ninguno` — zero undeclared holes — with exit code `0`.
- **The harness does not mutate itself, and that is declared, not hidden.** `tools/mutate.py`
  deletes `tests/test_mutate.py` from every copy it runs, because that file asserts the shape of
  the mutation table and would "kill" any edit to it — the exact dead end this section exists to
  catch. The cost is that the instrument's own guards, including the free-space refusal added in
  `0.4.2`, are pinned by tests the instrument cannot measure. A mutant on `tools/mutate.py`
  would report `VIVO` for want of a judge, which is why none is listed.
- **The last mutant came from the environment, not from a review.** A stress run of the suite
  under six parallel loops failed three times in 72 passes with `Errno 28: No space left on
  device`, raised while `medir()` wrote its two scratch files. Wrapping only the `node` call
  meant a full temp filesystem escaped as an exception: the package's own rule, that a state it
  cannot measure is *returned*, failed exactly where the machine was out of resources. The box
  is now created and written under the same contract, and `lo_caja_llena` — which restores the
  `raise` — dies at `test_una_caja_temporal_llena_es_un_motivo_y_no_una_excepcion`.

The `17` is re-measured, not remembered: the same script, run against the tests at that
earlier commit, reports 17 dead, 8 alive, and names the five coverage gaps itself —

```
huecos de cobertura: sp_borde_izq, sp_bandas_guarda, ve_escala_eje1, ao_round_04, ao_rel_no_relativo
```

— which is where the list above came from.

**A kill is read from the whole set of failing tests, and `[ajeno]` still means what it
says.** Getting that label right was a fix to the verdict rule, not to the suite. The
first version judged a kill by its *first* failing test, so four mutants whose own
module's test also died were printed as `[ajeno]`: a label that reads as "nobody who owns
this notices". The verdict now looks at the whole set of failing tests, and the report
names the test that owns the mutant. The cost of the old rule is measurable: deleting
`tests/test_contrato_censo.py` from a copy and re-running the two CLI mutants leaves both
of them dead, killed by `tests.test_contrato_cli`. So the census adds no mutation
coverage; what it buys is the eighteen-row contract, which is a different claim, and the
mutation rate was never evidence for it.

Three kills in the run above are labelled `[ajeno]`, and this paragraph used to claim the
opposite — that no kill depended on another site's tests. The run that closed the four escape
routes falsified it: `sp_perfil_escapa`, `ao_ref_vacia_ok` and `lo_nulos_conforman` remove
guards that only fire at the process boundary, where `tests/test_contrato_cli.py` owns the exit
codes of all four modules. It is the right owner for that behaviour and the wrong word to print,
so the number is stated here instead of being left for a reader to notice.

Four rules make the report trustworthy. All four were learned by getting them wrong.

- **A kill has to reproduce.** Every nonzero run is repeated on a fresh copy of the mutant. A
  mutation that fails once and passes on the second run is reported as `FLAKY`, never as
  killed, and the script exits `2`, so a flaky run cannot be read as a rate.
- **The repeat must not compare where the copy lived.** Two runs that fail the *same* test
  differ in one respect: the temporary path each one runs in. Comparing the raw report made a
  reproducible kill look non-deterministic for a whole session (`au_filtro_py`, a payload that
  quotes the path of the file it opened). Where the copy lives is an input of the run, not an
  observation, so the location is normalised out before the two runs are compared — and the
  comparison uses the *set* of failing tests, because `A and B` versus `A alone` is not a
  repeat either.
- **A test that asserts the shape of the source cannot judge a mutation of the source.** The
  first version of the harness shipped its own invariant test (`this pattern appears exactly
  once`) inside the repository it mutates. With that test in the copy, all 25 mutants died for
  one reason — the invariant detected the edit — and the report read `25/25 killed`. That is
  the failure this package exists to catch, reproduced in its own suite: a green that measures
  the instrument instead of the subject. Two changes came out of it: the harness test is
  excluded from mutant copies by name, and any kill traced to it now aborts with `2` instead of
  counting.
- **A repetition has to start from the initial state.** A suite run is not a read-only act:
  one CLI test launches an interpreter without `-B` and leaves a `__pycache__/_cli.pyc` behind,
  so the repeat read the compiled module and the mutant became invisible. Each run now copies
  the whole tree instead of cleaning selectively.

**Four mutants cannot be killed by any test, and that is the finding, not an omission.** Three
are guards the arithmetic makes unreachable, and one is a branch whose input nothing produces.
No input distinguishes them from the original, so no test can:

| mutant | why no input reaches it |
|---|---|
| drop the `+-0.5` clamp on the parabola vertex | with `c0` the minimum cost, `c0 <= c_menos` and `c0 <= c_mas`, hence `abs(c_menos - c_mas) <= c_menos - 2*c0 + c_mas`: the vertex is always inside `+-0.5`. The clamp documents the bound; `test_el_desplazamiento_cabe_siempre_en_media_muestra` pins the invariant instead of the guard |
| `curvatura <= 0` → `curvatura < 0` | `curvatura == 0` needs `c_menos + c_mas == 2*c0` with `c0` a minimum, i.e. a three-way tie, which exact integer sums can produce only by making the parabola flat everywhere — not with `_ssd` over distinct shifts |
| allow bands with fewer than 2 samples of overlap | the `2*max_shift + 8 > min(len)` check already refuses those inputs, so the later guard is shadowed by the earlier one from every public entry point |
| read bytecode by descriptor only on `'xb'` | measured: the interpreter opens `__pycache__` files with mode `'wb'`, so the `'xb'` arm of the filter has no producer. The observable half — that the probe does not leave bytecode behind — is pinned by `test_la_sonda_no_deja_bytecode_en_el_arbol`, which does kill the mutant that removes `-B` |

Keeping a guard that cannot fire is a choice: it states the invariant where a reader looks for
it. What is not acceptable is claiming the suite covers it. It does not, and no test can.

## Contract

| exit code | meaning |
|---|---|
| `0` | conforming / measured and within tolerance |
| `1` | diverging — the receipt names the anchor, point or cause |
| `2` | not measured — never reported as conforming |
| `20` | bad invocation |

All four modules have `--self-test`, and each one runs against its own synthetic fixtures.
Three of them — `anchor_oracle`, `subpixel_probe`, `viewport_embed` — open no file and no
socket while doing it; that is measured with `sys.addaudithook`, not asserted, because the
first draft of this paragraph claimed it for all four and `live_oracle` contradicted it:
its self-test writes `fuente.ts` and `probe.mjs` into a temporary directory and runs `node`,
which is the whole point of the module. Twenty-four filesystem events outside `sys.prefix`,
against zero in the other three.

The probe is not a snippet in this file, it is [`tools/audit_self_test.py`](tools/audit_self_test.py):

```bash
$ python tools/audit_self_test.py
anchor_oracle     0 events · AUTOTEST OK: 33 anclas de oraculo
live_oracle      23 events · AUTOTEST OK: 7 anclas de oraculo vivo · v24.15.0
subpixel_probe    0 events · AUTOTEST OK: 9 anclas de subpixel
viewport_embed    0 events · AUTOTEST OK: 14 anclas de encastre
$ echo $?          # 1: a module touched data I/O, which is what the table says
```

Read the number for `live_oracle` as *nonzero*, not as a constant: it counts the writes and
pipes of each `node` run the fixture performs, so it moves if the fixture does — the same
tree reports 23 or 24 depending on whether a bytecode cache already existed. `0` versus
*nonzero* is the invariant; the exact number is a property of the fixture, and
`tests/test_audit_self_test.py` pins the former rather than the latter.

Measuring the self-test is itself a case of the problem this package exists to catch, twice
over.

The first version reported 1 event for `anchor_oracle` on a fresh clone and 0 afterwards,
because the first import writes a `.pyc` through a bare file descriptor and the event carries
no path for a filter to match. The probe now runs each module with `-B`, and skips descriptor
writes as a second net, so the answer no longer depends on whether the clone was warm.

The second version filtered on the *excerpt* it prints — `repr(args)[:160]` — instead of on
the event's own arguments. Both agree until a path is long: macOS caches the system Python's
bytecode in `~/Library/Caches/com.apple.python/<path>-39.pyc`, and a copy under `$TMPDIR` puts
the `.pyc` past the cut, so loading code stopped matching the code filter and was reported as
data I/O. Three modules went red on Python 3.9 with zero data opened. The filter now takes the
tuple (`_es_dato`), the cutoff is applied only to what gets printed, and
`test_una_ruta_de_codigo_larga_sigue_siendo_carga_de_codigo` pins it. A filter that reads a
display string is measuring the report, not the event.

Three of them also take `--json` for the full receipt; `live_oracle` takes no such flag
because its receipt is JSON unconditionally — a flag that would not change the output is
one more thing to keep true.

A bad invocation exits `20`, not the `2` that `argparse` uses by default, and an input file
that does not exist exits `2` with a `NO_MEDIDO · INSUMO_FALTA` line instead of a traceback
that would leave the process at `1`, the code that means *the port is wrong*. Both were
wrong until this commit; `tests/test_contrato_cli.py` measures the process, not
`main()`, because the process is what a runner reads.

### Which of the sixteen cells each CLI actually emits

A table of four codes is a claim about four processes, and a claim about a process is not
read, it is measured. `tools/contrato_censo.py` runs every CLI once per cell and compares
the exit code, so the cells that are *empty* are measurements too — each one carries the
code it does return and the reason, and the census goes red the day one of them starts
firing instead of this table going stale.

| module | `0` | `1` | `2` | `20` |
|---|---|---|---|---|
| `anchor_oracle` | measured | measured | measured | measured |
| `live_oracle` | measured | **empty — a reader, not a judge** | measured | measured |
| `subpixel_probe` | measured | **empty — a reader, not a judge** | measured | measured |
| `viewport_embed` | measured | measured | **empty — it reads no file** | measured |

The three empty cells, with the code they do return:

- **`live_oracle` + `1` → `0`.** Its CLI is a reader: `--referencia` supplies the *names* to
  evaluate with `node`, never the values to compare against, and `main` prints the measured
  numbers and exits `0`. Fed a reference whose `CANVAS_W` is off by 9, it still exits `0`.
  The judging lives one layer up, in `anchor_oracle --backend node`, which takes those same
  numbers through `comparar` and does exit `1`.
- **`subpixel_probe` + `1` → `2`.** Two unrelated profiles produce a phase, not a
  divergence: with no reference to be wrong about, the honest answer is `NO_MEDIDO`.
- **`viewport_embed` + `2` → `20`.** It opens no file, so a missing input is arity, not
  `INSUMO_FALTA`.

Two cells carry a second row, because one cell is reached by two unrelated inputs:
`anchor_oracle` + `2` is `INSUMO_FALTA` for a file that is missing and `REFERENCIA_VACIA` for a
file that names nothing, and `subpixel_probe` + `2` is the same missing file and a profile too
short for its bands. A row also has to answer the *code*, not the status: `1` is both "the
subject diverges" and what an escaping exception returns, so a row expecting `1` used to accept a
traceback as its evidence. The census now reads `stderr` too, and a second negative control
proves that refusal can go red.

Two things this instrument got wrong before it got the table right, both worth stating
because they are the failure it exists to catch:

- **The first census read the flag's name and concluded it compared.** `--referencia` reads
  like "compare against this", so the row was written as `expects 1` and the module
  disagreed. A flag that carries a name is not a reader of what the name promises; the fix
  was to declare the empty cell inside the tool, with its motive, instead of inferring it
  from a word.
- **The first negative control ran the subject.** It took a real cell, replaced the
  expectation with `99`, and checked that the census complained. A control that breaks in
  the same way the subject breaks cannot tell you the subject is right; it now spawns a
  throwaway process that exits `7` against an expectation of `99`.

Without `node`, the `live_oracle` cells become a fourth class rather than a false green:
the expectation is `2`, because that is what the reader returns when it cannot measure.


## Tests

```console
$ python -m unittest discover -s tests -t .
```

`fixtures/engine.ts` and `fixtures/anchors.json` are synthetic and self-contained: no
project, asset or path from any real repository appears in this package.

## License

MIT.
