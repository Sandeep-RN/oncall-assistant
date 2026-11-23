"""Demo tokens (ADR 0003, point 7): a token lifts the PUBLIC share of the daily budget.

The cluster never holds a token, only its SHA-256. They arrive as a mounted Secret: a directory
with one file per token. The file name is the token's name (logged with each question), the content
the lowercase hex SHA-256 of the token (scripts/seal-demo-tokens.sh in the gitops repo makes it).
The kubelet refreshes a mounted Secret in place, so a token added, rotated or revoked takes effect
with no restart: the directory is read on every lookup, never cached. Measured live (demo #218,
four merges): ArgoCD synced 1 to 5 minutes after the merge, then the mount changed 3 to 16 s later.
It holds a few small files, and it is read only when a request carries a token.

Plain SHA-256 is enough because a token is 32 random bytes: it cannot be guessed from its hash. The
comparison visits every stored hash with a constant-time compare, so the time taken does not say
which token matched or how many exist. Nothing here logs a token or a hash.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path

# The same name rule as the sealing script: lowercase, short, safe as a file name and in a log line.
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class DemoTokens:
    def __init__(self, directory: str | os.PathLike | None):
        self.directory = Path(directory) if directory else None

    def _hashes(self) -> dict[str, str]:
        if self.directory is None:
            return {}
        try:
            names = sorted(os.listdir(self.directory))
        except OSError:  # no such directory: nothing is sealed yet
            return {}
        found: dict[str, str] = {}
        for name in names:
            # The kubelet's own entries (..data and the timestamped directory) start with a dot.
            if name.startswith(".") or not NAME.fullmatch(name):
                continue
            path = self.directory / name
            try:
                if not path.is_file():  # follows the kubelet's symlinks
                    continue
                value = path.read_text(encoding="ascii").strip().lower()
            except OSError, UnicodeDecodeError:
                continue
            if SHA256_HEX.fullmatch(value):
                found[name] = value
        return found

    def identify(self, presented: str) -> str | None:
        """The name of the token that was presented, or None if it matches none."""
        digest = hashlib.sha256(presented.strip().encode()).hexdigest()
        match = None
        for name, stored in self._hashes().items():
            # No early exit: every stored hash is compared.
            if hmac.compare_digest(stored, digest):
                match = name
        return match
