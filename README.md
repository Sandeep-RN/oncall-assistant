# oncall-assistant

An on-call assistant for a platform team: ask a question in plain language and
get a short answer that cites the exact runbook or decision record it came
from, or "I don't know" when the documents do not cover it.

This is a **mock customer engagement**. The "customer" is the platform team of
[oci-k8s-gitops-demo](https://github.com/Sandeep-RN/oci-k8s-gitops-demo),
role-played by the author; its documents and its single-node k3s platform are
real and public. The assistant is deployed onto that platform through its
GitOps repository, inside a hard resource cap, at no infrastructure cost.

**Status:** build starting (milestone M1, target 2026-12-09). Only `/healthz` exists so far.
Nothing is live yet.

- [Customer brief](docs/customer-brief.md): problem, users, constraints, success criteria, delivery
- [Glossary](GLOSSARY.md): the terms used in this repo and its issues
- [Issues and milestones](https://github.com/Sandeep-RN/oncall-assistant/milestones): app work
- [Platform side](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/milestone/6): ADR 0025 and the gitops manifests

## Develop

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
pip install pre-commit && pre-commit install      # gitleaks runs before every commit
```

Rules for contributors and agents: [CLAUDE.md](CLAUDE.md).
