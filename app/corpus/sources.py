"""Which documents the assistant answers from: the Markdown of the three platform repos."""

from __future__ import annotations

from dataclasses import dataclass

# Files an on-call engineer never needs: instructions for coding agents and CI config.
_COMMON_EXCLUDE = (
    "CLAUDE.md",
    "**/CLAUDE.md",
    "docs/agents/**",
    ".github/**",
    "**/node_modules/**",
    "**/.terraform/**",
)


@dataclass(frozen=True)
class Source:
    repo: str  # "owner/name"
    ref: str = "main"  # branch or tag; resolved to a commit SHA before anything is read
    include: tuple[str, ...] = ("**/*.md",)
    exclude: tuple[str, ...] = _COMMON_EXCLUDE


SOURCES: tuple[Source, ...] = (
    Source("Sandeep-RN/oci-k8s-gitops-demo"),
    Source("Sandeep-RN/oci-k8s-gitops-demo-app"),
    Source("Sandeep-RN/oci-k8s-gitops-demo-gitops"),
)
