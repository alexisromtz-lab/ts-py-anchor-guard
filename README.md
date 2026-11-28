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
AUTOTEST OK: 44 anclas de oraculo
```

Measured on 2026-11-25 in an empty venv on Python 3.12.13: the package lands in
`site-packages` and the self-test exits 0. The same command under Python 3.9.6 is refused
by pip, which is the intended effect of `requires-python = ">=3.11"` and not a defect.

Or vendored, with nothing installed:

```console
$ git clone https://github.com/alexisromtz-lab/ts-py-anchor-guard
$ cd ts-py-anchor-guard && python -m ts_py_anchor_guard.anchor_oracle --self-test
```

`pyproject.toml` is in place (`name = "ts-py-anchor-guard"`, version `0.9.4`), so a plain
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

`0.4.5` is the harness growing where the table was thin, and it found one defect in the code
it was measuring. Six mutants were added over the three sites with the worst ratio of lines to
mutants (`anchor_oracle` 92.7, `live_oracle` 74.7, `contrato_censo` 62.3); five die. The one
that did not is now the fifth declared exemption, and its reason is a measurement rather than
an argument: the node probe answered `typeof v`, so an exported `true` arrived as the string
`"boolean"` and the `isinstance(v, bool)` branch it protects had no producer. That exemption
held for two releases and `0.9.0` falsified it — the probe returns the value, a `true` reaches
Python as a boolean, and the mutant now dies. The defect came
from `lo_motivo_sin_causa`: `medir()` reported `node rc 1: Node.js v24.15.0` — the last line of
`stderr`, which is Node's version banner — while the cause, a `SyntaxError`, sat three lines
above it. A motive that names the runner sends the reader to the wrong file. It now prefers the
last line containing `Error` and falls back to the last one. Two tests written for these mutants
passed for the wrong reason before they were fixed: one fed `None` as the reference, so the
probe never read the export, and one asserted only the exit code while a second negative control
fired on the same sabotage.

`0.5.0` adds a file rather than a return path: `action.yml`, a composite action that runs this
package inside a workflow without installing it, exits with the module's own code and publishes
`rc` and `receipt` as outputs. The minor moves because the set of files changed, which is the
rule this project has followed since `0.2.0`. The action reuses the same `main()` entry points the
CLI already exposed, so no contract changed; what it removes is the gap between "the tool works"
and "a caller can adopt it in five lines". Four of its seven invocation paths are measured in the
table above and one of them, the `uses: ./` job, only becomes evidence when CI runs it.

`0.5.1` is that sentence paying its debt. The action advertised a dependency-free path, and no
run of it had ever happened without the dependency present: `auto` prefers the live oracle, and
every hosted runner ships `node`, so `backend: estatico` — the spelling the reader accepts, which
the input table had been printing as `static` — was covered only by local unit tests. `ci.yml`
now strips every directory that publishes a `node` from the `PATH` in a step that fails when it
strips nothing, runs the action three times under it, and asserts the receipts: `0` with
`"backend": "estatico"` and `"peor_rel": 0.0`, `1` with `DIVERGE` from a step that is red, and
`2` for `backend: node`, which is the witness that the filter reached inside the composite. The
census grew a `backend` axis in the same pass, and its two new rows change class with the
environment rather than deducing one. Two documentation defects fell out: `static` for
`estatico`, which the CLI answers with `20`, and the claim that a failed step publishes no
outputs.

The mutator moved for the same reason, on a smaller surface: `au_sin_B` was counted as a hole
under the system 3.9.6 and killed under 3.12.13, and the difference is not the code but the
interpreter — 3.9.6 writes no `.pyc` for a cold import, so removing `-B` changes nothing
observable there. The exemption is now declared by that measurement instead of being asserted
by a rate, which means the report says `44` and `45` on the interpreter that produces each.
The patch moves because a return path was measured, two strings were corrected and a rate
gained its subject; no exit code changed.

`0.6.0` adds `consumers/v0/`, the harness that pins the published tag from a repository that is
not this one. Every run up to here executed `uses: ./`, which measures the action but not what a
stranger gets: a tag, a tarball, an extraction, and a composite whose `PYTHONPATH` points at a
directory the caller never sees. Run `45852973521` walked that path in a throwaway repository on
a stock `ubuntu-latest` and returned three receipts — `0` with `"backend": "estatico"` and
`"peor_rel": 0.0`, `1` with `DIVERGE` from a step that went red while the `receipt-file` it wrote
stayed readable, and `0` from `auto`, which chose `node v24.22.3` — so the five lines this file
promises are measured rather than asserted. The same run named a defect the matrix had: the
runner's `python3` is `3.14.4`, while the matrix certified `3.11` through `3.13`, so a caller
could adopt a version this project had never exercised; `3.14` is in the matrix now. The minor
moves because the set of files changed; no exit code did.

`0.7.0` is the first run against an engine that already shipped instead of against a fixture: a
`627`-line TypeScript file and its `831`-line Python port, no adapters and no edits on either
side, nine numbers compared at `peor_rel 0.0` — so the two implementations of the same law are
bit-identical and nothing had ever said so. It also cost three things that are now in the code:
a vector in the reference used to raise out of `float()` and take the whole receipt with it; a
green over a subset of the declared anchors carried no field saying which ones it skipped; and
a renamed anchor (`NUDOS_S5` in TypeScript, `RAMPA_S5` in the port) is absent from every receipt
rather than counted as a hole. The minor moves because the receipt gained `cobertura` and one
failure became a named row; no exit code changed.

`0.8.0` moves the correspondence out of the caller's head and into the repository: a
`ts-py-anchor.json` that declares which anchor of the source is which address of the reference,
versioned with the code and reviewed like it. Against the same engine the manifest compares `12`
anchors at `peor_rel 0.0` instead of refusing two containers, counts the `14` keys nobody
measures instead of absorbing them, and turns the `16` declared-but-unmeasured roots into a named
gap the moment a pair signs `exigir_cobertura_total`. Three things it cost: a mapping used to
consume nothing, so `CUADRO` stayed `ANCLA_NO_EVALUABLE` with its members already at `0.0`; the
aggregate receipt read `cobertura` unguarded and crashed on a pair that refused before producing
one; and the pair's tolerance and backend had to be decided — the file wins, because a file can
be reviewed and a command line cannot. The minor moves because the schema is new; no exit code
did.

`21ae392` cut the tag's CI red and the reason was worth keeping: the assertion on a refused
invocation found `steps.<id>.outputs.rc` empty. The module's own `20` was published; the action's
own refusal was not, so the same code reached the caller as a number on one path and as an
absent slot on the other. All boundary refusals now publish `rc=20` with an empty `receipt`, and
`ci.yml` asserts both.

`0.9.0` is the reader learning that **text is a value**. A declaration like
`export const EVENTO = "paneo:fin"` was unreadable, and so was every object keyed by text, so on
a real file the census read **13 of 72** declarations (18,1 %). It now reads **72 of 72** and
evaluates **56** (77,8 %) — `posthog/posthog@bda26b33` `frontend/src/lib/constants.tsx`
(77 551 B, 67), `marimo-team/marimo@906e4c2f` `frontend/src/core/constants.ts` (3),
`langfuse/langfuse@a2cd4753` `packages/shared/src/constants.ts` (2), each count matching
`grep -c '^export const'`. The 59 refusals were classified by hand: 31 strings, 17 comments, 4
template literals, 2 `enum` member access — the language's, not this reader's — 1 numeric
separator, 1 spread, and 3 with no single cause. What it cost, none of it the language's
fault:

- **The opening quote was never masked.** `_cerrar_cadena` returned the index of the character
  after the opening quote, so every string's *body* was read as code: `"cero}"` closed a brace
  level and `"https://…"` opened a comment on its `//`.
- **A regex literal swallowed the file.** `/[\w'()]/gi` opened a string on its `'`, and the
  rest of `constants.tsx` — 27 of its 67 declarations — disappeared into it. Regexes are now
  skipped as a token, with `<` deliberately excluded from the "a regex may start here" set so
  that a JSX closing tag is not mistaken for one.
