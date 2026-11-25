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
Python, so the checks run in CI in milliseconds and in a fresh clone without installing
anything.

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

`pyproject.toml` is in place (`name = "ts-py-anchor-guard"`, version `0.1.0`), so a plain
`pip install ts-py-anchor-guard` becomes true the moment a wheel is published — and not
before. No dependencies. Each module is standalone, importable and has a `main()`.

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
| `rc == 0` for a 1:1 embed | exact integer algebra, nothing measured | yes, no process spawned |

Two boundaries are declared rather than measured, and no claim here crosses them:

- **No browser and no compositor are observed.** `subpixel_probe` measures profiles you give
  it. Whether a real compositor snaps layers to integer pixels, and at what phase, is a
  property of that compositor, measured elsewhere; this package can feed the measurement but
  cannot stand in for it.
- **`0.000e+00` is agreement between two executables, not proof of a correct engine.** If
  the TypeScript source is wrong, both the source and the port are wrong together, and the
  verifier is silent by construction. It answers "same function", never "right function".

## Contract

| exit code | meaning |
|---|---|
| `0` | conforming / measured and within tolerance |
| `1` | diverging — the receipt names the anchor, point or cause |
| `2` | not measured — never reported as conforming |
| `20` | bad invocation |

Every module also has `--json` (the full receipt) and `--self-test` (its own anchors, run
against synthetic fixtures, no filesystem or network).

## Tests

```console
$ python -m unittest discover -s tests -t .
```

`fixtures/engine.ts` and `fixtures/anchors.json` are synthetic and self-contained: no
project, asset or path from any real repository appears in this package.

## License

MIT.
