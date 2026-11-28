# oncall-assistant

An on-call assistant for a platform team: ask a question in plain language and
get a short answer that cites the exact runbook or decision record it came
from, or "I don't know" when the documents do not cover it.

This is a **mock customer engagement**. The "customer" is the platform team of
[oci-k8s-gitops-demo](https://github.com/Sandeep-RN/oci-k8s-gitops-demo),
role-played by the author; its documents and its single-node k3s platform are
real and public. The assistant is deployed onto that platform through its
GitOps repository, inside a hard resource cap, at no infrastructure cost.

**Status (2026-11-23):** milestone M1 MVP is done (2026-11-23, target was 2026-12-09); next is M2,
evals and SLOs. The assistant is
deployed at https://ask.sandeeprn.in through the platform's GitOps repository. Done: the corpus,
local embeddings and the pgvector index ([ADR 0001](docs/adr/0001-local-onnx-embeddings-on-python-314.md)),
`POST /ask` with cited answers or a refusal ([ADR 0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md)),
the retrieval eval (39 questions, 89% right passage in the top 5), the container image on GHCR,
a one-file question page at `/` that shows every failure the edge or the app can send, and saved
answers when the free model tier is at its limit, and a daily token budget with demo tokens that lift
the public share ([ADR 0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md)).

- [Customer brief](docs/customer-brief.md): problem, users, constraints, success criteria, delivery
- [Project brief](PROJECT_BRIEF.md): the facts and numbers, with sources, for anything written about this project
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
run is in progress. Full run on the current corpus, in an x86 container test on a laptop: peak
memory 247 MiB ([ADR 0001](docs/adr/0001-local-onnx-embeddings-on-python-314.md)). On the arm64 node, held at its CPU
limit, the first full run took 7 min 4 s with a working set of 271 MiB, measured once
([demo #196](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/issues/196)).

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
passage from the right document and section among the passages the model would get? That is the
top 5, plus up to 3 more sections when 4 of the 5 share a document
([ADR 0004](docs/adr/0004-same-document-expansion-of-retrieved-passages.md)); `--no-same-document`
scores the plain top 5. It also prints the best-passage score
of every question, because a refusal threshold has to be chosen from those ranges. Needs the index
(`python -m app.index`).

## Ask

`POST /ask` with `{"question": "..."}` (3 to 500 characters) answers from the top 5 passages (up to 8, ADR 0004),
citing them as `[n]`, or says "I don't know" ([ADR 0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md)):

| Response | Meaning |
|---|---|
| 200 `kind: live` | an answer with `citations` (URL at the pinned commit, repo, path, section) |
| 200 `kind: refusal` | the documents do not answer it (`reason: model`), or the model cited nothing (`uncited`) |
| 401 `kind: unauthorized` | the `X-Demo-Token` header holds a token that matches none (never treated as a visitor) |
| 200 `kind: saved` | a capacity limit (the daily budget is spent, the provider's 429, or two answers already running): the `saved` answers, and `match` says which one is the visitor's own question, if any ([ADR 0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md)) |
| 503 `kind: unavailable` | a fault: timeout, provider error, bad reply, database unavailable, or not configured; `notice` says which |

Every live answer carries `timings_ms` and `tokens`. Logs keep a hash and the length of the question,
never its text. `GET /saved` lists the saved answers (no database or key needed) and `GET /` is the
question page. FastAPI's `/docs`, `/redoc` and `/openapi.json` are not served; set
`ONCALL_ENABLE_API_DOCS=1` to turn them on locally (issue #47: `/docs` loads script from a CDN,
outside the page's CSP).

## Daily budget and demo tokens

Groq's free tier for `openai/gpt-oss-120b` allows, for everyone together (read in the Groq console
on 2026-11-28): 30 requests a minute, 1K requests a day, **8K tokens a minute** and 200K tokens a
day. An answer takes about 2 to 3K tokens, so the per-minute token limit is the first one reached:
about 3 answers a minute, 2 when the same-document rule adds passages (ADR 0004). A 429 from it
gives the saved answers. For the daily limit the assistant
counts tokens (not calls) in Postgres, in one small table, `llm_usage` ([ADR 0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md)).
Visitors may use `PUBLIC_SHARE_PCT` (70%) of `DAILY_TOKENS_TOTAL`; when it is spent they get the
saved answers, and the check comes before the embedding, so a spent budget costs nothing. A **demo
token** (`X-Demo-Token`, or the "I have a demo token" box on the page) lifts the public share for its
holder: it may use what is left of the day's total. It does not lift the provider's own per-minute
limit or the edge's per-client limit. The day is a UTC day (Groq documents no daily reset time).

The app role is read-only; it writes only that table, and only inside an explicit
`SET TRANSACTION READ WRITE` (the platform repo grants it, and runs the same rules on a real Postgres
in CI). The cluster holds only the SHA-256 of each token, one file per token in `DEMO_TOKEN_DIR`;
a token added or revoked works with no restart, 1 to 5 minutes after the merge (ArgoCD syncs, then
the kubelet refreshes the mount within 3 to 16 s; measured in demo #218). A broken ledger never stops
an answer (it is logged as `budget_error`); a database that is down fails at once with a 503.

## Saved answers

Five pre-written answers in `app/saved/answers.json`, shown, clearly labelled, when the free model
tier is at its limit. They are drafted by the real pipeline over the pinned corpus, then read by a
person next to the passages they cite; the file's `note` says what was trimmed. Rebuild after the
corpus pin moves (a test fails until you do), then re-review the diff:

```bash
PGHOST=localhost PGPORT=5433 PGUSER=postgres PGDATABASE=postgres \
  .venv/Scripts/python -m app.index --lock corpus-lock.json   # the pinned corpus, not each repo's head
LLM_PROVIDER=kodekey PGHOST=localhost PGPORT=5433 PGUSER=postgres PGDATABASE=postgres \
  .venv/Scripts/python -m app.saved.build
```

```bash
# The development key from .env (git-ignored), laptop only; the cluster uses Groq.
set -a; . ./.env; set +a
LLM_PROVIDER=kodekey PGHOST=localhost PGPORT=5433 PGUSER=postgres PGDATABASE=postgres \
  .venv/Scripts/python -m app.answer "How do I roll back a bad deploy?"
```