- **A false green at the runtime boundary.** The probe answered `typeof v` for anything that
  was not a number, so an exported `true` crossed as the *text* `"boolean"` and a name that does
  not exist crossed as `"undefined"` — an absent anchor compared as a string, which is a
  measurement of nothing. The probe returns the value; `medir()` keeps a string and drops a
  boolean, so a boolean is a hole with a motive.

The tolerance does not apply to text: two strings have no distance between them, so a text row
carries `tipo_valor: "texto"` and no `peor_rel`, and `--tolerancia` cannot turn a different
branch name into a conforming one. `--censo` gained the denominator — `declaradas` next to
`leidas` and `evaluables`, with the two silences named apart (`NO_LEIDA` is the reader,
`NO_EVALUABLE` is the subset) — because a coverage figure computed from what the reader reached
is the instrument measuring itself. The self-test grew from 33 anchors to 44. The minor moves
because the receipt gained a value type; no exit code changed.

`0.9.1` is that denominator getting its third part. Two held-out files — `calcom/cal.com@ae027bb7`
118 declarations, `immich-app/immich@a51a4385` 16 — read **134 of 134** and evaluate 38 and 12.
Reading generalises and evaluating does not, and the census was blaming the parser for it: on
calcom, 60 of the 80 refusals read `process.env`. Those are now their own population,
`con_entorno`, carrying the variables each anchor reads, so 118 publishes as 38 evaluable + 60
environment-bound + 20 structural. An anchor that reads the environment is still refused — with
its own motive — because a variable that is not set is not a value; what changes is that the
number stops calling a deployment fact a reader gap. Text that merely *names* a variable
(`"process.env.X"` in a message or a comment) is not a dependency: the decision is taken on the
mask, which is what makes `["X"]` count as environment while the string does not.

The next step was pre-registered and refuted without writing the code: teaching the reader `!`,
`||`, `&&` and `true`/`false` was predicted to take calcom from 38 to 70-90 evaluable. The same
declarations that use `||` also read `process.env.WEBAPP_URL`, so the operator surface is not the
binding constraint. A prediction that dies before the change is cheaper than one that dies after
it.

`0.9.2` is that refusal learning to say **what** refused. Of the 25 structural refusals in the
two held-out files plus `fixtures/engine.ts`, **all 25 said `no se puede tokenizar`** — one
message for nine different constructs, so a limit of this reader was publishing itself in the
voice of a syntax error in the source. Each refusal now carries a name: `PLANTILLA_LITERAL` 9,
`OPERADOR_BOOLEANO` 4, `FUNCION_FLECHA` 3, `COMPARACION` 2, `MIEMBRO` 2, `REGEX_LITERAL` 2,
`ASERCION_TIPO` 1, `PALABRA_RESERVADA` 1, `BLOQUEADA_POR_ANCLA` 1. The prediction that failed
first was the guess: naming `.length`, calls, `satisfies`/`as` and `=>` was predicted to explain
17 of calcom's 20 and leave under 3 % generic. Measured, those four cover **1 of 20**; the
template literal, which the guess never mentioned, is **9 of 20** (45 %). The census publishes
`por_causa` over the structural population and `causa_de` for every refusal, with the invariant
`suma(por_causa) + con_entorno == no_evaluables` asserted in the tests.

What it cost, and none of it was the language's:

- **A refusal can be inherited.** `BASE_URL = WEBAPP_URL` reported `no se puede tokenizar en 50`
  on a body ten characters long: the position belonged to the constant it reads. A classifier
  that scanned the body would have lied on 1 of 25, so the inheritance is labelled where it
  happens and the message gains the culprit's name (`WEBAPP_URL: …`).
- **"Unnamed" points both ways.** A refusal the tables do not cover still comes from a rule of
  the evaluator, and that rule writes its name in the message (`texto en aritmetica`).
  Reporting it as `SIN_CAUSA_NOMBRADA` was the same defect pointing the other way, so it reads
  `REGLA_DEL_EVALUADOR`: an entry saying where to read, not a bucket pretending to be a
  diagnosis.
- **The mask, not the delimiters, names the literal.** A masked position has no token, so the
  cause is the literal that stands there — found by walking back to where it opens, which is why
  the `/` of a division does not become `REGEX_LITERAL` and a `?.` inside a comment does not
  become `MIEMBRO`. On code the longest match wins, so `!==` is a comparison and not a `!`.

The measurement that matters for the next act is the cross, now priced: of calcom's 60
environment-bound anchors, **13 are blocked by the environment alone** and **31 also stop at a
boolean operator**. `0.9.2` read those 13 through `causa_de` — the head of a chain — and
published `--env` at 38 → 51; `0.9.3` measured **48**, because three of the thirteen have a
second blocker standing behind the read. The operator surface set aside in `0.9.1` was never
wrong either: it is what stops the other 50.

`0.9.3` is that environment becoming an **argument** instead of a hole. `--entorno map.json`
takes `{VARIABLE: "valor"}` — the deployment the source is written for — and a read of
`process.env.X` becomes a value only when `X` is in that map. Measured on
`calcom/cal.com@ae027bb7`, declaring the 63 variables the file reads moves **38 → 48 of 118**
(40,7 %): `con_entorno` 60 → 50, `estructurales` 20 → 20. The prediction was 51; the 3 that did
not move are the ones whose first cause was the environment and whose second was `as string`,
`parseInt(…)` and a ternary — `causa_de` publishes the head of a chain and not the chain.

Four decisions hold the act together, and each of them is a way to be green over nothing:

- **No default, ever.** `X` absent from the map is `VARIABLE_NO_DECLARADA`, not the fallback:
  `process.env.FALTA || "d"` stays unpriced even when the map is non-empty, because the value
  would come from an operator act that does not exist yet. A map is a closed world or it is
  nothing.
- **The map is published in every receipt.** `censo` and the five terminal receipts of
  `comparar` carry `entorno`, because the same commit under another map is another census. Without
  it a differential receipt is two numbers with no argument between them.
- **An unreadable map is `NO_MEDIDO`, never an empty map.** An empty map is exactly what a source
  that reads nothing looks like, so turning a typo into one would silence every read in the file.
  A number in the map is refused for the same reason: `process.env` yields text, and coercing
  `25` to `"25"` describes a type the deployment cannot have.
- **`--manifest` refuses `--entorno` out loud.** The map does not travel in the manifest yet, and
  a flag accepted and ignored is the "green over nothing" this series keeps finding.

The bracket form `process.env["PORT"]` and the dotted `process.env.PORT` are the same read, and a
string that merely names a variable — `"process.env.PORT"` — is still a value.

`0.9.4` reads `!`, `&&` and `||` — but only over a map that already closes the environment, and the
order is the point: an operator over a free variable is not a function, it is a wish. With the 63
variables of `calcom/cal.com@ae027bb7` declared, the file moves **48 → 64 of 118** (54,2 %):
`con_entorno` 50 → 34, `estructurales` 20 → 20, and `immich@a51a4385` stays at **12 of 16**
because none of its four refusals is an operator. The preregistro predicted 63, and the difference
is named rather than rounded:

- **The prediction missed by one, and the census says why.** Fifteen bodies whose only symbols are
  `process.env.X`, text and an operator were predicted to move. A sixteenth moved:
  `EMAIL_FROM_NAME = process.env.EMAIL_FROM_NAME || APP_NAME`. The residue heuristic that selected
  the fifteen classes any identifier as opaque, and `APP_NAME` is an anchor the reader closes — so
  the sixteenth body was never mixed, and the instrument was the thing being measured.
- **A latent defect stood between the count and its number.** `_resolver` built the inner reader
  without the map, so `A = BASE` — where `BASE = process.env.BASE_URL || "x"` — refused
  `VARIABLE_NO_DECLARADA` on a variable the map declared. The refusal carried the same text and the
  same cause as an honest one, which is why `0.9.3` could not see it: a weaker reader reporting a
  gap in its subject's own words. The map now crosses the hop, and `ao_mapa_salto` dies at the test
  that pins it.
- **The truth of a text is JavaScript's, written down once.** `""` is false; `"0"` and `"false"`
  are true. A reader that borrowed Python's rule would answer `process.env.DRY_RUN || "no"` with
  the fallback for a deployment that exported `DRY_RUN=0` — a divergence with no failing test
  anywhere, because the test would be run with the same wrong rule.
