"""Where issues come from.

Three sources, one shape. A judge needs no credential for any of them:
  - a public GitHub repository (unauthenticated, 60 requests an hour)
  - a cached local file (deterministic, so the proofs are reproducible)
  - a single issue supplied on the command line
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

CACHE = pathlib.Path("demo/data/inbox.json")
API = "https://api.github.com/repos/{repo}/issues?state=open&per_page=100"
TIMEOUT_S = 20


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    author: str
    created_at: str

    @property
    def ref(self) -> str:
        return f"#{self.number}"

    @property
    def text(self) -> str:
        return f"{self.title}\n\n{self.body}"


def from_github(repo: str, *, token: str | None = None) -> list[Issue]:
    """Read open issues from a public repository. No credential required."""
    req = urllib.request.Request(
        API.format(repo=repo),
        headers={"accept": "application/vnd.github+json", "user-agent": "auryn-triage"},
    )
    if token:
        req.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        payload = json.loads(resp.read())
    issues = [
        Issue(
            number=item["number"],
            title=item["title"],
            body=item.get("body") or "",
            author=(item.get("user") or {}).get("login", "unknown"),
            created_at=item.get("created_at", ""),
        )
        for item in payload
        if "pull_request" not in item
    ]
    return sorted(issues, key=lambda i: i.number)


def from_file(path: pathlib.Path = CACHE) -> list[Issue]:
    data = json.loads(path.read_text())
    return [Issue(**row) for row in data]


def save(issues: list[Issue], path: pathlib.Path = CACHE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(i) for i in issues], indent=2) + "\n")


def load(repo: str | None = None, *, path: pathlib.Path = CACHE, token: str | None = None) -> list[Issue]:
    """Prefer the live repository; fall back to the cache when offline.

    A failed fetch must never stop the demo, so the cache exists in the repo.
    """
    if repo:
        try:
            issues = from_github(repo, token=token)
            save(issues, path)
            return issues
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if not path.exists():
                raise
            print(f"  (live fetch failed: {exc}; using the cached inbox)")
    return from_file(path)
