# 0003. Saved answers when the free tier is at its limit, and a daily budget kept in Postgres

Status: Accepted (2026-11-22). Replaces one part of [ADR 0002](0002-cite-or-refuse-one-openai-compatible-call.md):
a 429 or a busy server no longer answers 503. Points 5 to 7 are decided here and built in PR C of
issue #6; points 1 to 4 are built in PR B.

## Context
- The public demo runs on Groq's free tier: about 3 live answers a minute and 200K tokens a day
  (about 90 answers) for everyone together. That limit will be reached on a good day.
- The customer brief promises 99% of questions get a good response, and says a clearly labelled
  saved answer counts as good. If every failure fell back to a saved answer, every failure would
  count as good and the target could never burn: a broken service would look healthy.
- Similarity scores cannot decide when the documents do not cover a question (ADR 0002), so they
  should not decide which saved answer fits a question either.
- The app's database role is read-only by design (platform ADR 0025, `roles.sql`). A budget that
  survives a restart needs one place the app may write, and every merge restarts the pod.

## Decision
1. **Capacity is not a fault.** When the free tier is doing what it was always going to do (the
   daily budget is spent, the provider answers 429, or two answers are already running), `POST /ask`
   answers **200** with `kind: "saved"`. Real faults stay **503** exactly as in ADR 0002: timeout,
   provider error, bad reply, database unavailable, not configured. The availability target counts
   by `kind`: live, refusal and saved are good, unavailable is bad. The share of saved answers is
   shown next to it, so a day of degradation is visible even when the target is green.
2. **Five saved answers, in the image.** `app/saved/answers.json`, so they work while Postgres is
   down. They are made by `python -m app.saved.build`, which asks the real pipeline (retrieval,
   model, citation check) over the corpus pinned in `corpus-lock.json` (the nightly index follows
   each repo's head instead), and refuses anything that is not a live answer with a citation.
   Characters that only look like ASCII (non-breaking hyphens, curly quotes) are replaced, because
   a model wrote a file path with them and it would not survive a paste into a shell. Citations are
   commit-pinned links to that pin. The output is a draft: the author reads each answer next to the
   passages it cites in the pull request, and a sentence the passage does not support is trimmed
   by hand (two of five were on 2026-11-22; the file says so). The ADR 0002 check only proves that
   a citation exists, not that it supports the claim. A test fails when a saved citation is not pinned to the commit in `corpus-lock.json`,
   so moving the pin forces a rebuild and a new review (CI cannot fetch the corpus, so it cannot
   check that the text still says the same). The questions: roll back a bad deploy, revoke a link-creation token, point-in-time
   restore, the platform's biggest availability limit, the assistant's memory cap.
3. **Exact match, never similarity.** A visitor's question is lowercased and stripped of spaces and
   punctuation; it matches a saved question only if equal. The response always carries the notice
   and all five saved answers, and says which one matched, if any. A wrong saved answer shown with
   confidence is worse than none, and question-to-question similarity has not been measured.
4. **The page** shows a saved answer with the label "Saved answer, written earlier, not generated
   for your question". `GET /saved` lists them, so the page can offer them after a 503 too.
5. **Daily budget (PR C).** Counted in tokens (prompt plus completion from the provider's `usage`),
   because tokens, not requests, run out first. The public share is 70% of 200K; the rest is for
   demo-token holders. Both numbers are settings. The check comes before the embedding, so a spent
   budget costs nothing. The count is added after the call, so a few answers can overshoot; the
   provider's own 429 is the hard stop. The day is a UTC day unless the provider's docs say
   otherwise (to be checked before PR C). If the counter cannot be read or written, the answer goes
   ahead and the error is logged.
6. **One writable table (PR C).** `llm_usage (day, who, tokens, calls)`, created by the role Job;
   the app role gets `SELECT, INSERT, UPDATE` on that table only. The passages stay read-only, and
   the role's read-only default stays on: the app writes only inside an explicit
   `SET TRANSACTION READ WRITE`, so any other write path still fails. Rejected: a separate role
   (the same process would hold both passwords) and a counter in memory (every deploy would hand
   out a fresh day's budget).
7. **Demo token (PR C).** A request header `X-Demo-Token`. The cluster holds only the SHA-256 of
   each token, with a name (a Secret). The server hashes the presented token and compares in
   constant time; plain SHA-256 is enough for 32 random bytes. A wrong token is a 401, never a
   silent downgrade. A token lifts only the public share: not the provider's per-minute limit and
   not the edge's per-client limit. Logs carry the token's name, never the token.

## Consequences
- A saved answer can go stale when the documents change. The drift test catches a moved corpus pin,
  not a rewritten paragraph in a file at the same pin. Saved answers are rebuilt and re-reviewed
  whenever the pin moves. They can also be older than the live index: the nightly run follows each
  repo's head, so a document changed since the pin is answered live from its new text.
- A visitor whose question is not one of the five gets a labelled list of examples, not an answer
  to their question. That follows the brief's definition of a good response, but it is a weak
  answer to the visitor; the live-versus-saved share is how the weakness stays visible.
- A "busy" or "rate limited" reply is now about 4 KB instead of a few bytes. The edge's per-client
  limit bounds what one visitor can pull.
- The budget is not backed up (the database is a cache): rebuilding it hands out a fresh day.

## At scale
A model gateway with per-tenant and per-token budgets, retries and provider fallback; an answer
cache keyed by the normalised question and the corpus version (it would replace the hand-picked
saved answers); one counter row per day becomes a hot row at high rates, so counting moves to
Redis or a batched writer.