- **`null` is a decision; absence is silence.** A key declared `null` says the deployment does not
  define the variable: `X || "d"` is `"d"`, `X ?? "d"` is `"d"`, `!X` is `true`, and `X.foo` is
  still refused — there are no members of nothing. Omitting the key is a different decision and
  stays `VARIABLE_NO_DECLARADA`. The receipt publishes the map it used, with its `null`s.
- **Reading is eager, and that is the conservative choice.** Both operands are read even when the
  left one decides, exactly as `??` already did: an operand the reader cannot close is a gap, and a
  branch would only hide it. `E || !IS_SELF_HOSTED` is therefore still unpriced where `E` is a
  value, because the second operand reads `.some(...)`.

What did not move is the frontier the act declared: `parseInt(process.env.X || "1", 10)`, a
template literal, `!==` and an unknown call each keep their second blocker, so 19 of the 20 mixed
bodies the preregistro set aside stay unpriced — the twentieth, `EMAIL_FROM_NAME`, was never
mixed. Naming an operator must not become a licence to read past it:
`test_la_frontera_del_acto_no_se_mueve` is the test for that, and the suite is at 171 tests with
four mutants over this act, all dead.

`0.9.5` adds the surface a differential needs, the differential, and the ceiling that lets either
one leave the machine. The census publishes `valores` — one per evaluable, inside the same walk
that already decided `evaluables` — and `--entorno-base` / `--entorno-destino` compare the same
commit under two maps. On `calcom/cal.com@ae027bb7` with its 60 declared variables against the
same 60 declared `null`: **26 of the 64** shared anchors change value and **38** do not, which is
the whole population — 26 + 38 = 64, and nothing is read in one map and not the other.

- **The map crosses the hop, and the value crosses with it.** `valores` is filled by the loop that
  already classifies, not by a second pass over the anchors: two passes are free to disagree, and a
  receipt carrying two counts of the same population is a receipt that cannot be used as evidence.
  A `valores` with one entry too many or one too few is what `ao_valores_de_mas` and
  `ao_valores_sin_poblacion` die to prevent.
- **A difference is the finding, not a failure.** The differential exits `0` when it measured:
  26 anchors that move between two deployments of one commit are the answer, not an error. Only
  `--exigir-invariancia` turns movement into `1`, and the Action forwards it as
  `exigir-invariancia` — a check that fails on *any* drift is a check a team turns off.
- **An anchor read in neither map is not an invariant one.** `solo_en_base` / `solo_en_destino`
  carry the anchors that appear in one reading and not the other, because `cambian + invariantes`
  must equal `comunes` and nothing else: an anchor whose key the base map does not declare was
  never compared, and counting it as agreeing is the false green over an unread anchor that this
  tool exists to refuse.
- **The fingerprint names the deployment.** `mapa_base` and `mapa_destino` carry `sha1:` over the
  canonical JSON of the map, so key order in a file is not part of an identity and `{ancla: valor}`
  alone can no longer say the value moved without saying under which map. Measured: nulo
  `sha1:914291b3…`, texto `sha1:5da4f355…`.
- **`null` declared and a key absent are different maps, and the fingerprint sees it.** They have
  to be: `X` declared `null` evaluates, `X` absent refuses, and a fingerprint that ignored the
  difference would attribute both readings to the same deployment.

The ceiling is its own act, because a receipt that cannot leave the machine is not a result. The
census of this file was **34 141 B as one line** and is now **1 031 B** (-97,0 %) with
`evaluables`, `declaradas`, `cobertura` and `por_causa` intact; the differential is **2 000 B**
and keeps the direction, both fingerprints and **15 of the 26** rows, saying `_resto: 11` for the
ones that did not travel. `bytes` prices the receipt the line replaced, and `receipt-file` keeps it
whole — `rc`, `receipt` and, when it differs, `resumen`, in one file that cannot claim to be the
other.

- **A list of rows travels as rows.** A differential's `filas` *is* the finding, and its width is
  the same three key names repeated 26 times, not information: the summary spends those bytes once
  on `columnas`, then on as many leading rows as fit, in the finding's own order. The first draft
  collapsed the list to `{"n": 26}`, which is a receipt that says twenty-six things changed and
  names none — `re_lista_sin_muestra` is that draft, preserved as a mutant.
- **Nothing leaves without saying it was cut.** `_resto` counts the rows that did not travel and
  `_resumido` names the keys a compressed node could not carry. A summary that looked like a
  complete receipt would be the same lie as a green over zero anchors.
- **A summariser that cannot read the receipt is a refusal.** `receipt` is published by the
  summary and never by the raw receipt, so a step that could not summarise exits `20` instead of
  publishing a line nobody can parse. The module's `--self-test` prints prose rather than a
  receipt and crosses untouched: it is the wiring proof, and a summary of it would measure the
  wrong subject.

One defect of this act is worth keeping: the summary was installed and then overwritten by the
line that predated it, so the first measurement reported a 34 150-byte "summary" and the ceiling
looked satisfied by nothing. It was caught by replaying the `run:` block as the shell actually
runs it — `bash --noprofile --norc -e -o pipefail` — and by checking the byte count of the line
rather than the exit code of the step. The suite is at 191 tests with ten mutants over this act,
each one dead by a test of its own module — `bytes` pricing the compressed object instead of the
published line survived the first draft, because every receipt the suite fed in was canonical to
both readings: `re_bytes_no_pesado` only dies against a receipt written the way `json.dumps` writes
one, with the separators' spaces still in it.

The second defect cost a red on `main` and is the same shape. `0.9.5` sent every stdout to the
summariser, including the empty one a module leaves behind when it refuses before reading: on run
46104450819, `backend: node` with no node printed `NO_MEDIDO · SIN_ORACULO_VIVO` on stderr and
nothing on stdout, the summariser answered `rc=2` for the empty string, and `rechazar` failed the
step with `20` — the caller read the summariser's verdict under the module's name. An empty
receipt is not a receipt to compress: the step now publishes `rc` beside `receipt=` and says in
the summary that the cause is on the log. `PasoDePublicacionTest` takes the `run:` body out of
this file and executes it with `bash --noprofile --norc -e -o pipefail`, so the guard is measured
by the shell and not by its name: with the branch removed, the test reports `20 != 2`.

`0.9.6` changes the instrument, not the subject. `tools/mutate.py` now judges each mutant with the
tests of the module that owns the site, and pays for the whole suite only when that module does not
see the edit; the copies are spread over workers. No byte of the package moved, and the ten mutants
of `0.9.5` keep their verdict: read again on two fresh copies the old way (`--estricto`), all ten
agree on `estado`, `veredicto` and `detalle`, and `re_sin_techo` is `MUERTO [propio]` by
`tests.test_resumen.ResumenDeReciboTest` in both readings — `116,1 s` one way, `7,2 s` the other.
The same ten cost **18m49s** of wall clock the old way and **2m10s** the new one.

- **The 300 s per mutant were waiting, not arithmetic.** The whole suite takes 125 s of wall clock
  for 23 s of CPU on this machine, because most of it is a subprocess that has to be spawned and
  waited for: the lever is concurrency, and threads are enough since no waiting thread holds the
  GIL. Once the base is paid, a mutant its owner kills costs 7,2 s to 21,1 s instead of two full
  suites, and four run at a time.
- **The scope of a verdict is published, never implied.** `alcance: dueno` says the owning module
  killed the mutant in its own tests under `-f`; `alcance: suite` says that module stayed green and
  the rest of the suite had to answer. A `VIVO` is only pronounced after the whole suite has
  agreed, so a mutant the owner cannot see is never called alive by the cheap route, and a kill by
  another module's tests is still printed as `[ajeno]`.
- **`-f` does not change what a kill looks like.** The first red is repeated on a second fresh copy
  and the marks are compared as a set, with the path each copy ran in normalised out — the same two
  rules as before, applied to the shorter run. `--estricto` keeps the previous procedure, the whole
  suite in two fresh copies, for exactly the case where the cheap route has to be measured against
  it.
