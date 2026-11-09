"""Read and update a Keep-a-Changelog style CHANGELOG.md.

Sections are headed by ``## [name]`` or ``## [name] - date`` lines, e.g.
``## [unreleased]`` or ``## [v1.2.3] - 23-06-2026``. Everything before the
first section header is the preamble and is preserved as-is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .version import get_version_tuple

# Matches a section header line, e.g. "## [v1.2.3] - 23-06-2026" or "## [unreleased]".
# Sections may be written with two or three hashes ("## [...]", "### [...]");
# they are always written back with "## ". A single "#" is deliberately not
# matched: "# ..." is usually a comment (e.g. in a code block), not a header.
# A version section may already link to its gh release page, e.g.
# "## [v1.2.3](https://github.com/o/r/releases/tag/v1.2.3)"; the link is
# stripped on parse and regenerated on render.
HEADER_RE = re.compile(
    r"^#{2,3}\s*\[([^\]]*)\](\([^)]*\))?\s*(?:-\s*(.*?))?\s*$", re.MULTILINE
)

# Matches a markdown sub-header line inside a section body ("## Foo"); single
# "#" lines are left alone (comments). Rewritten as "### Foo" on render.
SUBHEADER_RE = re.compile(r"^## (.*)$", re.MULTILINE)

# Matches a section name that is a version, e.g. "v1.2.3" or "1.2.3rc1"
VERSION_NAME_RE = re.compile(r"v?\d+(\.\d+)*[0-9A-Za-z.\-+]*", re.IGNORECASE)

# Section names that hold not-yet-released changes.
UNRELEASED_NAMES = ("unreleased", "pending")

# Template for a CHANGELOG.md that does not exist yet.
DEFAULT_CHANGELOG = """# Changelog / release notes

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Possible sections in each release:

* Added: for new features.
* Changed: for changes in existing functionality.
* Deprecated: for soon-to-be removed features.
* Removed: for now removed features.
* Fixed: for any bug fixes.
* Security: in case of vulnerabilities.

"""


@dataclass
class Section:
    """A ``## [name] - date`` section of the changelog."""

    name: str
    date: str = ""
    body: str = ""
    link: str = ""  # existing release-page link (url without parens), if any


def norm_version(v: str) -> str:
    """Normalize a version for comparison, so 'v1.2.3' == '1.2.3'."""
    return v.strip().removeprefix("v").lower()


def is_version_name(name: str) -> bool:
    """Whether a section name looks like a version, e.g. 'v1.2.3'."""
    return bool(VERSION_NAME_RE.fullmatch(name.strip()))


def _version_sort_key(name: str) -> tuple:
    """Sort key for a version section name; numeric parts compare numerically."""
    parts = get_version_tuple(norm_version(name))
    # Wrap each part so ints and strings never compare against each other.
    return tuple((0, p) if isinstance(p, int) else (1, str(p)) for p in parts)


def sort_sections(sections: list[Section]) -> list[Section]:
    """Order sections: [unreleased]/[pending] on top, then release sections
    sorted newest version first, then any remaining sections in original order."""
    head: list[Section] = []
    vers: list[Section] = []
    rest: list[Section] = []
    for s in sections:
        if s.name.lower() in UNRELEASED_NAMES:
            head.append(s)
        elif is_version_name(s.name):
            vers.append(s)
        else:
            rest.append(s)
    vers.sort(key=lambda s: _version_sort_key(s.name), reverse=True)
    return head + vers + rest


def parse_changelog(text: str) -> tuple[str, list[Section]]:
    """Split changelog text into the preamble and a list of sections."""
    matches = list(HEADER_RE.finditer(text))
    preamble = text[: matches[0].start()] if matches else text
    sections = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw_link = m.group(2) or ""
        sections.append(
            Section(
                name=m.group(1).strip(),
                date=(m.group(3) or "").strip(),
                body=text[m.end() : end],
                link=raw_link[1:-1] if raw_link else "",
            )
        )
    return preamble, sections


def _normalize_body(body: str) -> str:
    """Normalize a section body: at most one blank line (two successive
    newlines) between lines, and sub-headers written as "## " are rewritten
    as "### ". Lines starting with a single "#" are left alone."""
    text = re.sub(r"\n{3,}", "\n\n", body.strip("\n"))
    return SUBHEADER_RE.sub(r"### \1", text)


def _header_name(s: Section, repo_url: str | None) -> str:
    """The bracketed section name. With ``repo_url``, version sections are
    (re)linked to their gh release page; without it, an existing link is kept
    as-is and no new links are created."""
    if repo_url and is_version_name(s.name):
        return f"[{s.name}]({repo_url}/releases/tag/{s.name})"
    if s.link:
        return f"[{s.name}]({s.link})"
    return f"[{s.name}]"


