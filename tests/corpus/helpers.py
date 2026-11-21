import io
import tarfile

SHA = "a" * 40


def make_tarball(files: dict[str, bytes | str], prefix: str = "o-r-aaaa") -> bytes:
    """A GitHub-style repo tarball: every path sits under one top-level directory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo(f"{prefix}/linked.md")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    return buf.getvalue()


class FakeGet:
    """Stands in for the HTTP boundary: maps a URL substring to a response body."""

    def __init__(self, routes: dict[str, bytes]):
        self.routes, self.calls = routes, []

    def __call__(self, url: str, headers: dict[str, str]):
        self.calls.append(url)
        for part, body in self.routes.items():
            if part in url:
                return io.BytesIO(body)
        raise AssertionError(f"unexpected url {url}")