- **What a kill is compared on is the class, because that is what the report carries.** Both routes
  publish `tests.test_<modulo>.<Clase>` and not the method: `unittest` writes the failing method
  before the parenthesis and the class inside it, so the mark never sees the method name. Narrowing
  it would change every `detalle` in the table, which is a change to the subject's published
  evidence and not to the harness.
- **One copy per worker, so the space is asked per worker.** The 64 MiB refusal is now multiplied
  by the number of workers, and `--trabajadores N` defaults to `min(cpu_count, 4)`: two copies per
  mutant are live at a time, so a machine that passes the old check with four workers would have
  been four times over its headroom. The message names both factors.

The whole table, measured with this harness under CPython 3.9.6: `aplicables: 93 · muertos: 88 ·
vivos: 5 · flaky: 0 · huecos de cobertura: ninguno · muertos por un test ajeno: 3` — the same three
declared foreign kills the serial passes had accumulated — in **4m03s**, with `85` rows decided by
their own module and `8` by the suite.

The same 93 under CPython 3.14.8 read `muertos: 89 · vivos: 4` in **15m12s** (`86`/`7`), and exactly
one row moves: `au_sin_B` goes `VIVO` to `MUERTO [propio]`, killed by
`tests.test_audit_self_test.ContratoDelProbe.test_la_sonda_no_deja_bytecode_en_el_arbol`. That is not
drift. `au_sin_B` removes the `-B` that keeps the bytecode cold, so its reachability is a property of
the interpreter and not of the subject: `mutate._persiste_bytecode()` already puts it in
`INALCANZABLES` where the interpreter writes `.pyc`, and
`tests/test_mutate.py::test_el_flag_B_solo_puede_importar_donde_el_interprete_escribe_pyc` measures
that structurally rather than by running it. Four mutants stay alive in both readings: the three the
README calls inmatable, and `au_fd_solo_w`.

One number this act does not explain, and publishes instead of smoothing: the per-row wall clock.
Summed, the 93 rows cost `902,4 s` under 3.9.6 and `3 334,5 s` under 3.14.8, and the suite going from
`91,4 s` to `101,5 s` does not account for the difference. It is reported as measured, not attributed.

The suite is at **198 tests**; the seven
that pin this act are in `tests/test_mutate.py`, and they were checked the way the harness checks
its subjects: with the row ordering removed, the order test fails (`['sp_borde_izq', 've_sin_recorte']`
inverted); with `as_completed` read as `futuros.items()`, it cannot fail at all, which is why that
draft was not kept.

`0.9.7` fixes one test of that act and nothing else. `v0.9.6` left `main` red on run 46157299976:
`test_la_etapa_del_dueno_y_la_suite_no_comparten_copia` read the inode of the mutated file at each
of the three runs and asked for three different numbers, and under 3.14 two of them came back equal
(`[4785326, 4785326, 4785379]`). The harness was right and the litmus was wrong: the suite runs on
the **same path** as the owner's stage, and `_mutar` re-copies the tree into it, so the file that
lands there takes the inode number the system has just freed. An inode is state of the filesystem,
not of the object — a repeated one does not prove a repeated copy, and a distinct one does not
prove a fresh one. The test now reads the sequence of acts (mutate, run, mutate, run, mutate, run)
and asserts what the act actually claims: between the owner's run and the suite's, the tree is
rebuilt. No byte of the package or of the harness moved, so the 93-row table above stands as
published, and `v0.9.6` is left where it is, red, as the record of the defect.

## Use as a GitHub Action

`action.yml` is a composite action. It runs the clone your workflow pinned, installs nothing,
and exits with the module's own code, so a divergence fails the step instead of colouring a log.

```yaml
- name: anchor parity
  id: guard
  uses: ./                       # or alexisromtz-lab/ts-py-anchor-guard@<sha> once pinned
  with:
    check: anchor
    source: fixtures/engine.ts
    reference: fixtures/anchors.json
- name: read the verdict
  run: echo "rc=${{ steps.guard.outputs.rc }}"
```

`check` picks the module and is the only required input:

| input | default | applies to | meaning |
|---|---|---|---|
| `check` | — | all | `anchor` · `census` · `diff` · `embed` · `probe` |
| `self-test` | `false` | all | run the module's own `--self-test` instead of measuring a subject |
| `source` | — | `anchor` | the TypeScript file to read |
| `reference` | — | `anchor` | the JSON file with the anchors to compare |
| `manifest` | — | `anchor` | a versioned manifest of signed correspondences; takes the place of `source` and `reference` |
| `backend` | `auto` | `anchor` | `auto` · `node` · `estatico` — the reader's own spelling, forwarded verbatim |
| `environment` | — | `census` | JSON `{VARIABLE: "valor"}`; `null` declares an absent variable, an omitted key refuses the read |
| `env-base` | — | `diff` | the map the commit is read under as the base deployment |
| `env-destino` | — | `diff` | the map of the deployment it is being moved to |
| `exigir-invariancia` | `false` | `diff` | turn movement between the two maps into `rc 1`; absent, drift is a measurement |
| `tolerance` | `0.0` | all | relative tolerance; the receipt still reports the residual |
| `canvas` | — | `embed` | `W H` of the host canvas |
| `window` | — | `embed` | `W H` of the sub-viewport |
| `rect` | — | `embed` | `X Y W H` to check against; omitted means "compute it" |
| `receipt-file` | — | all | write the **whole** receipt here, with `rc` and — when the output line was summarised — `resumen` beside it. Evidence a later reader can re-open; a failure's receipt is written too |
| `profile-a` / `profile-b` | — | `probe` | two whitespace-separated profile files |
| `bands` | — | `probe` | band count, at least 3 and at least 32 samples each |
| `max-shift` | — | `probe` | cap on the shift searched, in samples |

Two outputs: `rc` (`0` · `1` · `2` · `20`, the same value the step exits with) and `receipt` — the
receipt as **one line under 2 KiB by construction**, not as the whole thing. A receipt that would
be longer is summarised (counts and the finding kept, wide tables reduced to their names) and
`bytes` says how big the whole one was; set `receipt-file` to keep it. The same bounded text goes
to `$GITHUB_STEP_SUMMARY`.

