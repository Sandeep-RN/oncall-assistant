# Project brief: oncall-assistant

The single source of facts about this project for anything written about it
somewhere else: a resume, a portfolio page, a profile, a post, an interview
answer. **Last verified: 2026-11-23** (milestone M1 closed that day).

## How to use this file

For a person, or for an AI assistant working in another project:

1. **Use only the facts and numbers in this file.** Each number has a source.
   Do not round up, combine numbers, or add a number that is not here.
2. **This is a personal project.** The README calls it a "mock customer
   engagement": the "customer" is the platform team of
   [oci-k8s-gitops-demo](https://github.com/Sandeep-RN/oci-k8s-gitops-demo),
   role-played by the author. Never describe it as work for a real customer
   or an employer, and never as production experience.
3. **Only milestone M1 is done.** Do not claim anything from M2 (eval scores
   in CI, SLOs, a dashboard, alerts), M3 (the live-state agent) or M4 under
   any bullet until that milestone closes. They are listed in "Not done".
4. **Prefer the ready-made text** in "Ready to use" to writing new claims.
5. **Check the date above.** "What changes next" at the end says which lines
   to update when M2 to M4 close. If this file is more than a month old,
   read the [README](README.md) first.
6. **Ask the owner** for anything that is missing. Do not fill a gap by
   guessing.

## Summary

**One line.** An on-call assistant that answers questions about a real
platform's runbooks and decision records with cited answers, or says "I don't
know", running for free on that platform's own Kubernetes node.

**50 words.** A retrieval-augmented assistant (FastAPI, PostgreSQL with
pgvector, a local ONNX embedding model) that answers on-call questions from
the docs of a Kubernetes platform. Every answer cites its source
passage, or the assistant says "I don't know". It is delivered through the
platform's GitOps repo and runs inside a hard 1 GiB memory cap.

**150 words.** A personal project, set up as a mock customer engagement: the
"customer" is the platform team of my own Kubernetes project, and its
documents are real. An on-call engineer asks a question in plain language and
gets a short answer that cites the exact runbook or decision record, or "I
don't know". Retrieval uses a local embedding model on ONNX Runtime and
pgvector; one OpenAI-compatible call to gpt-oss-120b on Groq's free tier
writes the answer, and the app turns any answer without a valid citation into
a refusal. The assistant ships the way the platform's own service does: an arm64 image
scanned by Trivy, pushed to GHCR, and a tag-bump pull request that ArgoCD
deploys. It shares one free node with a live site, inside a 1 GiB cap, with a
daily token budget, saved answers for when the free tier runs out, and a
read-only database role.

## Status

Live at <https://ask.sandeeprn.in> since 2026-11-22
([demo #195](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/issues/195)).
Milestone **M1 MVP closed on 2026-11-23** (12 issues closed, 0 open; its
target date was 2026-12-09). M2 "Evals and SLOs" is open (due 2026-12-23),
with [#14](https://github.com/Sandeep-RN/oncall-assistant/issues/14) (grow the
eval set) still open. M3 and M4 are planned in the
[customer brief](docs/customer-brief.md) but not started.

## Facts

| | |
|---|---|
| Name | oncall-assistant |
| Kind | Personal project, set up as a mock customer engagement (the author role-plays the customer). One person: design, decisions, build, operation |
| Period | From 2026-11-21 (first commit); M1 done 2026-11-23 |
| Repo (public) | <https://github.com/Sandeep-RN/oncall-assistant>; its manifests are in the platform's [gitops repo](https://github.com/Sandeep-RN/oci-k8s-gitops-demo-gitops) (`apps/oncall-assistant`) |
| Live URL | <https://ask.sandeeprn.in> (a one-file question page at `/`, `POST /ask`, `GET /saved`, `/healthz`; the framework's `/docs` is off, [#47](https://github.com/Sandeep-RN/oncall-assistant/issues/47)) |
| What it answers from | The Markdown docs of the three platform repos: 50 documents, 297 passages at the current pin ([PR #51](https://github.com/Sandeep-RN/oncall-assistant/pull/51), `corpus-lock.json`) |
| Model | gpt-oss-120b. In the cluster through **Groq's free tier**; development and evals use a separate key (KodeKey) that stays on the laptop and in CI ([ADR 0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md), [CLAUDE.md](CLAUDE.md)) |
| Embeddings | `BAAI/bge-small-en-v1.5`, fp32 ONNX, 384 dimensions, run locally; no embedding API ([ADR 0001](docs/adr/0001-local-onnx-embeddings-on-python-314.md)) |
| Hosting | A second tenant on the platform's single k3s node, inside a ResourceQuota of 1 GiB of memory limits and 1 CPU ([platform ADR 0025](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/blob/main/docs/adr/0025-second-application-on-the-node-inside-a-hard-cap.md)). Designed; its verification issue, [demo #196](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/issues/196), is still open |
| Size of the work | On 2026-11-23: 21 merged pull requests in this repo (`gh pr list`), 3 app ADRs, 261 tests passing against a real Postgres with none skipped ([PR #51](https://github.com/Sandeep-RN/oncall-assistant/pull/51)) |
| Cost | No infrastructure cost: it runs on the platform's existing free node and Groq's free tier (README, customer brief "Costs nothing to run") |
| Built with | An AI coding assistant, Claude Code. See "How it was built" |

**Tools, by layer** (use these exact names for skills and tags):

| Layer | Tools |
|---|---|
| Application | Python 3.14, FastAPI, Starlette, uvicorn, httpx, pytest, ruff |
| Retrieval | ONNX Runtime, Hugging Face `tokenizers`, NumPy, `BAAI/bge-small-en-v1.5`, PostgreSQL with pgvector, psycopg, psycopg-pool |
| LLM | gpt-oss-120b on Groq (free tier) through the OpenAI-compatible chat completions API, no SDK; KodeKey for development and evals |
| CI/CD | GitHub Actions, Docker Buildx (multi-arch: amd64 and arm64), Trivy, GHCR, gitleaks, pre-commit |
| Platform (gitops repo) | k3s, ArgoCD (own AppProject), Kustomize, Sealed Secrets, Traefik, cert-manager, Let's Encrypt, external-dns, ResourceQuota, LimitRange, PriorityClass, CronJob |
| Practice | ADRs, issue-first milestones, an eval set written before the answering code, test-first, a customer brief with success criteria |

## Results

Every row has a source.

| What was tested | Result | Source |
|---|---|---|
| Retrieval on the fixed question set | 25 of 28 answerable questions (89%) had the right passage in the top 5; target 90%. Same score and same three misses after the corpus pin moved | [PR #13](https://github.com/Sandeep-RN/oncall-assistant/pull/13), [PR #51](https://github.com/Sandeep-RN/oncall-assistant/pull/51) |
| Can a similarity score decide "I don't know"? | No: best-passage scores were 0.62 to 0.85 for answerable questions and 0.62 to 0.78 for unanswerable ones; the ranges overlap | [ADR 0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md), [PR #13](https://github.com/Sandeep-RN/oncall-assistant/pull/13) |
| Live smoke check of cited answers | Both providers, 5 eval questions: 3 answered with the expected document cited, 2 refused (10 of 10). Five questions are a smoke check, not a result | [PR #16](https://github.com/Sandeep-RN/oncall-assistant/pull/16) |
| Cost of one answer | 2.0 to 2.5K prompt tokens and 25 to 240 completion tokens, so about 3 live answers a minute on Groq's 8K-tokens-a-minute free tier; generation 0.5 to 1.3 s, retrieval 0.1 to 0.2 s (5 questions) | [ADR 0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md) |
| Indexing memory, container test on x86 | Before the batching fix: OOM-killed at a 384Mi limit, 435 MiB peak without a limit. After (fixed lengths plus a token budget): 247 MiB. Full index of 285 passages, laptop Docker | [ADR 0001](docs/adr/0001-local-onnx-embeddings-on-python-314.md), [#19](https://github.com/Sandeep-RN/oncall-assistant/issues/19) |
| Memory on the arm64 node, one run | First index run on the node (286 passages, 7 min 4 s): index Job working set 271 MiB of 384 MiB, app 247 MiB of 320 MiB, Postgres 34 MiB of 256 MiB; no restarts, no OOM kills | [demo #196](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/issues/196) (comment of 2026-11-22) |
| Delivery path | The first real CI run pushed a tag-bump pull request into the gitops repo, which auto-merged (gitops #79); ArgoCD rolls each bump | [#7](https://github.com/Sandeep-RN/oncall-assistant/issues/7), [#32](https://github.com/Sandeep-RN/oncall-assistant/issues/32) |
| Demo token revoke | A token added or revoked by a merge works with no restart, 1 to 5 minutes after the merge (ArgoCD sync, then the mount refresh in 3 to 16 s); a revoked token then got a 401. Four merges | [ADR 0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md), [demo #218](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/issues/218) |
| Least-privilege database role | The app role can write one table only, and only inside an explicit read-write transaction; a CI step tries the permissions on a real Postgres (26 checks) | [demo #207](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/issues/207), [#33](https://github.com/Sandeep-RN/oncall-assistant/issues/33) |
| Saved answers reviewed by a person | Of 5 model-drafted saved answers, 2 had a sentence their own valid citation did not support; both were trimmed by hand | [ADR 0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md), [#40](https://github.com/Sandeep-RN/oncall-assistant/issues/40) |

How to quote these honestly:

- **"Mock customer engagement" means a personal project.** The customer is
  role-played by the author. The documents and the platform are real.
- **The 89% may be quoted only with its limits**, and never as an answer
  quality score. The 39 questions (28 answerable, 11 unanswerable) were all
  drafted by Claude from the documents and accepted by the owner, so they are
  easier than real on-call questions, and 89% is below the 90% target. Say:
  "89% top-5 retrieval (25 of 28) on a first, AI-drafted 39-question set,
  below its 90% target". Never "89% accuracy", never "89% of answers are
  correct", and never drop "below its 90% target".
- **Answer quality is not measured.** Whether each claim is supported by its
  citation is the M2 answer eval. The 10 of 10 is a five-question smoke check.
- **Keep the memory numbers apart.** 435 MiB and 247 MiB are a container test
  on x86 on a laptop. 271 MiB is the index Job's working set on the arm64
  node, from one run. 247 MiB is also the app pod's peak on the node: a
  different pod and a different measurement. The node figures belong to demo
  #196, which is still open; say "measured once on the node", not "verified".
  Do not write "cut memory from 435 to 271 MiB".
- **ADR 0025 hosting is designed, not verified.** Say "designed to run inside
  a hard 1 GiB cap"; do not claim it is proven until demo #196 closes.
- **The model is gpt-oss-120b on Groq's free tier** in the cluster. Do not
  name any other provider or model for the live site.
- **There is no SLO, dashboard or alert yet.** The 99% availability and 8 s
  latency targets in the customer brief are targets for M2, not results.

## Decisions and why

| Decision | Why | ADR |
|---|---|---|
| Local ONNX embeddings (bge-small), no PyTorch, Python 3.14 | No embedding API and no cost; PyTorch does not fit the memory budget; ONNX Runtime had no Python 3.15 wheels | [0001](docs/adr/0001-local-onnx-embeddings-on-python-314.md) |
| Refusal comes from the model citing or not, checked by the app; not from a score | Similarity ranges of answerable and unanswerable questions overlap; an answer with no valid citation becomes a refusal | [0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md) |
| One plain OpenAI-compatible call, explicit timeouts, no retries | A retry breaks the 8 s latency target and a 429 means wait | [0002](docs/adr/0002-cite-or-refuse-one-openai-compatible-call.md) |
| Capacity limits answer 200 with a labelled saved answer; faults stay 503 | If every failure fell back to a saved answer, the availability target could never burn | [0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md) |
| Saved answers matched by exact text, never by similarity | A wrong saved answer shown with confidence is worse than none | [0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md) |
| A daily token budget in Postgres: one writable table, read-only default kept on | It must survive restarts; widening the role by one table keeps the lock on the index | [0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md) |
| Demo tokens stored only as SHA-256 hashes, one file per token | Add or revoke by a merge, with no restart and no re-sealing of other tokens | [0003](docs/adr/0003-saved-answers-on-capacity-limits-and-a-daily-budget.md) |
| A second tenant on the node inside a hard cap, guardrails owned by the platform | There is no second free VM; the cap, not priority, protects the live site. Designed; verification is demo #196 | [platform 0025](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/blob/main/docs/adr/0025-second-application-on-the-node-inside-a-hard-cap.md) |

All app ADRs: [docs/adr/README.md](docs/adr/README.md).

## Problems found and fixed

Each one happened. The `post-idea` issue has the detail.

| Problem | Cause | Fix |
|---|---|---|
| The index Job was OOM-killed at 384Mi ([#19](https://github.com/Sandeep-RN/oncall-assistant/issues/19)) | Padding each batch to its longest text gave ONNX Runtime a new input shape almost every batch | Fixed input lengths plus a token budget: 247 MiB in the same x86 container test |
| No similarity threshold could decide "I don't know" ([#20](https://github.com/Sandeep-RN/oncall-assistant/issues/20)) | The score ranges overlap | The model cites or refuses; the app checks the citations |
| pgvector needs a superuser, and a superuser can run shell commands ([#21](https://github.com/Sandeep-RN/oncall-assistant/issues/21)) | pgvector is not a trusted extension | Three roles: admin creates the extension, the indexer is not a superuser, the app is read-only |
| The repo could not use Python 3.15 ([#22](https://github.com/Sandeep-RN/oncall-assistant/issues/22)) | ONNX Runtime had no 3.15 wheels | Python 3.14, moved on purpose later |
| Two correct answers became refusals ([#23](https://github.com/Sandeep-RN/oncall-assistant/issues/23)) | The model cited with fullwidth brackets, which the parser did not read | The parser accepts both styles; the two real replies are tests |
| The first real question got a 500 ([#24](https://github.com/Sandeep-RN/oncall-assistant/issues/24), [#18](https://github.com/Sandeep-RN/oncall-assistant/issues/18)) | A database error from the search was not caught | A clean 503 `index_unavailable` |
| A down database still made visitors wait before the 503 ([#31](https://github.com/Sandeep-RN/oncall-assistant/issues/31)) | The connection pool had no timeout | A 3 s pool timeout (`app/main.py`) |
| A log line passed its test and never appeared in the pod ([#29](https://github.com/Sandeep-RN/oncall-assistant/issues/29)) | The app never configured logging; `caplog` hid it | Logging set on the app's own logger, tested in a fresh interpreter |
| A telemetry warning printed before the opt-out could run ([#30](https://github.com/Sandeep-RN/oncall-assistant/issues/30)) | It fires at import | Measured with `strace`: no network calls; CI embeds with `--network none` |
| CI was green and had never been allowed to push ([#32](https://github.com/Sandeep-RN/oncall-assistant/issues/32)) | The token was read-only; checkout passed because the repo is public | Contents and Pull requests set to write; the re-run opened the bump |
| An answer named a file with invisible hyphens ([#39](https://github.com/Sandeep-RN/oncall-assistant/issues/39)) | The model wrote non-breaking hyphens | Lookalike characters are replaced; a test checks the shipped file |
| Answers with valid citations still made unsupported claims ([#40](https://github.com/Sandeep-RN/oncall-assistant/issues/40)) | A citation check proves a citation exists, not that it supports the claim | A person reads each saved answer beside its passages |
| A public API console nobody wrote ([#49](https://github.com/Sandeep-RN/oncall-assistant/issues/49)) | The framework's default `/docs`, outside the page's security policy | Off unless an environment variable is set to `1` |

Design decisions logged as post ideas, not bugs: the availability split
([#34](https://github.com/Sandeep-RN/oncall-assistant/issues/34)), exact-match
saved answers ([#35](https://github.com/Sandeep-RN/oncall-assistant/issues/35)),
one writable table ([#33](https://github.com/Sandeep-RN/oncall-assistant/issues/33)),
a real-browser check of the page's security policy (it passed,
[#37](https://github.com/Sandeep-RN/oncall-assistant/issues/37)), and two
gotchas from the revoke drill ([#52](https://github.com/Sandeep-RN/oncall-assistant/issues/52),
[#53](https://github.com/Sandeep-RN/oncall-assistant/issues/53)).

## Not done

Do not claim any of these.

- **M2 Evals and SLOs:** retrieval score as a CI gate, the answer eval
  (are claims supported by their citations, refusal rate), a question set of
  about 100 with the owner's own questions
  ([#14](https://github.com/Sandeep-RN/oncall-assistant/issues/14)), the 99%
  availability and 8 s latency SLOs, a dashboard and alerts.
- **M3 Agent:** read-only live-state tools (alerts, application health, pod
  events) behind the token, and the NetworkPolicy that limits egress.
- **M4 Reliability and handover:** logs, a handover runbook, a demo video, a
  write-up.
- **Verification of the hosting design** (ADR 0025): demo #196 is open; its
  7-day item (the link shortener's SLO unaffected) is due about 2026-11-29.
- **Answer quality.** Not measured beyond a five-question smoke check.
- **High availability.** One replica on one node; each deploy is a short gap.
- **Backups of the index.** The database is a cache rebuilt from public docs,
  by design.

## How it was built

Built from 2026-11-21 with an AI coding assistant (Claude Code). The
assistant wrote much of the code, tests and CI, drafted the 39 eval questions,
and wrote first drafts of the docs and ADRs. The owner made the decisions,
accepted the questions, read every saved answer beside its passages, ran or
supervised every live check, and reviewed and merged the pull requests. The
[CLAUDE.md](CLAUDE.md) file is the instructions given to the assistant.

When this project is described anywhere, say this plainly if asked. The skill
shown is deciding, measuring and verifying, not typing code.

## Ready to use

### Resume bullets

Pick three to five. Do not merge two bullets into one bigger claim.

- Built a retrieval-augmented on-call assistant (FastAPI, PostgreSQL with
  pgvector, local ONNX embeddings) that answers from a platform's runbooks and
  decision records with cited answers, or says "I don't know" when no valid
  citation backs the answer.
- Delivered it through the platform's GitOps repo like any other service: a
  multi-arch (arm64) image scanned by Trivy before push, published to GHCR,
  and a tag-bump pull request that ArgoCD deploys.
- Fixed an out-of-memory kill in the embedding job by changing the batching to
  a few fixed input shapes with a token budget: in a container test, peak
  memory fell from 435 MiB (OOM-killed at a 384Mi limit) to 247 MiB.
- Kept a free-tier LLM demo honest under load: a daily token budget in
  Postgres, labelled saved answers when capacity runs out, and real faults
  still returned as errors, kept apart from capacity limits.
- Gave the app a least-privilege database role: read-only by default, with one
  writable table for the token budget, checked in CI against a real Postgres.

### Portfolio card

```yaml
title: "On-call Assistant: Cited Answers over Runbooks (RAG)"
description: "A personal project: an assistant that answers on-call questions from a real platform's runbooks and decision records with cited answers or 'I don't know', running on that platform's free Kubernetes node inside a hard 1 GiB cap, delivered by GitOps."
tags: ["RAG", "Python", "FastAPI", "pgvector", "ONNX Runtime", "LLM", "Kubernetes", "ArgoCD", "GitHub Actions"]
status: "in progress"   # M1 done 2026-11-23; M2 to M4 open
date: "2026-11"
github: "https://github.com/Sandeep-RN/oncall-assistant"
live: "https://ask.sandeeprn.in"
```

### Short texts

**Two sentences.** I built an on-call assistant that answers questions about
my Kubernetes platform's runbooks and decision records, citing the exact
section or saying "I don't know". It runs for free on that platform's own
node, inside a hard memory cap, and ships through the same GitOps pipeline as
the platform's service.

**Profile line.** On-call RAG assistant: cited answers or "I don't know" over
real runbooks, on a free k3s node via ArgoCD. Live at ask.sandeeprn.in.

**Project description (about 100 words).** A personal project, set up as a
mock customer engagement with my own platform team as the customer. The
assistant answers on-call questions from the public docs of my Kubernetes
platform. A local embedding model on ONNX Runtime and pgvector find the top
five passages, gpt-oss-120b on Groq's free tier writes a short answer, and the
app turns any answer without a valid citation into "I don't know". It ships
as an arm64 image through Trivy, GHCR and a tag-bump pull request to ArgoCD,
and shares one free node with a live site inside a 1 GiB cap. Evals and SLOs
are the next milestone.

### Diagram in plain ASCII

```
  Visitor --HTTPS--> Traefik (rate limit) --> app (FastAPI, ONNX embeddings)
                                                 |            |
                                     top 5 passages        one call
                                                 v            v
                                  Postgres + pgvector     Groq free tier
                                  (index, token ledger)   (gpt-oss-120b)
                                                 ^
                       nightly index CronJob ----+---- public docs of the
                                                       three platform repos

  merge --> GitHub Actions (test, build arm64, Trivy) --> GHCR
                 |
                 +--> tag-bump PR in the gitops repo --> ArgoCD --> the node
```

## Links

- Live: <https://ask.sandeeprn.in>
- Start here: [README](README.md), then the [customer brief](docs/customer-brief.md)
- Decisions: [docs/adr/README.md](docs/adr/README.md) and platform
  [ADR 0025](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/blob/main/docs/adr/0025-second-application-on-the-node-inside-a-hard-cap.md)
- Milestones: <https://github.com/Sandeep-RN/oncall-assistant/milestones>
- Write-ups of the problems, as issues: [label `post-idea`](https://github.com/Sandeep-RN/oncall-assistant/issues?q=label%3Apost-idea)
- The platform's own brief: [oci-k8s-gitops-demo PROJECT_BRIEF.md](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/blob/main/PROJECT_BRIEF.md)

## What changes next

Update this file, then everything written from it, when these close:

| When | Change |
|---|---|
| Demo #196 closes (7-day item, about 2026-11-29) | "Facts" Hosting and "Decisions": ADR 0025 may be called verified, with the results posted there. Remove its line from "Not done" and the "designed, not verified" quoting rule |
| M2 Evals and SLOs closes (due 2026-12-23) | "Results": the grown eval set's retrieval score and the answer eval; the 7-day availability and latency figures as measured. Rewrite the 89% quoting rule for the new set. A bullet for the CI eval gate, SLOs and alerts may be added. Remove M2 from "Not done" |
| M3 Agent closes (target 2027-01-06) | "Facts" and a bullet for the read-only live-state tools and the egress NetworkPolicy. Remove M3 from "Not done" |
| M4 closes (about 2027-01-20) | Links to the demo video and the write-up; the portfolio card's `status` becomes `"done"` |
