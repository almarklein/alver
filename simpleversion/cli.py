"""Commands to easily manage releases and changelog

* Run `simpleversion bump vx.y.z`.
* Edit the changelog as needed.
* Commit and create a PR for this version bump.
* When merged, push a tag to roll the release.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import changelog

VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+(?:[.\-][0-9A-Za-z]+)*$", re.IGNORECASE)
VERSION_LINE_RE = re.compile(r"^(__version__\s*=\s*)(['\"])([^'\"]*)\2", re.MULTILINE)
GITHUB_REMOTE_RE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)

# Directories to skip when searching the repo for _version.py.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".tox",
    ".nox",
    ".eggs",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simpleversion",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "version", help="Print the current project version from _version.py."
    )

    p_bump = sub.add_parser(
        "bump",
        help="Bump the version and add a changelog section with "
        "gh-generated release notes.",
    )
    p_bump.add_argument("version", help="New version, e.g. v1.2.3")

    p_notes = sub.add_parser(
        "notes", help="Print the release notes for a version from CHANGELOG.md."
    )
    p_notes.add_argument("version", help="Version to show notes for, e.g. v1.2.3")

    sub.add_parser(
        "changelog-from-gh",
        help="Create/update CHANGELOG.md sections from the GitHub releases "
        "of this repo.",
    )

    sub.add_parser(
        "changelog-to-gh",
        help="Update the release notes of all gh releases that have a "
        "section in CHANGELOG.md.",
    )

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    if args.command == "bump":
        return cmd_bump(args.version)
    elif args.command == "notes":
        return cmd_notes(args.version)
    elif args.command == "version":
        return cmd_version()
    elif args.command == "changelog-from-gh":
        return cmd_changelog_from_gh()
    elif args.command == "changelog-to-gh":
        return cmd_changelog_to_gh()
    return 2  # pragma: no cover


def cmd_changelog_to_gh() -> int:
    repo_dir = get_repo_dir()
    changelog_file = get_changelog_file(
        repo_dir
    )  # must exist; nothing to push otherwise
    owner, repo = get_owner_repo(repo_dir)
    releases = get_gh_releases(owner, repo, repo_dir)

    _preamble, sections = changelog.parse_changelog(
        changelog_file.read_text(encoding="utf-8")
    )
    by_version = {changelog.norm_version(r["tag"]): r for r in releases}

    updated = 0
    skipped: list[str] = []
    for s in sections:
        if not changelog.is_version_name(s.name):
            continue  # e.g. [unreleased]
        rel = by_version.get(changelog.norm_version(s.name))
        if rel is None:
            skipped.append(s.name)
            continue
        body = s.body.strip("\n")
        if not body:
            skipped.append(s.name)
            continue
        # Check both version texts (section name vs release tag) and use the
        # larger one as the tag, so e.g. "v0.2.0" wins over "0.2.0".
        tag = max([str(rel["tag"]), s.name], key=len)
        update_gh_release(owner, repo, tag, rel.get("id"), body, repo_dir)
        print(f"Updated release {tag} ({owner}/{repo}) with notes from CHANGELOG.md")
        updated += 1

    for name in skipped:
        print(f"Skipped [{name}]: no matching gh release or empty section")
    print(f"Done: {updated} release(s) updated, {len(skipped)} section(s) skipped.")
    return 0


def cmd_changelog_from_gh() -> int:
    repo_dir = get_repo_dir()
    changelog_file = get_changelog_file(repo_dir, create=True)
    owner, repo = get_owner_repo(repo_dir)
    releases = get_gh_releases(owner, repo, repo_dir)
    new_text = changelog.changelog_from_releases(
        changelog_file.read_text(encoding="utf-8"), releases
    )
    changelog_file.write_text(new_text, encoding="utf-8")
    print(
        f"Updated {changelog_file.relative_to(repo_dir)} from {len(releases)} "
        f"gh releases ({owner}/{repo})"
    )
    return 0


def cmd_version() -> int:
    repo_dir = get_repo_dir()
    version_file = find_version_file(repo_dir)
    print(load_version(version_file))
    return 0


def load_version(path: Path) -> str:
    """Load a _version.py as a module and return its __version__ attribute."""
    try:
        spec = importlib.util.spec_from_file_location("_version", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return str(mod.__version__)
    except Exception:
        # The module-level code failed (e.g. its package is not importable);
        # fall back to reading the literal __version__ assignment.
        m = VERSION_LINE_RE.search(path.read_text(encoding="utf-8"))
        if m:
            return m.group(3)
        sys.exit(f"error: could not determine __version__ from {path}")


def cmd_bump(version: str) -> int:
    if not VERSION_RE.fullmatch(version):
        sys.exit(f"error: invalid version {version!r}, expected something like v1.2.3")

    repo_dir = get_repo_dir()
    version_file = find_version_file(repo_dir)
    changelog_file = get_changelog_file(repo_dir, create=True)

    owner, repo = get_owner_repo(repo_dir)
    release_notes, source = get_release_notes(owner, repo, version, repo_dir)

    # The changelog header and git tag keep the "v" prefix (e.g. v1.2.3),
    # but __version__ itself must be a plain PEP 440 version (1.2.3).
    plain_version = version[1:] if version[:1].lower() == "v" else version
    old_version = set_version_in_file(version_file, plain_version)
    new_text = changelog.bump_changelog(
        changelog_file.read_text(encoding="utf-8"), version, release_notes
    )
    changelog_file.write_text(new_text, encoding="utf-8")

    print(
        f"Bumped {version_file.relative_to(repo_dir)}: {old_version} -> {plain_version}"
    )
    print(
        f"Updated {changelog_file.relative_to(repo_dir)}: section [{version}] "
        f"with release notes from {source} ({owner}/{repo})"
    )
    return 0


def cmd_notes(version: str) -> int:
    repo_dir = get_repo_dir()
    changelog_file = get_changelog_file(repo_dir)
    try:
        body = changelog.extract_changelog(
            changelog_file.read_text(encoding="utf-8"), version
        )
    except KeyError:
        sys.exit(f"error: no section for version {version!r} in {changelog_file}")
    print(body)
    return 0


# ===== Repo helpers


def run_git(repo_dir: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip()


def get_repo_dir() -> Path:
    try:
        return Path(run_git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    except RuntimeError as e:
        sys.exit(f"error: not inside a git repository ({e})")


def get_owner_repo(repo_dir: Path) -> tuple[str, str]:
    """Derive (owner, repo) from the git remote url, e.g. git@github.com:o/r.git."""
    remotes = run_git(repo_dir, "remote").split()
    if not remotes:
        sys.exit(f"error: no git remote configured in {repo_dir}")
    name = "origin" if "origin" in remotes else remotes[0]
    url = run_git(repo_dir, "remote", "get-url", name)
    m = GITHUB_REMOTE_RE.search(url)
    if not m:
        sys.exit(
            f"error: could not derive org/repo from remote {name!r} url {url!r} "
            "(only github.com remotes are supported)"
        )
    return m.group("owner"), m.group("repo")


def get_changelog_file(repo_dir: Path, create: bool = False) -> Path:
    """Return the path to CHANGELOG.md, optionally creating a default one."""
    path = repo_dir / "CHANGELOG.md"
    if not path.is_file():
        if not create:
            sys.exit(f"error: no CHANGELOG.md found at {path}")
        path.write_text(changelog.DEFAULT_CHANGELOG, encoding="utf-8")
        print(f"Created {path.relative_to(repo_dir)}")
    return path


def find_version_file(repo_dir: Path) -> Path:
    """Find the _version.py in the repo (shallowest match wins)."""
    matches = []
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        ]
        if "_version.py" in filenames:
            matches.append(Path(dirpath) / "_version.py")
    if not matches:
        sys.exit(f"error: no _version.py found in {repo_dir}")
    matches.sort(key=lambda p: (len(p.parts), str(p)))
    return matches[0]


def set_version_in_file(path: Path, version: str) -> str:
    """Set __version__ in the given _version.py. Returns the old version."""
    text = path.read_text(encoding="utf-8")
    m = VERSION_LINE_RE.search(text)
    if not m:
        sys.exit(f"error: no __version__ assignment found in {path}")
    old = m.group(3)
    new_text = (
        text[: m.start()]
        + m.group(1)
        + m.group(2)
        + version
        + m.group(2)
        + text[m.end() :]
    )
    path.write_text(new_text, encoding="utf-8")
    return old


# ===== Release notes


def _run_gh(cmd: list[str], repo_dir: Path):
    """Run a gh command; return None if the gh executable is not installed."""
    try:
        return subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    except FileNotFoundError:
        return None


def get_release_notes(
    owner: str, repo: str, tag: str, repo_dir: Path
) -> tuple[str, str]:
    """Get release notes for ``tag`` as generated by gh. Returns (notes, source)."""
    base_cmd = [
        "gh",
        "api",
        f"repos/{owner}/{repo}/releases/generate-notes",
        "-f",
        f"tag_name={tag}",
        "--jq",
        ".body",
    ]
    p = _run_gh(base_cmd, repo_dir)
    if p is not None and p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip("\n"), "gh"

    # The tag may not exist yet (bump happens before tagging); point gh at the
    # current commit instead.
    try:
        head = run_git(repo_dir, "rev-parse", "HEAD")
    except RuntimeError:
        head = "HEAD"
    p2 = _run_gh([*base_cmd, "-f", f"target_commitish={head}"], repo_dir)
    if p2 is not None and p2.returncode == 0 and p2.stdout.strip():
        return p2.stdout.strip("\n"), "gh"

    err_src = (
        (p2.stderr if p2 is not None else "")
        or (p.stderr if p is not None else "")
        or "gh executable not found"
    )
    err_lines = err_src.strip().splitlines()
    err = err_lines[-1] if err_lines else "unknown error"
    print(
        f"warning: could not generate release notes with gh ({err}); "
        "falling back to git log",
        file=sys.stderr,
    )
    return git_log_notes(repo_dir), "git log"


def get_gh_releases(owner: str, repo: str, repo_dir: Path) -> list[dict]:
    """List published gh releases (newest first) as dicts with tag/date/body."""
    cmd = [
        "gh",
        "api",
        "--paginate",
        f"repos/{owner}/{repo}/releases?per_page=100",
        "--jq",
        '.[] | select(.draft | not) | {id: .id, tag: .tag_name, date: .published_at, body: (.body // "")}',
    ]
    p = _run_gh(cmd, repo_dir)
    if p is None:
        sys.exit("error: gh executable not found; cannot list releases")
    if p.returncode != 0:
        sys.exit(
            f"error: could not list gh releases for {owner}/{repo}: {p.stderr.strip()}"
        )
    # The jq filter emits one compact JSON object per line.
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]


def update_gh_release(
    owner: str,
    repo: str,
    tag: str,
    release_id,
    body: str,
    repo_dir: Path,
) -> None:
    """PATCH the notes (body) of a gh release, by tag first, then by id."""
    endpoints = [f"repos/{owner}/{repo}/releases/tags/{tag}"]
    if release_id is not None:
        endpoints.append(f"repos/{owner}/{repo}/releases/{release_id}")
    err = "gh executable not found"
    for endpoint in endpoints:
        p = _run_gh(
            ["gh", "api", "-X", "PATCH", endpoint, "-f", f"body={body}"], repo_dir
        )
        if p is not None and p.returncode == 0:
            return
        if p is not None:
            err = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else err
    sys.exit(f"error: could not update release {tag!r} ({owner}/{repo}): {err}")


def git_log_notes(repo_dir: Path) -> str:
    """Fallback release notes from the git log since the previous tag."""
    try:
        prev = run_git(repo_dir, "describe", "--tags", "--abbrev=0")
        rev_range = f"{prev}..HEAD"
    except RuntimeError:
        rev_range = "HEAD"
    return run_git(repo_dir, "log", "--pretty=format:* %s (%h)", rev_range)