A refusal at the boundary publishes the code and leaves `receipt` empty, because nothing was
measured: run `45895456729` found that slot empty instead of reading `20`, since the script wrote
its outputs only after the module had run. An empty output is not a zero, so the three inputs a
call can get wrong now leave through the same door as the module's own `20`, and `outcome:
failure` plus `rc` say which side refused and what it said.

**`shell: bash` inside a composite action is `bash -e`.** That one fact cost three runs.

Run `45842378293` went red and left `steps.desvio.outputs.rc` empty at the next step. The obvious
reading, that the runner drops outputs of a failed step, was wrong; run `45842590972` showed why:
the script never reached the line that writes anything. `salida=$(python3 -m ...)`
is a plain assignment whose status is the command's, so under `-e` the first divergence killed
the script, and the exit code it meant to propagate was the bullet. `set +e -u -o pipefail` hands
the flow back to the script. Run `45842813192` then reported `rc: 1` from a **failed** step, so
outputs do survive a failure; what did not survive was my own `set -e`.

And the local verification missed all of it because it replayed the `run:` block as `bash file`,
without `-e`. Same text, different program: an instrument that does not reproduce the subject's
shell is not an instrument. Replay it as `bash --noprofile --norc -e -o pipefail`.

`receipt-file` stays, because a caller may want the verdict and the receipt on disk without
parsing outputs, and because a file is easier to attach to a review than a one-line field.

**`backend: estatico`, measured with no `node` on the `PATH`.** `auto` prefers the live oracle
whenever it can reach one, so a runner that ships `node` — every GitHub-hosted runner does —
never exercises the dependency-free path. The claim "no external toolchain required" was
therefore resting on local unit tests, not on the published action. `ci.yml` now filters the
`PATH` in a step of its own and runs the action three times under it:

| step | input | exit | asserted from |
|---|---|---|---|
| `estatico_sin_node` | `backend: estatico`, fixtures | `0` | `"backend": "estatico"`, `"peor_rel": 0.0` in `receipt-file` |
| `estatico_desvio` | `backend: estatico`, `PLATE_W` moved by 1.0 | `1` | `causa: DIVERGE` in `receipt-file`, written by a **failing** step |
| `node_ausente` | `backend: node`, same fixtures | `2` | `NO_MEDIDO · SIN_ORACULO_VIVO`, read from the module |

The third row is not a control for its own sake: it is the **witness** that the filter worked.
If `node` were still reachable inside the composite, that step would return `0` and the two
green rows above would prove nothing about a node-free environment. A green pair with a green
witness is silence; a green pair with a red witness is a measurement.

The step that filters `PATH` fails on purpose when it removes nothing, so a runner image that
stops shipping `node` breaks the job loudly instead of turning the axis into a no-op.
`tools/contrato_censo.py` runs there too: two of its rows change class with the environment
(`--backend node` is `POR_DISENO · RC_OK` when `node` is present and `MEDIDO · RC_NO_MEDIDO`
when it is not), so the grid measures the axis instead of deducing it.

Run `45848898559` on `75da161`
([link](https://github.com/alexisromtz-lab/ts-py-anchor-guard/actions/runs/45848898559)) is where
that axis stopped being a promise. On `ubuntu-latest` the filter removed `/usr/local/bin`, the
action ran on the filtered `PATH`, and the two witnesses came back as predicted: `0` with
`"backend": "estatico"` and `"peor_rel": 0.0`, and `NO_MEDIDO · SIN_ORACULO_VIVO · node >= 22.6
no esta disponible` for `backend: node`. The same run answers a question this file would
otherwise have to guess at: an `env:` block on a step that says `uses:` **is** inherited by the
composite's `run:` steps — the filtered `PATH` shows up in the step's own environment in the log,
and the `2` proves it reached the script. Whether an `env:` block declared on a `uses:` step
crosses into the composite's own `run:` blocks is what decided whether this axis could be tested
at all, so it was measured here rather than cited: the documented `env` context describes a
step's own `run:`, and the part that mattered was the one the docs leave to the runner.

**What is measured, and what is not.** The seven runs below were executed by hand on 2026-11-25 with
the `run:` block extracted from `action.yml` and `GITHUB_OUTPUT`/`GITHUB_STEP_SUMMARY` pointed at
files — on node `v24.15.0`, Python 3.12.13:

| input | exit | evidence |
|---|---|---|
| `check=anchor`, fixtures | `0` | 21 anchors, worst relative error `0.000e+00`, `backend: node v24.15.0` |
| `check=embed`, `1920 1080` / `960 864` / `480 108 960 864` | `0` | `escala: [1.0, 1.0]`, the 1:1 invariant holds |
| `check=probe`, 192 samples, 4 bands, shift `0.4` injected | `0` | `desplazamiento_global: 0.4002`, every band within `0.0011` of it |
| `check=anchor` with `PLATE_W` moved by 1.0 | `1` | `causa: DIVERGE`; the step goes red |
| `check=anchor` with no `source` | `20` | `::error` annotation, no traceback |
| `check` misspelled | `20` | names the three accepted values |
| `check=probe` with 2 bands | `2` | `NO_MEDIDO · PERFIL_INVALIDO · hacen falta al menos 3 bandas` |

The `action` job in `ci.yml` then takes over: fourteen steps, eight of which run the action
itself — three module self-tests, the fixtures, the negative control, and the three node-free runs
described above — with the rest asserting what those runs returned: `rc == 0` and a zero worst
error on the fixtures, a `reference` displaced by one unit that has to make the step **fail** with
`rc: 1` and `DIVERGE` in its `receipt-file`, and the exact `NO_MEDIDO` reason from the node-free
witness. A job that only proves the happy path proves the step runs, not that it judges.

Run `45842968869` on `bef8f75`
([link](https://github.com/alexisromtz-lab/ts-py-anchor-guard/actions/runs/45842968869)) finished
with `action: success`, one step red on purpose inside it, and the three interpreter jobs green.
That is what turns the seven rows above from a local measurement of a script into a measurement
of the action. Run `45848898559` on `75da161` supersedes it as the current witness: same job, the
six node-free steps added, and the verdicts cited in the section above.

**Pin a tag or a sha, never `main`.** A tag is cut only on a commit whose `action` job came back
green, which is why this file does not list its own tags — that sentence would go stale the
instant one is cut. Ask `git ls-remote --tags` instead.

```yaml
uses: alexisromtz-lab/ts-py-anchor-guard@v0
```

**Measured from outside, once.** Everything above runs `uses: ./`. Run `45852973521` pinned the
tag from a throwaway repository that this project does not own (`ubuntu-latest`, `2026-11-26`):
`check=anchor`, `backend: estatico`, `{"TASA": 0.15}` against a source of `0.15` returned `0` with
`"peor_rel": 0.0`; the same pair with the reference displaced to `0.25` returned `1` with
`causa: DIVERGE` and left its `receipt-file` readable after the step went red; and the same
positive inputs with no `backend` declared returned `0` from `auto`, which selected
`node v24.22.3`. That repository is a throwaway host for the run, not a product: read the link as
a record of what happened, and `consumers/v0/` — byte-identical to what ran — as the reproducible
artifact, with its `README.md` saying how to push it to a repository of your own in four commands.

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
- **Text is a value.** A string literal is compared by exact equality — an event name, an
  error code, a route — and the tolerance does not apply, because two strings have no
  distance between them. A text row carries `tipo_valor: "texto"` and no `peor_rel`, and a
  divergence names the two strings instead of a relative error.
- **Object keys may be text.** `{ "ancho-max": 1725, ANCHO }` resolves both as
  `CAJA.ancho-max` and `CAJA.ANCHO`; a shorthand whose name is not declared is
  `FuenteIlegible`, never a `0`.
- **Numbers may carry separators.** `1_000_000` is `1000000`: the separator is syntax, not a
  digit, and refusing it made a real `constants` file unreadable for a reason the port
  cannot share.
- **Comments and regex literals are not code.** A `//` inside `"https://…"` does not open a
  comment, and a regex literal (`/[\w'()]/gi`) does not open a string on its `'` — the two
  defects that kept the reader from reading its own subject.
- **Calls:** `Math.floor`, `ceil`, `round`, `abs`, `sqrt`, `sign`, `min`, `max`, `pow`, and
  the constants `Math.PI` / `Math.E`.
- **Refused, by name:** block bodies, loops, destructuring, and calls into anything not in
  the list above (`reduce`, `map`, helpers of the project). A refused anchor surfaces as
  `NO_MEDIDO · ANCLA_NO_EVALUABLE` and is listed under `no_evaluables` — never a pass, and
  never an exception. A whole object literal compared against a number is refused the same
  way: name a field (`rectView.left`) and it compares.

**How much of a real file that is, measured.** Three production `constants` files were run
through `--censo` at fixed commits — `posthog/posthog@bda26b33`
`frontend/src/lib/constants.tsx` (77 551 B), `marimo-team/marimo@906e4c2f`
`frontend/src/core/constants.ts`, `langfuse/langfuse@a2cd4753`
`packages/shared/src/constants.ts`. The reader returns **72 of 72** declarations
(67 + 3 + 2, the same count `grep -c '^export const'` reports) and evaluates **56 of them,
77,8 %**. Before strings were values it evaluated 13 of 72, and the 59 refusals were
classified by hand: 31 strings, 17 comments, 4 template literals, 2 `enum` member access, 1
numeric separator, 1 spread, 3 with no single cause. The first version of that census read 18,1 % of the
subject and would have reported 100 % of its own reach — which is why `--censo` prints the
declared count next to the read one.

Those three files are also the ones the reader was taught on, so two held-out files were run
next, pinned by commit and untouched by any of that work: `calcom/cal.com@ae027bb7`
`packages/lib/constants.ts` (14 085 B, 118 declarations) and `immich-app/immich@a51a4385`
`web/src/lib/constants.ts` (10 694 B, 16). The reader returns **134 of 134** and evaluates 38
and 12. Reading generalises; *evaluating* does not, and the reason is not the parser: on
calcom, 60 of the 80 refusals read `process.env` and only 20 are syntax. A `constants` file
is mostly an interface to an environment that is not here, so `--censo` names that
population apart instead of filing it with the reader's own gaps — the three parts publish
the denominator: 118 = 38 evaluable + 60 environment-bound + 20 structural.