def render_changelog(
    preamble: str, sections: list[Section], repo_url: str | None = None
) -> str:
    """Compose changelog text from a preamble and sections, in canonical format.

    Section headers are always written as ``## [name]`` (regardless of how they
    were written). If ``repo_url`` is given (e.g. "https://github.com/o/r"),
    version sections are (re)linked to their gh release page; without it,
    existing links are kept as-is and no new links are created. Sections are
    separated by exactly two blank lines, within a section there is at most
    one blank line, and sub-headers inside a section are written as ``### ``.
    """
    blocks = []
    for s in sections:
        header = f"## {_header_name(s, repo_url)}"
        if s.date:
            header += f" - {s.date}"
        body = _normalize_body(s.body)
        blocks.append(header + "\n\n" + body if body else header)
    parts = []
    if preamble.strip():
        parts.append(preamble.rstrip("\n"))
    parts.extend(blocks)
    if not parts:
        return ""
    return "\n\n\n".join(parts) + "\n"


def format_changelog(text: str, repo_url: str | None = None) -> str:
    """Format changelog text into the canonical format (see ``render_changelog``),
    preserving the order of the sections. Without ``repo_url``, existing
    release links are kept as-is and no new links are created."""
    preamble, sections = parse_changelog(text)
    return render_changelog(preamble, sections, repo_url)


def bump_changelog(
    text: str,
    version: str,
    release_notes: str,
    today: str | None = None,
    repo_url: str | None = None,
) -> str:
    """Return updated changelog text for releasing ``version``.

    A new section ``## [version] - <today>`` is added, unless a section for
    this version already exists, in which case that section is used. If an
    ``[unreleased]`` or ``[pending]`` section exists, its header is removed
    and its content is moved into the target section, followed by the given
    release notes. Sections are sorted so that newer versions are on top.
    """
    if today is None:
        today = date.today().strftime("%d-%m-%Y")
    preamble, sections = parse_changelog(text)
    v = norm_version(version)

    unreleased = next((s for s in sections if s.name.lower() in UNRELEASED_NAMES), None)
    target = next((s for s in sections if norm_version(s.name) == v), None)

    if target is None:
        target = Section(name=version, date=today)
        sections.append(target)
    if unreleased is not None:
        sections.remove(unreleased)

    # Compose the target body: existing content, then the unreleased content,
    # then the generated release notes. The notes are skipped if already
    # present (e.g. when bumping the same version twice).
    parts = []
    for chunk in (target.body, unreleased.body if unreleased else ""):
        chunk = chunk.strip("\n")
        if chunk:
            parts.append(chunk)
    notes_chunk = release_notes.strip("\n")
    if notes_chunk and notes_chunk not in "\n\n".join(parts):
        parts.append(notes_chunk)
    target.body = "\n\n".join(parts)

    return render_changelog(preamble, sort_sections(sections), repo_url)


def changelog_from_releases(
    text: str, releases: list[dict], repo_url: str | None = None
) -> str:
    """Create/update changelog sections from gh releases (expected newest first).

    Each release is a dict with keys ``tag``, ``date`` (ISO string) and ``body``.
    Existing ``[unreleased]``/``[pending]`` sections are kept on top. A section
    whose version matches a release tag gets its date updated from gh, its name
    set to the larger of the two version texts (so "v0.2.0" wins over "0.2.0"),
    and its body set to the larger of the two notes texts (gh vs changelog);
    a release without a section gets a new one. Sections are sorted so that
    newer versions are on top.
    """
    preamble, sections = parse_changelog(text)
    by_version = {norm_version(s.name): s for s in sections}

    merged: list[Section] = []
    used: set[str] = set()
    for rel in releases:
        tag = str(rel.get("tag") or "").strip()
        if not tag:
            continue
        key = norm_version(tag)
        date_str = iso_to_changelog_date(rel.get("date") or "")
        body = str(rel.get("body") or "").strip("\n")
        existing = by_version.get(key)
        if existing is not None and key not in used:
            existing.date = date_str or existing.date
            # Keep the larger notes text, whether it comes from gh or the changelog.
            existing.body = max([existing.body.strip("\n"), body], key=len)
            existing.name = max([tag, existing.name], key=len)
            merged.append(existing)
            used.add(key)
        else:
            merged.append(Section(name=tag, date=date_str, body=body))

    # Keep all other existing sections (including [unreleased]/[pending]).
    for s in sections:
        if norm_version(s.name) not in used:
            merged.append(s)

    return render_changelog(preamble, sort_sections(merged), repo_url)


def iso_to_changelog_date(s: str) -> str:
    """Convert an ISO datetime like '2026-11-09T12:34:56Z' to '09-11-2026'."""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%d-%m-%Y")
    except ValueError:
        return s


def extract_changelog(text: str, version: str) -> str:
    """Return the body of the section for ``version``.

    Raises KeyError if there is no section for this version.
    """
    _preamble, sections = parse_changelog(text)
    v = norm_version(version)
    for s in sections:
        if norm_version(s.name) == v:
            return s.body.strip("\n")
    raise KeyError(version)
