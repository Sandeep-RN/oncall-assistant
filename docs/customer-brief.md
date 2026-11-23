# Customer brief: an on-call assistant for a platform team

Status: draft (2026-11-18; reviewed 2026-11-21). This is a **mock engagement**. The "customer" is a
platform team role-played by the author; its documents and its platform are
real and public: [oci-k8s-gitops-demo](https://github.com/Sandeep-RN/oci-k8s-gitops-demo)
and its two sibling repos.

## The problem

The platform team runs a small Kubernetes platform (single-node k3s on Oracle
Cloud's free tier) with GitOps delivery, an SLO with burn-rate alerts and
tested backups. What the team knows is written down: 25 architecture
decision records, nine runbooks and several evidence write-ups. When an alert fires, the
on-call engineer has to find the right runbook and the decision behind it,
across three repositories, under time pressure.

## The users

On-call engineers of the platform team. They know Kubernetes; they do not
know every decision that was made, or where it is written.

## What they asked for

1. Ask a question in plain language and get a short answer that **cites the
   exact document and section** it came from.
2. Hear **"I don't know"** when the documents do not cover the question,
   rather than a confident guess.
3. Later: an assistant that also **reads the platform's live state**
   (firing alerts, application health, pod events) and combines it with the
   runbooks. Read-only: it may never change anything.

## Constraints

- **Runs on the team's existing platform**, delivered through its GitOps
  repository like any other application. No manual `kubectl apply`.
- **Costs nothing to run.** Free tiers only; any paid credit needs the
  team's approval first.
- **Shares one small node with a live service.** The assistant gets about
  1 GiB of memory and 1 CPU, and the live service always wins.
- **Data handling.** The documents are public. Each visitor question and the
  passages found for it are sent to an external model provider that states it
  does not keep inputs, apart from up to 30 days for abuse and reliability
  checks. Questions are stored only shortened or hashed. Development and evals
  use a separate education key that stays on the developer's laptop and in
  CI, never on the platform; only the team's own eval questions go there,
  never visitors' questions.
- **Public demo.** Anyone may try it within a daily budget; reviewers get a
  named token. The live-state features are token-only. The provider's free
  tier allows only a few live answers per minute; beyond that, visitors get
  saved answers.

## Success criteria

Measured on a fixed set of questions about the team's own documents, which only
grows. It starts at 39 (11 of which the documents cannot answer):

| Criterion | Target |
|---|---|
| The right passage is among the top 5 found | at least 90% of questions |
| Every claim in an answer is supported by a cited passage | at least 90% of answers |
| Unanswerable questions get "I don't know" | at least 90% of them |
| Availability of the public demo, 7 days | 99% of questions get a good response (see below) |
| Speed, 7 days | 95% of live answers within 8 seconds |

A good response is a live answer, a refusal, or a clearly labelled saved
answer; errors and timeouts are bad. The question set grows to about 100 by
M2: with 11 unanswerable questions, one missed refusal already costs about nine
points, which is why the set must grow before its scores are trusted.

## Out of scope

Fine-tuning a model; any write action on the platform; documents that are not
public; high availability (the platform has one node).

## Delivery

| Milestone | Delivers | Target date |
|---|---|---|
| M1 MVP | Cited answers on a live URL | 2026-12-09 (done 2026-11-23) |
| M2 Evals and SLOs | Scores in the README, retrieval gate in CI, dashboard and alerts | 2026-12-23 |
| M3 Agent | Read-only live-state tools behind the token | 2027-01-06 |
| M4 Reliability and handover | Logs, handover runbook, demo video, write-up | about 2027-01-20 |

## Handover

The team receives the repository, its decision records, a runbook for the
assistant's alerts and failure modes (provider down, budget spent, bad
answers), and the eval set so it can judge future changes itself.