The tempting next step was to teach the reader `!`, `||`, `&&` and `true`/`false`, which it
does not support. That was pre-registered against these two files with a prediction of 38 →
70-90 evaluable on calcom, and it is **refuted before writing a line**: teaching operators
moves almost nothing, because the same declarations that use `||` also read
`process.env.WEBAPP_URL`. The operator surface is not the binding constraint and the
measurement says so.

Precedence in the receipt: a measured divergence (`RC 1`) outranks a gap (`RC 2`), because
a number that is wrong is a fact while a number that is unreadable is a hole in the census.
`cobertura` publishes the scope of every receipt — how many anchors the source declares, how
many were compared, and which ones the reference never named — because a green over a subset
is a measurement of that subset and of nothing else.

`--censo` prints exactly the population the reader sees — useful to keep the acceptance set
honest when the source grows:

```
$ python -m ts_py_anchor_guard.anchor_oracle --fuente fixtures/engine.ts --censo
CANVAS_W · const · 1080
...
NO_LEIDA onNode · funcion con cuerpo de bloque
NO_EVALUABLE nearestNode · no se puede tokenizar en 18: ' => (Math.abs(b - v)'
CENSO · 20 declarada(s) · 19 leida(s) (95.0%) · 18 evaluable(s) · 1 por estructura · las
funciones con cuerpo de bloque y las variables locales no se leen
```

The same line over a file that reads the environment — `calcom/cal.com@ae027bb7`
`packages/lib/constants.ts` — splits the remainder in two:

```
CENSO · 118 declarada(s) · 118 leida(s) (100.0%) · 38 evaluable(s) · 60 con entorno ·
20 por estructura · las funciones con cuerpo de bloque y las variables locales no se leen
```

`con_entorno` maps each such anchor to the variables it reads
(`CALCOM_ENV · ['CALCOM_ENV', 'NODE_ENV']`), and it is a report, not an excuse: those
anchors stay `NO_EVALUABLE` with their own motive in `no_evaluables`. What changes is that
the number no longer lies about *why* — a parser gap is work, a variable nobody set is a
fact about the deployment.

Declaring that deployment turns the reads that have nothing behind them into values:

```
$ python -m ts_py_anchor_guard.anchor_oracle --fuente calcom/constants.ts --censo \
      --entorno calcom-env.json
CENSO · 63 variable(s) declarada(s) · 118 declarada(s) · 118 leida(s) (100.0%) ·
48 evaluable(s) · 50 con entorno · 20 por estructura (… OPERADOR_BOOLEANO 4 ·
PLANTILLA_LITERAL 9 …) · las funciones con cuerpo de bloque y las variables locales no se leen
```

`entorno` travels in every receipt, so a receipt without it is a census of no deployment in
particular.

The two silences are different questions and get different names: `no_leidas` is the reader
(it never returned the declaration) and `no_evaluables` is the language (it returned it and
this subset cannot value it — `nearestNode` is a `reduce`, refused by name in the section
above, and the tokenizer stops before the call does). `declaradas` is the denominator, so no
coverage figure can be computed from what the reader happened to reach.

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

### Measured on an engine that had already shipped: nine numbers, `peor_rel 0.0`

Every example above is a fixture. The first run against real code was a TypeScript engine and
its Python port of the same law — `paneo.ts` (627 lines), `transicion.ts` (163),
`modelo-paneo.py` (831) and `predice-transicion.py` (1 846) — with no adapter and no edit on
either side (`video/letras-video`, 26-Nov-2026, version `0.7.0`):

| TypeScript declares | Python computes | path measured | `peor_rel` |
|---|---|---|---|
| `RAMPA_MEDIDA = [0.453, 0.764, 1]` | `(0.453, 0.764, 1.0)` | `RAMPA_MEDIDA.0` … `.2` | `0.0` |
| `CUADRO = { ancho: 1080, alto: 1920 }` | `(1080, 1920)` | `CUADRO.ancho`, `.alto` | `0.0` |
| `VENTANA = { ancho: 864, alto: 960 }` | `(864, 960)` | `VENTANA.ancho`, `.alto` | `0.0` |
| `PLACAS.compass.nativo = [768, 1344]` | `{"compass": [768, 1344]}` | `PLACAS.compass.nativo.0/.1` | `0.0` |

Nine numbers, `rc 0`. Four things the run cost, all of them now in the code or in this file:

- **A vector in the reference used to kill the whole receipt.** `float(esperado)` ran outside
  the guard, so a port that hands back `RAMPA_MEDIDA = (0.453, 0.764, 1.0)` raised `TypeError`
  and the file's scalars were never reported — `NO_MEDIDO` with a traceback instead of a named
  gap. The source side already refused literals by name; the reference side does too now, and
  the remedy is the path it prints.
- **A green over a subset carried no scope.** The first successful run returned `rc 0` over `3`
  of the `7` anchors that file declares, and no field said so. Hence `cobertura`. It reports;
  it does not fail — a reference may be a subset, it may not be silently smaller.
- **Shape is not derivable, and guessing it would be a false green.** TypeScript `CUADRO` is
  an object, Python `CUADRO` is a tuple. Named `CUADRO.0` it is refused (`ANCLA_NO_EVALUABLE`),
  never matched by position; named `CUADRO.ancho` it measures. Stating that correspondence once,
  per repository, is the caller's work: a tool that inferred it would be inventing the mapping
  it claims to verify.
- **A renamed anchor is invisible.** The same ramp is `NUDOS_S5` in TypeScript and `RAMPA_S5`
  in the port. Comparison is by name, so that pair is neither a pass nor a failure — it is
  absent from every receipt. `cobertura.omitidas` is what makes the absence visible.

Drift is caught at the scale this engine cares about: shifting `RAMPA_MEDIDA.0` by `0.001`
returns `RC 1 · DIVERGE` with `peor_abs 0.001`, `peor_rel 0.002203` and the rounding residual
of the measured value.

### A manifest: the correspondence is signed, not remembered

Two of the four costs above end in a name — `CUADRO.0` against `CUADRO.ancho`, `NUDOS_S5`
against `RAMPA_S5` — and both lived in my head, which is not a place a gate can read. The same
engine, re-measured with the correspondence committed as data (`version 1`, 26-Nov-2026):

```json
{
  "version": 1,
  "pares": [
    {
      "nombre": "paneo",
      "fuente": "paneo.ts",
      "referencia": "ref-paneo.json",
      "mapeos": {
        "CUADRO.ancho": "CUADRO.0",
        "CUADRO.alto":  "CUADRO.1",
        "VENTANA.ancho": "VENTANA.0",
        "VENTANA.alto":  "VENTANA.1"
      },
      "exigir_cobertura_total": false
    }
  ]
}
```

| invocation, same four files | `rc` | what the receipt says |
|---|---|---|
| `--manifest ts-py-anchor.json` | `0` | `12` anchors compared at `peor_rel 0.0`; `20` declared, `16` omitted, `14` ignored |
| `… --exigir-cobertura-total` | `2` | `COBERTURA_INCOMPLETA` naming the `11 + 5` roots it skipped |
| `… RAMPA_MEDIDA.1` moved by `1/10 000` | `1` | `DIVERGE · NUDOS_S5.1 · peor_rel 0.000130873` |
| the same files with no manifest | `2` | `ANCLA_NO_EVALUABLE · CUADRO, VENTANA`, `0` compared |

What the file decides, and why each decision is a refusal rather than a convenience:

- **A mapping measures; an inference would not.** `CUADRO.ancho → CUADRO.0` is a signature. A
  reader that paired the members by position would be measuring its own guess, and the receipt
  would say `0.0` about a pairing nobody declared.
- **A key nobody addresses is counted, not compared.** A dump from the Python side carries keys
  this contract never signed (`CONTRASTE`, `RED`, `MIN_CORTES`…); they come back as
  `referencia_ignorada` and the count is in the totals. Silently absorbing them would hide a typo
  in a mapping; refusing the file would make the manifest unusable.
- **A mapping that does not resolve is `MAPEO_INVALIDO` (`rc 2`)** — and it never overwrites a
  `DIVERGE`: a measured divergence is about the port, a broken signature is about the contract,
  and the first one outranks the second.
