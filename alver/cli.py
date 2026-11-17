"""Easy management of versions, releases and changelog

* Run `alver bump vx.y.z`
* Edit CHANGELOG.md as needed.
* Create a PR, discuss, merge.
* -> Github does the rest (publish release to Pypi and GH).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import changelog
from .version import get_detailed_version

VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+(?:[.\-][0-9A-Za-z]+)*$", re.IGNORECASE)
VERSION_LINE_RE = re.compile(r"^(__version__\s*=\s*)(['\"])([^'\"]*)\2", re.MULTILINE)
# Matches the ``version = "..."`` line in the [project] table of a pyproject.toml.
PYPROJECT_VERSION_LINE_RE = re.compile(r"^version\s*=\s*(['\"])([^'\"]*)\1")
PROJECT_TABLE_RE = re.compile(r"\s*\[project\]\s*(#.*)?$")
GITHUB_REMOTE_RE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)

# Directories to skip when searching the repo for the version file.
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
        prog="alver",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "version",
        help="Print the current project version (from _version.py, __init__.py, "
        "or pyproject.toml).",
    )

    sub.add_parser(
        "gitversion",
        help="Print the detailed project version based on git tags and history "
        "(like 'version', but refined), e.g. 1.2.3.post4+gabcdef1.",
    )

    sub.add_parser(
        "format",
        help="Format CHANGELOG.md in place, fixes section headers and blank lines.",
    )

    p_bump = sub.add_parser(
        "bump",
        help="Bump to the given version and add a changelog section with "
        "GitHub-generated release notes, e.g. `alver bump v1.2.3`.",
    )
    p_bump.add_argument("version", help="New version to bump to, e.g. v1.2.3")

    p_notes = sub.add_parser(
        "notes",
        help="Print the release notes for the given version from CHANGELOG.md, "
        "e.g. `alver notes v1.2.3`.",
    )
    p_notes.add_argument("version", help="Version to show notes for, e.g. v1.2.3")

    p_from_gh = sub.add_parser(
        "changelog-from-gh",
        help="Create/update CHANGELOG.md sections from the GitHub releases of "
        "this repo for the given version, e.g. `alver changelog-from-gh v1.2.3` "
        "('*' = all releases).",
    )
    p_from_gh.add_argument(
        "version",
        help="Release version to process, e.g. v1.2.3 or v0.2.*; '*' processes "
        "all releases.",
    )

    p_to_gh = sub.add_parser(
        "changelog-to-gh",
        help="Update the gh release notes from the CHANGELOG.md section of the "
        "given version, e.g. `alver changelog-to-gh v1.2.3` ('*' = all sections).",
    )
    p_to_gh.add_argument(
        "version",
        help="Version whose section/release to process, e.g. v1.2.3 or v0.2.*; "
        "'*' processes all sections.",
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
    elif args.command == "gitversion":
        return cmd_gitversion()
    elif args.command == "format":
        return cmd_format()
    elif args.command == "changelog-from-gh":
        return cmd_changelog_from_gh(args.version)
    elif args.command == "changelog-to-gh":
        return cmd_changelog_to_gh(args.version)
    return 2  # pragma: no cover


def version_matches(pattern: str, name: str) -> bool:
    """Whether a version/tag matches a pattern; '*' matches everything.

    Comparison is on normalized versions, so 'v1.2.3' matches '1.2.3', and
    wildcards work, e.g. 'v0.2.*'.
    """
    return fnmatch.fnmatchcase(
        changelog.norm_version(name), changelog.norm_version(pattern)
    )


def cmd_changelog_to_gh(version: str) -> int:
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
        if not version_matches(version, s.name):
            continue  # filtered out by the version argument
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


def cmd_changelog_from_gh(version: str) -> int:
    repo_dir = get_repo_dir()
    changelog_file = get_changelog_file(repo_dir, create=True)
    owner, repo = get_owner_repo(repo_dir)
    releases = get_gh_releases(owner, repo, repo_dir)
    releases = [
        r for r in releases if version_matches(version, str(r.get("tag") or ""))
    ]
    repo_url = f"https://github.com/{owner}/{repo}"
    new_text = changelog.changelog_from_releases(
        changelog_file.read_text(encoding="utf-8"), releases, repo_url=repo_url
    )
    write_repo_file(changelog_file, new_text)
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


def cmd_gitversion() -> int:
    repo_dir = get_repo_dir()
    version_file = find_version_file(repo_dir)
    version = load_version(version_file)
    print(get_detailed_version(version, str(version_file)))
    return 0


def cmd_format() -> int:
    repo_dir = get_repo_dir()
    changelog_file = get_changelog_file(repo_dir)  # must exist
    text = changelog_file.read_text(encoding="utf-8")
    # No repo_url: format normalizes spacing/headers but does not create new
    # release links; existing links are left intact.
    new_text = changelog.format_changelog(text)
    write_repo_file(changelog_file, new_text)
    print(f"Formatted {changelog_file.relative_to(repo_dir)}")
    return 0


def load_version(path: Path) -> str:
    """Read the version verbatim from the source of the given version file.

    The module is not imported/executed; the literal assignment is read from
    the text. Supports _version.py and __init__.py (a __version__ = "..."
    assignment) as well as pyproject.toml (a static version in [project]).
    """
    text = path.read_text(encoding="utf-8")
    if path.name == "pyproject.toml":
        span = _project_version_span(text)
        if span:
            return span[2]
        sys.exit(f"error: could not determine version from [project] in {path}")
    m = VERSION_LINE_RE.search(text)
    if m:
        return m.group(3)
    sys.exit(f"error: no __version__ assignment found in {path}")


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
    repo_url = f"https://github.com/{owner}/{repo}"
    new_text = changelog.bump_changelog(
        changelog_file.read_text(encoding="utf-8"),
        version,
        release_notes,
        repo_url=repo_url,
    )
    write_repo_file(changelog_file, new_text)

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


def try_get_owner_repo(repo_dir: Path) -> tuple[str, str] | None:
    """Derive (owner, repo) from the git remote url; None if not possible."""
    try:
        remotes = run_git(repo_dir, "remote").split()
        if not remotes:
            return None
        name = "origin" if "origin" in remotes else remotes[0]
        url = run_git(repo_dir, "remote", "get-url", name)
    except RuntimeError:
        return None
    m = GITHUB_REMOTE_RE.search(url)
    return (m.group("owner"), m.group("repo")) if m else None


def get_owner_repo(repo_dir: Path) -> tuple[str, str]:
    """Derive (owner, repo) from the git remote url, e.g. git@github.com:o/r.git."""
    result = try_get_owner_repo(repo_dir)
    if result is not None:
        return result
    remotes = run_git(repo_dir, "remote").split()
    if not remotes:
        sys.exit(f"error: no git remote configured in {repo_dir}")
    name = "origin" if "origin" in remotes else remotes[0]
    url = run_git(repo_dir, "remote", "get-url", name)
    sys.exit(
        f"error: could not derive org/repo from remote {name!r} url {url!r} "
        "(only github.com remotes are supported)"
    )


# Reference files used to detect the repo's line-ending style (the files alver
# writes itself are deliberately not used: they may carry mixed endings).
NEWLINE_REFERENCE_FILES = ("README.md", "pyproject.toml", "LICENSE")


def detect_newline() -> str:
    """The dominant line ending (LF or CRLF) of the repo's reference files.

    Checks README.md, pyproject.toml and LICENSE in the repo root; the first
    one that exists and contains newlines decides (majority wins, ties go to
    the next candidate). Defaults to LF.
    """
    try:
        repo_dir = get_repo_dir()
    except SystemExit:
        return "\n"  # not inside a git repo
    for name in NEWLINE_REFERENCE_FILES:
        p = repo_dir / name
        try:
            data = p.read_bytes()
        except OSError:
            continue
        crlf = data.count(b"\r\n")
        lf = data.count(b"\n") - crlf
        if crlf > lf:
            return "\r\n"
        if lf:
            return "\n"
    return "\n"


def write_repo_file(path: Path, text: str) -> None:
    """Write a text file using the repo's dominant newline style.

    This keeps git diffs clean both for repos checked out as-is (LF,
    core.autocrlf=false) and for repos with newline translation enabled
    (CRLF working files on Windows). The in-memory text is always LF;
    newline= only controls the on-disk encoding.
    """
    path.write_text(text, encoding="utf-8", newline=detect_newline())


def get_changelog_file(repo_dir: Path, create: bool = False) -> Path:
    """Return the path to CHANGELOG.md, optionally creating a default one."""
    path = repo_dir / "CHANGELOG.md"
    if not path.is_file():
        if not create:
            sys.exit(f"error: no CHANGELOG.md found at {path}")
        write_repo_file(path, changelog.DEFAULT_CHANGELOG)
        print(f"Created {path.relative_to(repo_dir)}")
    return path


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _project_version_span(text: str) -> tuple[int, int, str] | None:
    """Locate the ``version = "..."`` value in the [project] table of a pyproject.toml.

    Returns (start, end, version) character offsets of the version value in
    ``text``, or None if the [project] table has no static version line.
    """
    in_project = False
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("["):
            in_project = bool(PROJECT_TABLE_RE.fullmatch(line))
        elif in_project:
            m = PYPROJECT_VERSION_LINE_RE.match(line)
            if m:
                start = offset + m.start(2)
                return start, start + len(m.group(2)), m.group(2)
        offset += len(line)
    return None


def find_version_file(repo_dir: Path) -> Path:
    """Find the file that defines the project version (shallowest match wins).

    Recognized version files: ``_version.py``, an ``__init__.py`` with a
    ``__version__`` assignment, and a ``pyproject.toml`` with a static
    ``version`` in its ``[project]`` table.
    """
    matches: list[tuple[Path, int]] = []
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        ]
        p = Path(dirpath)
        if "_version.py" in filenames:
            matches.append((p / "_version.py", 0))
        if "__init__.py" in filenames:
            init_file = p / "__init__.py"
            if VERSION_LINE_RE.search(_read_text_safe(init_file)):
                matches.append((init_file, 1))
        if "pyproject.toml" in filenames:
            pyproject = p / "pyproject.toml"
            if _project_version_span(_read_text_safe(pyproject)):
                matches.append((pyproject, 2))
    if not matches:
        sys.exit(
            f"error: no version file found in {repo_dir} (looked for _version.py, "
            "__init__.py with __version__, and pyproject.toml with [project] version)"
        )
    matches.sort(key=lambda t: (len(t[0].parts), t[1], str(t[0])))
    return matches[0][0]


def set_version_in_file(path: Path, version: str) -> str:
    """Set the version in the given version file. Returns the old version."""
    text = path.read_text(encoding="utf-8")
    if path.name == "pyproject.toml":
        span = _project_version_span(text)
        if not span:
            sys.exit(f"error: no version assignment found in [project] of {path}")
        start, end, old = span
        write_repo_file(path, text[:start] + version + text[end:])
        return old
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
    write_repo_file(path, new_text)
    return old


# ===== Release notes


def _run_gh(cmd: list[str], repo_dir: Path):
    """Run a gh command; return None if the gh executable is not installed."""
    try:
        return subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    except FileNotFoundError:
        return None


# ===== GitHub REST API
#
# Talking to GitHub does not require the gh executable: if GH_TOKEN or
# GITHUB_TOKEN is set, we call the REST API directly over HTTPS (stdlib only).
# The gh CLI is only used as a fallback (it brings its own stored auth).

GITHUB_API_URL = "https://api.github.com"


def _github_token() -> str | None:
    """Token for the GitHub REST API (same env vars as the gh CLI respects)."""
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None


def _api_request(
    method: str, endpoint: str, fields: dict | None = None
) -> tuple[int, str] | None:
    """Call the GitHub REST API directly over HTTPS, using GH_TOKEN/GITHUB_TOKEN.

    Returns (status, body), or None if no token is set or the request failed.
    """
    token = _github_token()
    if not token:
        return None
    data = json.dumps(fields).encode("utf-8") if fields is not None else None
    req = urllib.request.Request(
        f"{GITHUB_API_URL}/{endpoint}", data=data, method=method
    )
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except OSError:
        return None


def _api_call(
    method: str, endpoint: str, repo_dir: Path, fields: dict | None = None
) -> tuple[int, str, str] | None:
    """Call the GitHub REST API, preferring a direct HTTPS call (no gh needed)
    and falling back to `gh api`. Returns (status, body, source), or None if
    neither transport is available."""
    res = _api_request(method, endpoint, fields)
    if res is not None:
        return res[0], res[1], "GitHub API"
    cmd = ["gh", "api"]
    if method != "GET":
        cmd += ["-X", method]
    cmd.append(endpoint)
    for k, v in (fields or {}).items():
        cmd += ["-f", f"{k}={v}"]
    p = _run_gh(cmd, repo_dir)
    if p is None:
        return None
    # Normalize the gh exit code to an HTTP-ish status: 200 on success.
    if p.returncode == 0:
        return 200, p.stdout, "gh"
    return 500, p.stderr or p.stdout, "gh"


def _api_get_list(endpoint: str, repo_dir: Path) -> tuple[int, str, str] | None:
    """GET a list endpoint, following pagination. Same transport preference as
    _api_call. Returns (status, raw_body, source), or None if neither works."""
    if _github_token():
        parts: list = []
        page = 1
        while True:
            sep = "&" if "?" in endpoint else "?"
            res = _api_request("GET", f"{endpoint}{sep}per_page=100&page={page}")
            if res is None:
                break  # network problem: fall back to gh below
            status, text = res
            if status != 200:
                return status, text, "GitHub API"
            try:
                batch = json.loads(text)
            except ValueError:
                return status, text, "GitHub API"
            if not isinstance(batch, list):
                return status, text, "GitHub API"
            parts.extend(batch)
            if len(batch) < 100:
                return 200, json.dumps(parts), "GitHub API"
            page += 1
    p = _run_gh(["gh", "api", "--paginate", f"{endpoint}?per_page=100"], repo_dir)
    if p is None:
        return None
    if p.returncode == 0:
        return 200, p.stdout, "gh"
    return 500, p.stderr or p.stdout, "gh"


def get_release_notes(
    owner: str, repo: str, tag: str, repo_dir: Path
) -> tuple[str, str]:
    """Get release notes for ``tag`` from GitHub's generate-notes endpoint.
    Returns (notes, source); falls back to the git log."""
    endpoint = f"repos/{owner}/{repo}/releases/generate-notes"
    try:
        head = run_git(repo_dir, "rev-parse", "HEAD")
    except RuntimeError:
        head = "HEAD"
    # The tag may not exist yet (bump happens before tagging); point the API
    # at the current commit instead.
    attempts = [{"tag_name": tag}, {"tag_name": tag, "target_commitish": head}]
    err = "no GitHub credentials (set GH_TOKEN or GITHUB_TOKEN, or install gh)"
    for fields in attempts:
        res = _api_call("POST", endpoint, repo_dir, fields)
        if res is None:
            break
        status, text, source = res
        if status == 200:
            try:
                body = json.loads(text).get("body") or ""
            except (ValueError, AttributeError):
                body = ""
            if body.strip():
                return body.strip("\n"), source
        else:
            err_lines = text.strip().splitlines()
            if err_lines:
                err = err_lines[-1]
    print(
        f"warning: could not generate release notes ({err}); falling back to git log",
        file=sys.stderr,
    )
    return git_log_notes(repo_dir), "git log"


def get_gh_releases(owner: str, repo: str, repo_dir: Path) -> list[dict]:
    """List published gh releases (newest first) as dicts with tag/date/body."""
    res = _api_get_list(f"repos/{owner}/{repo}/releases", repo_dir)
    if res is None:
        sys.exit(
            "error: no GitHub credentials: set GH_TOKEN or GITHUB_TOKEN, or install gh"
        )
    status, text, _source = res
    if status != 200:
        err = text.strip().splitlines()[-1] if text.strip() else f"HTTP {status}"
        sys.exit(f"error: could not list gh releases for {owner}/{repo}: {err}")
    try:
        items = json.loads(text)
    except ValueError:
        items = []
    return [
        {
            "id": r.get("id"),
            "tag": r.get("tag_name"),
            "date": r.get("published_at"),
            "body": r.get("body") or "",
        }
        for r in items
        if isinstance(r, dict) and not r.get("draft")
    ]


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
    err = "no GitHub credentials (set GH_TOKEN or GITHUB_TOKEN, or install gh)"
    for endpoint in endpoints:
        res = _api_call("PATCH", endpoint, repo_dir, {"body": body})
        if res is None:
            break
        status, text, _source = res
        if status in (200, 201):
            return
        err_lines = text.strip().splitlines()
        if err_lines:
            err = err_lines[-1]
    sys.exit(f"error: could not update release {tag!r} ({owner}/{repo}): {err}")


def git_log_notes(repo_dir: Path) -> str:
    """Fallback release notes from the git log since the previous tag."""
    try:
        prev = run_git(repo_dir, "describe", "--tags", "--abbrev=0")
        rev_range = f"{prev}..HEAD"
    except RuntimeError:
        rev_range = "HEAD"
    return run_git(repo_dir, "log", "--pretty=format:* %s (%h)", rev_range)
