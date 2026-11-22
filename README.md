# oncall-assistant

An on-call assistant for a platform team: ask a question in plain language and
get a short answer that cites the exact runbook or decision record it came
from, or "I don't know" when the documents do not cover it.

This is a **mock customer engagement**. The "customer" is the platform team of
[oci-k8s-gitops-demo](https://github.com/Sandeep-RN/oci-k8s-gitops-demo),
role-played by the author; its documents and its single-node k3s platform are
real and public. The assistant is deployed onto that platform through its
GitOps repository, inside a hard resource cap, at no infrastructure cost.

**Status (2026-11-22):** milestone M1 (target 2026-12-09) is in progress. The assistant is
deployed at https://ask.sandeeprn.in through the platform's GitOps repository. Done: the corpus,
local embeddings and the pgvector index ([ADR 0001](docs/adr/0001-local-onnx-embeddings-on-python-314.md)),
`POST /ask` with cited answers or a refusal ([ADR 0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md)),
the retrieval eval (39 questions, 89% right passage in the top 5), the container image on GHCR,
and a one-file question page at `/` that shows every failure the edge or the app can send.
Next (#6): saved answers when the free model tier is busy, the daily budget and the demo token.

- [Customer brief](docs/customer-brief.md): problem, users, constraints, success criteria, delivery
- [Glossary](GLOSSARY.md): the terms used in this repo and its issues
- [Issues and milestones](https://github.com/Sandeep-RN/oncall-assistant/milestones): app work
- [Platform side](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/milestone/6): ADR 0025 and the gitops manifests

## Develop

Python **3.14** (not 3.15: ONNX Runtime has no 3.15 wheels yet, [ADR 0001](docs/adr/0001-local-onnx-embeddings-on-python-314.md)).

```bash
py -3.14 -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux/macOS: python3.14, .venv/bin/
.venv/Scripts/python -m app.embed.download        # the pinned model, about 130 MB, sha256 checked; once
docker compose up -d db                           # Postgres with pgvector on 127.0.0.1:5433
PGHOST=localhost PGPORT=5433 PGUSER=postgres PGDATABASE=postgres .venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
pip install pre-commit && pre-commit install      # gitleaks runs before every commit
```

Without the database or the model, those tests skip locally; CI provides both and fails on any skip.
Rules for contributors and agents: [CLAUDE.md](CLAUDE.md).

## Corpus

The assistant answers from the Markdown files of the three platform repos
(`app/corpus/sources.py` lists them; agent-instruction files are left out).

```bash
.venv/Scripts/python -m app.corpus                  # uses the commits pinned in corpus-lock.json
.venv/Scripts/python -m app.corpus --update-lock    # pin each repo's current head first
```

Each file is split at headings (levels 1 to 3) into passages of about 40 to 350 words. Code blocks
and tables are never cut. Every passage carries its repo, path, heading path, a permalink to the
heading at the pinned commit (the citation link) and the hash of its file. Output: `data/corpus.jsonl`
(git-ignored).

## Index

```bash
PGHOST=localhost PGPORT=5433 PGUSER=postgres PGDATABASE=postgres .venv/Scripts/python -m app.index
```

One run fetches each repo's current head (or `--lock corpus-lock.json` for the pinned commits),
embeds only new or changed files with the local model and writes them to Postgres with pgvector,
in one transaction under an advisory lock. Exit codes: 0 done, 1 a problem to look at, 2 another
run is in progress. Full run on the current corpus: about 2 minutes, peak memory 247 MiB; a run
with nothing changed: about 3 seconds ([ADR 0001](docs/adr/0001-local-onnx-embeddings-on-python-314.md)).

## Evals

`evals/questions.jsonl` is the fixed question set: answerable questions with the document (and
section) that holds the answer, and unanswerable ones the documents must not be able to answer.
Format and validation: `app/evals/questions.py`.

```bash
PGHOST=localhost PGPORT=5433 PGUSER=postgres PGDATABASE=postgres .venv/Scripts/python -m app.evals
.venv/Scripts/python -m app.evals --min-recall 0.9      # exit 1 below the target (the M2 CI gate)
```

The set starts with 39 questions (28 answerable, 11 unanswerable) drafted by Claude from the
documents and accepted by the owner. They are easier than real on-call questions, so a good score
here is flattering. The set only grows: new questions, especially the owner's own, are added with
their `author`. Rules: a question is never edited to make it pass; it is changed only when its
expected source is wrong, with the reason in the pull request. Three labels were widened after the
first run (A09, A13, A24) once the other passages were checked to hold the answer too.

This scores retrieval only, with no model calls and no cost: for each answerable question, is a
passage from the right document and section among the top 5? It also prints the best-passage score
of every question, because a refusal threshold has to be chosen from those ranges. Needs the index
(`python -m app.index`).

## Ask

`POST /ask` with `{"question": "..."}` (3 to 500 characters) answers from the top 5 passages,
citing them as `[n]`, or says "I don't know" ([ADR 0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md)):

| Response | Meaning |
|---|---|
| 200 `kind: live` | an answer with `citations` (URL at the pinned commit, repo, path, section) |
| 200 `kind: refusal` | the documents do not answer it (`reason: model`), or the model cited nothing (`uncited`) |
| 503 `kind: unavailable` | provider rate limit, timeout or error, too many questions at once, or not configured; `notice` says which |

Every response carries `timings_ms` and `tokens`. Logs keep a hash and the length of the question,
never its text.

```bash
# The development key from .env (git-ignored), laptop only; the cluster uses Groq.
set -a; . ./.env; set +a
LLM_PROVIDER=kodekey PGHOST=localhost PGPORT=5433 PGUSER=postgres PGDATABASE=postgres \
  .venv/Scripts/python -m app.answer "How do I roll back a bad deploy?"
```