- **Every field is read or named.** `exigir_covertura_total` is `INSUMO_ILEGIBLE`, not "absent":
  a misspelled switch is a gate that is off while its author believes it is on.
- **Precedence is stated, not inherited.** `1` if any pair diverges, else `2` if any pair is a
  gap, else `0`. Not `max()`: `2` is a gap, not a severity.
- **The manifest outranks the command line** for `tolerancia` and `backend` — the file is
  reviewed and the invocation is not. `--exigir-cobertura-total` is the one exception, and only
  in the safe direction: it can turn a report into a defect, never a defect into a report.

`fixtures/manifiesto/` is the same three shapes kept small, so `ci.yml` exercises the manifest
under the node-less `PATH` before this paragraph is believed.

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

Text crosses this boundary too, and only as text: the probe returns the exported value, so a
string arrives as a string and a boolean arrives as a boolean — which `medir()` drops, because a
`true` compared against a port's `1` would be a measurement of a coercion the engine never made.

The receipt always names the backend that produced the reference values, because a number
measured by an interpreter and a number measured by a model of that interpreter are not the
same evidence. `--backend estatico` forces the model; `--backend node` fails with
`NO_MEDIDO · SIN_ORACULO_VIVO` when no suitable node is present; `auto`, the default, uses
node when it can.

**A node that is there and cannot load the source is the same gap in the reader.** Node's
strip-only mode refuses `enum` and `namespace`, which are ordinary TypeScript — six `export
enum` in the first production file this was measured on (`posthog/posthog@bda26b33`,
`frontend/src/lib/constants.tsx`). Until `0.8.1` that made `auto`, the path nobody has to
declare, answer `rc 2 ORACULO_VIVO_FALLO` on a file the static reader measures exactly: the
instrument refused the subject because of its own reader. `auto` now falls back to its
arithmetic and **publishes the reason** in the receipt's `aviso`, because a fallback that is
not named is a weaker instrument wearing a stronger one's name:

```
"backend": "estatico",
"aviso": "node no leyo la fuente (node rc 1: SyntaxError [ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX]:
          TypeScript enum is not supported in strip-only mode); medido con el lector estatico",
"rc": 0
```

An explicit `backend: node` — on the command line or in the pair — still fails with
`ORACULO_VIVO_FALLO`: that caller asked for the second implementation and does not get to
receive the first without knowing. What was asked for and could not run is a gap, never a
demotion to the other mode.

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
| `89` of `93` mutants killed under CPython 3.14.8 and `88` of `93` under CPython 3.9.6, where the fifth survivor is the one the harness declares unreachable there, `0` flaky, `0` coverage holes; the survivors that no input reaches are declared with their reason, and a kill from another module's test is reported rather than counted (`3`, all declared) | 93 curated mutations across nine sites (six modules, the CLI, two harness probes), each in a fresh copy, every kill repeated on a second fresh copy | yes — `python3 tools/mutate.py`, which ships the 93 mutations and names the exemptions with their reason |
| `18` of `22` contract rows measured, `4` declared with their motive — and the four move when `node` leaves the `PATH` (`3` `POR_DISENO` with it, `2` `SIN_NODO` without) while the `18` stays put | every CLI run once per row, its exit code compared with the process's, a row expecting `1` refusing a run whose stderr carries a traceback, no expectation taken from a flag's name, and a `backend` axis whose `--backend node` row changes class with the environment instead of assuming one | yes — `python3 tools/contrato_censo.py`; `ci.yml` also runs it under a filtered `PATH` |

Two boundaries are declared rather than measured, and no claim here crosses them:

- **No browser and no compositor are observed.** `subpixel_probe` measures profiles you give
  it. Whether a real compositor snaps layers to integer pixels, and at what phase, is a
  property of that compositor, measured elsewhere; this package can feed the measurement but
  cannot stand in for it.
- **`0.000e+00` is agreement between two executables, not proof of a correct engine.** If
  the TypeScript source is wrong, both the source and the port are wrong together, and the
  verifier is silent by construction. It answers "same function", never "right function".

### What the tests would notice: 83 mutations, 79 killed

