# Issue tracker: GitHub

Issues for this repo live in GitHub Issues on Sandeep-RN/oncall-assistant. Use the `gh` CLI.

- Create: `gh issue create --title "..." --body-file file.md`
- Read: `gh issue view <number> --json number,title,body,labels,comments`
- Comment: `gh issue comment <number> --body-file file.md`
- Labels: `gh issue edit <number> --add-label "..."`

Every task starts from an issue, in the milestone M1 to M4, with ONE triage label.
Pull requests close it with `Closes Sandeep-RN/oncall-assistant#N`.

Platform work for the assistant (gitops manifests, ADR 0025 checks) is tracked in
Sandeep-RN/oci-k8s-gitops-demo, milestone "oncall-assistant (ADR 0025)"; reference it with the full
`Sandeep-RN/oci-k8s-gitops-demo#N` form.
