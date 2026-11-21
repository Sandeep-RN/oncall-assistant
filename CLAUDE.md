# oncall-assistant (application, tests, CI)

Workspace-level rules and the working plan are private files one folder up (they are not in this repo). Read them first.

- This repo: the assistant's code, its tests and evals, and GitHub Actions. No Kubernetes
  manifests here; those belong in the gitops repo (Sandeep-RN/oci-k8s-gitops-demo-gitops).
  Platform decisions (resource cap, namespace, AppProject) are ADR 0025 in
  Sandeep-RN/oci-k8s-gitops-demo; decisions about the app itself go in `docs/adr/` here.
- This repo is PUBLIC. Never commit keys, tokens, `.env` files, kubeconfig or IP addresses.
  Run gitleaks (pre-commit) before every commit.
- Build features test-first. Keep `/healthz` working and free of database and provider calls.
- CI pins third-party Actions by commit SHA. Runtime and dev dependencies are exact pins.
- The assistant's own limits are in ADR 0025: 1 GiB of memory and 1 CPU for everything in its
  namespace (app 384Mi, Postgres 256Mi, indexing Job 384Mi at peak). Embeddings run on ONNX
  Runtime; no PyTorch. Keep the image and memory use inside that budget.
- Secrets: only the public provider's key (Groq) and the demo tokens ever reach the cluster.
  The development and eval key (KodeKey) lives on the developer's laptop and in CI secrets, never
  in the cluster.
- Use the terms in `GLOSSARY.md` (passage, citation, refusal, live answer, saved answer, ...).

## Agent skills

### Issue tracker

Issues for this repo live in GitHub Issues on Sandeep-RN/oncall-assistant. Platform work for the
assistant lives in the demo repo, milestone "oncall-assistant (ADR 0025)". See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix, plus
`post-idea`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` at the root, app decisions in `docs/adr/`. Platform decisions
are in the demo repo's `docs/adr/`.

### Post ideas

Offer to log non-obvious fixes, gotchas and trade-offs as `post-idea` issues in this repo. Same
six-section format as in the demo repo's "Post ideas" section. Fake values only; real events only;
ask first.
