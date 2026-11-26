# A consumer that pins `@v0`

Everything else in this repository is measured with `uses: ./` — the action running inside the
tree that produces it. That proves the action works; it does not prove the tag resolves for
someone else. This directory is the harness that measures from outside, and it is kept here so
the claim can be re-run rather than believed.

## What it measured

Run [`45852973521`](https://github.com/alexisromtz-lab/v0-consumer/actions/runs/45852973521) in a
throwaway repository (`alexisromtz-lab/v0-consumer`), on `ubuntu-latest`,
`2026-11-26`, runner `node v24.22.3` at `/usr/local/bin/node` and `Python 3.14.4`:

| step | inputs | exit | evidence |
|---|---|---|---|
| positive | `check=anchor`, `backend=estatico`, `{"TASA": 0.15}` against `0.15` | `0` | `"backend": "estatico"`, `"peor_rel": 0.0` |
| negative | same, reference displaced to `0.25` | `1` | the step went red, `receipt-file` survived with `rc=1` and `causa: DIVERGE` |
| default | no `backend` declared — the five lines the README promises | `0` | `"backend": "node v24.22.3"` |

The third row is the one worth keeping: `auto` prefers the live oracle, and the stock runner
publishes `node 24.22.3`, so the default path a caller gets without reading anything was measured
green rather than assumed.

## How to re-run it

From an empty repository — the four files below go in exactly these paths:

```sh
cp -R consumers/v0/config.ts consumers/v0/ref_ok.json consumers/v0/ref_drift.json .
mkdir -p .github/workflows
cp consumers/v0/.github/workflows/consume.yml .github/workflows/
git add -A && git commit -m "consume ts-py-anchor-guard@v0"
gh repo create <you>/<name> --public --source=. --remote=origin --push
gh run watch --repo <you>/<name>
```

A green run means three things held at once: the tag resolved from outside, the aligned fixture
returned `0` on the dependency-free backend, and a displaced reference made a step fail while the
receipt it wrote stayed readable.

## A note on the citation

The run above belongs to a throwaway repository, not a product: treat its URL as a record of what
happened rather than a page anyone maintains. The reproducible artifact is this directory —
identical bytes to what ran, verified with `shasum -a 256` at the time of the copy.