A suite can read its fixtures and still assert nothing. The question is not "does this test
open the fixture" but "if the code were wrong, would anything go red" — so 79 one-line
mutations are applied across nine sites (the five modules, the CLI, and the three harness
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
- **40 of 44 died** when the escape routes of `0.4.4` were the last thing added. Four mutants
  were added over the routes that let a crash look like a
  verdict, and all four died: one that removes the boundary's translation (`cli_choque_escapa`),
  one that turns the translated crash back into `1` (`cli_choque_es_uno`), one that lets an
  empty reference conform again (`ao_ref_vacia_ok`), one that lets the reader print nulls with `0`
  (`lo_nulos_conforman`) — plus the short profile (`sp_perfil_escapa`) and the census's own
  blind spot (`ce_choque_conforma`). The four survivors were the declared ones below.
- **45 of 50 die now.** The four of `0.4.4` were joined by six more over the three thinnest
  sites the table had — `anchor_oracle` at 92.7 lines per mutant, `live_oracle` at 74.7,
  `contrato_censo` at 62.3 — and five die: the exclusive edge of a tolerance
  (`ao_tol_borde_exclusivo`, `>` → `>=`), the motive that has to name a cause rather than the
  last line of `stderr` (`lo_motivo_sin_causa`), the version frontier
  (`lo_frontera_sin_flag`, `>=` → `>`), the census's first negative control
  (`ce_control_uno_apagado`), and the choice between `CHOQUE:` and "returned N" in its cause
  column (`ce_tabla_choque_invertido`). The sixth, the boolean filter, is the fifth declared
  exemption: the probe reports `typeof`, so what reaches Python for an exported `true` is the
  string `"boolean"` and no boolean ever arrives. Measured run: `aplicables: 50 · muertos: 45 ·
  vivos: 5 · flaky: 0 · huecos de cobertura: ninguno`, exit code `0`.
- **55 of 60 die now.** The manifest is the ninth site and the thinnest the table has ever had,
  because it is the newest: ten mutants over its validation, its arithmetic and its precedence,
  and all ten die. `mf_tolerancia_del_par_ignorada` and `mf_exigir_cli_no_rige` came from the
  build rather than from review — the defaults that arrive from the invocation are the half of
  the contract a reader of one function never sees: the pair's `tolerancia` and `backend` win
  over the invocation's, and `--exigir-cobertura-total` may only *add* rigour, never relax what
  a manifest already demands. The other eight cover the four refusals
  (`mf_version_ignorada`, `mf_clave_sobrante`, `mf_exigir_no_bool`, `mf_mapeo_no_consume` — a
  mapping that leaves the container inside makes every row compare against a shape that never
  existed), the precedence rule itself (`mf_precedencia_max`, `max()` instead of "a `1` wins,
  then a `2`"), the silence a covered drift needs (`mf_deriva_tapada`), the accounting that
  keeps an ignored key out of the divisor (`mf_ignoradas_comparadas`), and the guard that
  refuses to call a partial measurement complete (`mf_cobertura_sin_guardia`). Measured run of
  the ten: `aplicables: 10 · muertos: 10 · vivos: 0 · flaky: 0 · huecos de cobertura: ninguno`,
  exit code `0` — and put with the fifty of the run above, `60 · muertos: 55 · vivos: 5`.
- **65 of 69 die now**, and the seventh pass is the first one that measured the reader that
  learned text. Seven mutations, all dead by a test of their own module: the opening quote that
  is not skipped, so a string's body is read as code (`ao_cadena_abre_solo`); a regex literal
  read as a division, so it opens a string on its `'` and swallows the file
  (`ao_regex_es_division`); the numeric separator treated as a digit, so `1_000_000` is not a
  number (`ao_separador_no_es_digito`); the census denominator replaced by what the reader
  happened to reach (`ao_censo_sin_denominador`, killed by the one test that asserts the
  denominator is the sum of the reads and the named silences); tolerance applied to text, where
  a length difference is not a distance (`ao_texto_con_tolerancia`); the probe answering
  `typeof` again (`lo_probe_typeof`, killed by `test_el_texto_se_conserva_y_un_nombre_ausente_es_un_hueco`);
  and `lo_bool_conforma`, which left the exemption table because the producer changed. Four of
  the seven surface first at `ContratoTest.test_autotest_y_aridad`, which runs the module's own
  self-test — `_FUENTE_TEXTO` is part of the fixture the release runs — and each of the four was
  also checked against a focused test, so none of them rests on the fixture alone. Measured
  run: `aplicables: 69 · muertos: 65 · vivos: 4 · flaky: 0 · huecos de cobertura: ninguno`,
  exit code `0`.
- **68 of 72 die now**, and the eighth pass measures the third part of the census. Three
  mutants over the environment predicate, all dead by a test of `EntornoTest`: the variable
  that the receipt must name (`ao_entorno_no_se_nombra`, killed by the CLI test), the read
  found where there is only text (`ao_entorno_en_el_texto`), and the bracketed form dropped
  from the pattern (`ao_entorno_sin_corchetes`). The third one took two attempts to be a
  useful mutant: the first version broke the pattern outright and the mutant died for the
  wrong reason, so the pattern now narrows the group from `([^"']+)` to `(\d+)` and dies on
  the test that asserts both forms. Measured run: `aplicables: 72 · muertos: 68 · vivos: 4 ·
  flaky: 0 · huecos de cobertura: ninguno`, exit code `0` — with the same four declared
  survivors, so a wider reader did not quietly buy a smaller denominator.
- **75 of 79 die now**, and the tenth pass measures the declared environment. Three mutants over the
  taxonomy, all dead by a test of `TaxonomiaTest` and none by a test of another module: the
  classifier replaced by its own fallback (`ao_causa_cajon`, killed by the hand-over test), the
  longest match turned into the last match so `!==` publishes as `!` (`ao_causa_mas_corta`),
  and the inherited refusal losing its label so the anchor that only points is blamed
  (`ao_herencia_muda`). Measured run: `aplicables: 75 · muertos: 71 · vivos: 4 · flaky: 0 ·
  huecos de cobertura: ninguno`, exit code `0` — same four declared survivors, so naming nine
  constructs did not buy a smaller denominator. The run took 71 minutes because three foreign
  `pytest` processes were running on the same machine; the harness repeats every red on a fresh
  copy, which is why contention shows up as `flaky` and not as a kill.
- **The tenth pass turns the environment into a frontier.** Four mutants, all dead by a test
  of `EntornoDeclaradoTest` and none by a test of another module: the absent variable
  evaluated as an empty string (`ao_entorno_default`, killed by the repair that counts the
  three populations), the map received and thrown away (`ao_entorno_ignorado`, killed by the
  fallback test it resurrects), the census publishing an empty map (`ao_entorno_sin_publicar`,
  killed by the receipt test), and a numeric map coerced to text (`ao_entorno_numero`, killed
  by the CLI that refuses it). Measured run: `aplicables: 79 · muertos: 75 · vivos: 4 ·
  flaky: 0 · huecos de cobertura: ninguno`, exit code `0` — the same four declared survivors
  for the fourth pass running, so a declared environment did not buy a smaller denominator.
- **79 of 83 die now, and the eleventh pass measures the operators.** Four mutants over the act,
  all dead by a test of their own module and none by a test of another: Python's truth for text,
  so a deployment that exports `DRY_RUN=0` falls to the fallback (`ao_verdad_python`), `||`
  behaving as `&&` (`ao_o_logico_invertido`), the map dropped at the hop from one anchor to
  another (`ao_mapa_salto`) and a `null` key read back as an absent one (`ao_nulo_es_ausente`).
  Measured run: `aplicables: 4 · muertos: 4 · vivos: 0 · flaky: 0 · huecos de cobertura: ninguno`,
  exit code `0` — with the same four declared survivors as the four passes before it.
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

Five rules make the report trustworthy. Four were learned by getting them wrong.

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
- **The scope of a verdict is published, never implied.** A mutant that dies in the tests of the
  module it belongs to answers "does the module that owns this notice"; one that survives them and
  dies later answers a weaker and far more expensive question, and only the whole suite can ask
  it. Each row now prints which of the two decided it (`dueno` / `suite`), so the two claims are
  never read as one — and a reader who wants the old procedure has `--estricto`, which is how the
  ten mutants of `0.9.5` were shown to keep their verdict.

**Four mutants cannot be killed by any test, and that is the finding, not an omission.** Three
are guards the arithmetic makes unreachable and one is a filter the producer empties before it.
No input distinguishes them from the original, so no test can — this table was five rows until
`0.9.0`, when the fifth (a boolean filter the probe's `typeof` made unreachable) became killable
by changing the producer:

| mutant | why no input reaches it |
|---|---|
| drop the `+-0.5` clamp on the parabola vertex | with `c0` the minimum cost, `c0 <= c_menos` and `c0 <= c_mas`, hence `abs(c_menos - c_mas) <= c_menos - 2*c0 + c_mas`: the vertex is always inside `+-0.5`. The clamp documents the bound; `test_el_desplazamiento_cabe_siempre_en_media_muestra` pins the invariant instead of the guard |
| `curvatura <= 0` → `curvatura < 0` | `curvatura == 0` needs `c_menos + c_mas == 2*c0` with `c0` a minimum, i.e. a three-way tie, which exact integer sums can produce only by making the parabola flat everywhere — not with `_ssd` over distinct shifts |
| allow bands with fewer than 2 samples of overlap | the `2*max_shift + 8 > min(len)` check already refuses those inputs, so the later guard is shadowed by the earlier one from every public entry point |
| read bytecode by descriptor only on `'xb'` | measured: the interpreter opens `__pycache__` files with mode `'wb'`, so the `'xb'` arm of the filter has no producer. The observable half — that the probe does not leave bytecode behind — is pinned by `test_la_sonda_no_deja_bytecode_en_el_arbol`, which does kill the mutant that removes `-B` |

Keeping a guard that cannot fire is a choice: it states the invariant where a reader looks for
it. What is not acceptable is claiming the suite covers it. It does not, and no test can.

The table these passes built stands at **93 mutations** and is published above, in `0.9.6`: the
numbers in this section are the rounds that produced it, not its current state. One of its rows
describes a single interpreter, not both: the test named against `au_sin_B` kills that mutant only
where the interpreter writes `.pyc`, so the 3.9.6 reading counts five survivors and the 3.14.8
reading four.

## Contract

| exit code | meaning |
|---|---|
| `0` | conforming / measured and within tolerance (text: equal) |
| `1` | diverging — the receipt names the anchor, point or cause |
| `2` | not measured — never reported as conforming |
| `20` | bad invocation |

All four modules have `--self-test`, and each one runs against its own synthetic fixtures.
Three of them — `anchor_oracle`, `subpixel_probe`, `viewport_embed` — open no file and no
socket while doing it; that is measured with `sys.addaudithook`, not asserted, because the
first draft of this paragraph claimed it for all four and `live_oracle` contradicted it:
its self-test writes `fuente.ts` and `probe.mjs` into a temporary directory and runs `node`,
which is the whole point of the module. Nineteen filesystem events outside `sys.prefix`,
against zero in the other three.

The probe is not a snippet in this file, it is [`tools/audit_self_test.py`](tools/audit_self_test.py):

```bash
$ python tools/audit_self_test.py
anchor_oracle    rc=0 · 0 evento(s) de datos · AUTOTEST OK: 44 anclas de oraculo
live_oracle      rc=0 · 19 evento(s) de datos · AUTOTEST OK: 8 anclas de oraculo vivo · v24.15.0
subpixel_probe   rc=0 · 0 evento(s) de datos · AUTOTEST OK: 9 anclas de subpixel
viewport_embed   rc=0 · 0 evento(s) de datos · AUTOTEST OK: 14 anclas de encastre
$ echo $?          # 1: a module touched data I/O, which is what the table says
```

Read the number for `live_oracle` as *nonzero*, not as a constant: it counts the writes and
pipes of each `node` run the fixture performs, so it moves if the fixture does — the same
tree reports 19 today, 23 before the string fixture was added to the probe, and 23 or 24
depending on whether a bytecode cache already existed. `0` versus *nonzero* is the invariant;
the exact number is a property of the fixture, and `tests/test_audit_self_test.py` pins the
former rather than the latter.

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
