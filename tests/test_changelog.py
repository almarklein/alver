import pytest

from alver import changelog
from alver.changelog import (
    Section,
    bump_changelog,
    changelog_from_releases,
    extract_changelog,
    format_changelog,
    iso_to_changelog_date,
    is_version_name,
    norm_version,
    parse_changelog,
    render_changelog,
    sort_sections,
)

SAMPLE = """# Changelog

Preamble.


## [unreleased]

* wip


## [v0.2.0] - 01-02-2026

* two


## [v0.1.0] - 01-01-2026

* one
"""

TODAY = "09-11-2026"


# ===== parse / render


def test_parse_render_roundtrip():
    preamble, sections = parse_changelog(SAMPLE)
    assert preamble.startswith("# Changelog")
    assert [s.name for s in sections] == ["unreleased", "v0.2.0", "v0.1.0"]
    assert sections[1].date == "01-02-2026"
    assert sections[1].body.strip() == "* two"
    assert render_changelog(preamble, sections) == SAMPLE


def test_parse_empty_text():
    preamble, sections = parse_changelog("")
    assert preamble == ""
    assert sections == []


# ===== small helpers


@pytest.mark.parametrize(
    "a,b,equal",
    [("v1.2.3", "1.2.3", True), ("v1.2.3", "1.2.4", False), ("1.0.0", "v1.0.0", True)],
)
def test_norm_version(a, b, equal):
    assert (norm_version(a) == norm_version(b)) is equal


@pytest.mark.parametrize(
    "name,expected",
    [
        ("v1.2.3", True),
        ("1.2.3", True),
        ("v0.10.0rc1", True),
        ("unreleased", False),
        ("pending", False),
    ],
)
def test_is_version_name(name, expected):
    assert is_version_name(name) is expected


def test_iso_to_changelog_date():
    assert iso_to_changelog_date("2026-11-09T12:34:56Z") == "09-11-2026"
    assert iso_to_changelog_date("not-a-date") == "not-a-date"


# ===== sort_sections


def test_sort_sections_versions_descending():
    sections = [
        Section("v0.1.0"),
        Section("unreleased"),
        Section("v0.10.0"),
        Section("v0.9.0"),
        Section("custom"),
    ]
    ordered = sort_sections(sections)
    assert [s.name for s in ordered] == [
        "unreleased",
        "v0.10.0",
        "v0.9.0",
        "v0.1.0",
        "custom",
    ]


# ===== bump_changelog


def test_bump_new_version_removes_unreleased():
    out = bump_changelog(SAMPLE, "v0.3.0", "* gh notes", today=TODAY)
    assert "[unreleased]" not in out
    assert f"## [v0.3.0] - {TODAY}" in out
    # Unreleased content moved into the new section, followed by the notes.
    section = out.split(f"## [v0.3.0] - {TODAY}")[1].split("## [")[0]
    assert "* wip" in section
    assert "* gh notes" in section
    assert section.index("* wip") < section.index("* gh notes")
    # Newest version on top.
    assert (
        out.index("## [v0.3.0]") < out.index("## [v0.2.0]") < out.index("## [v0.1.0]")
    )


def test_bump_pending_header_is_removed():
    text = SAMPLE.replace("[unreleased]", "[pending]")
    out = bump_changelog(text, "v0.3.0", "* notes", today=TODAY)
    assert "[pending]" not in out
    assert "* wip" in out.split("## [v0.3.0]")[1]


def test_bump_existing_section_reused_and_not_duplicated():
    out1 = bump_changelog(SAMPLE, "v0.2.0", "* new notes", today=TODAY)
    section = out1.split("## [v0.2.0]")[1].split("## [")[0]
    assert "* two" in section and "* new notes" in section and "* wip" in section
    # Bumping the same version again must not duplicate the notes.
    out2 = bump_changelog(out1, "v0.2.0", "* new notes", today=TODAY)
    assert out2.count("* new notes") == 1


def test_bump_older_version_goes_below_newer():
    out = bump_changelog(SAMPLE, "v0.1.5", "* notes", today=TODAY)
    assert (
        out.index("## [v0.2.0]") < out.index("## [v0.1.5]") < out.index("## [v0.1.0]")
    )


def test_bump_into_empty_changelog():
    out = bump_changelog(changelog.DEFAULT_CHANGELOG, "v1.0.0", "* notes", today=TODAY)
    assert out.startswith("# Changelog / release notes")
    assert f"## [v1.0.0] - {TODAY}" in out
    assert "* notes" in out


# ===== extract_changelog


def test_extract():
    assert extract_changelog(SAMPLE, "v0.2.0") == "* two"
    assert extract_changelog(SAMPLE, "0.2.0") == "* two"  # v prefix optional


def test_extract_missing_raises():
    with pytest.raises(KeyError):
        extract_changelog(SAMPLE, "v9.9.9")


# ===== changelog_from_releases


def test_changelog_from_releases_creates_sorted_sections():
    releases = [
        {"tag": "v0.1.0", "date": "2026-01-01T10:00:00Z", "body": "* a"},
        {"tag": "v0.10.0", "date": "2026-03-01T10:00:00Z", "body": "* c"},
        {"tag": "v0.9.0", "date": "2026-02-01T10:00:00Z", "body": "* b"},
    ]
    out = changelog_from_releases("# Changelog\n\n", releases)
    assert (
        out.index("## [v0.10.0] - 01-03-2026")
        < out.index("## [v0.9.0] - 01-02-2026")
        < out.index("## [v0.1.0] - 01-01-2026")
    )
    assert "* c" in out


def test_changelog_from_releases_merges_existing():
    releases = [
        {"tag": "v0.3.0", "date": "2026-10-01T10:00:00Z", "body": "* three"},
        {"tag": "v0.2.0", "date": "2026-09-15T10:00:00Z", "body": "* gh two"},
    ]
    out = changelog_from_releases(SAMPLE, releases)
    # [unreleased] stays on top, v0.2.0 body updated from gh, v0.3.0 added on top
    # of v0.2.0, v0.1.0 kept.
    assert [s.name for s in parse_changelog(out)[1]] == [
        "unreleased",
        "v0.3.0",
        "v0.2.0",
        "v0.1.0",
    ]
    assert extract_changelog(out, "v0.2.0") == "* gh two"
    # Empty gh body keeps the existing hand-written body.
    releases_empty = [{"tag": "v0.2.0", "date": "2026-09-15T10:00:00Z", "body": ""}]
    out2 = changelog_from_releases(SAMPLE, releases_empty)
    assert extract_changelog(out2, "v0.2.0") == "* two"


@pytest.mark.parametrize(
    "existing_body,gh_body,expected",
    [
        ("* two", "* gh two", "* gh two"),  # gh text is larger
        (
            "* a much longer handwritten note",
            "* gh",
            "* a much longer handwritten note",
        ),  # changelog text is larger
        ("* two", "", "* two"),  # no gh notes
    ],
)
def test_changelog_from_releases_picks_larger_notes_text(
    existing_body, gh_body, expected
):
    text = SAMPLE.replace("* two", existing_body)
    releases = [{"tag": "v0.2.0", "date": "2026-09-15T10:00:00Z", "body": gh_body}]
    out = changelog_from_releases(text, releases)
    assert extract_changelog(out, "v0.2.0") == expected


@pytest.mark.parametrize(
    "section_name,tag,expected",
    [
        ("0.2.0", "v0.2.0", "v0.2.0"),  # larger text wins
        ("v0.2.0", "0.2.0", "v0.2.0"),  # larger text wins
        ("v0.2.0", "v0.2.0", "v0.2.0"),
    ],
)
def test_changelog_from_releases_picks_larger_version_text(section_name, tag, expected):
    text = SAMPLE.replace("## [v0.2.0]", f"## [{section_name}]")
    releases = [{"tag": tag, "date": "2026-09-15T10:00:00Z", "body": "* gh"}]
    out = changelog_from_releases(text, releases)
    assert f"## [{expected}]" in out


# ===== format / canonical rendering


MESSY = """# Changelog

Preamble.



# [unreleased]


* wip


* more wip

### [v0.1.0] - 01-01-2026



* one

## Sub-header

# Another header
"""

CANONICAL = """# Changelog

Preamble.


## [unreleased]

* wip

* more wip


## [v0.1.0] - 01-01-2026

* one

### Sub-header

### Another header
"""


def test_parse_detects_hash_variants():
    preamble, sections = parse_changelog(MESSY)
    assert preamble.startswith("# Changelog")
    assert [s.name for s in sections] == ["unreleased", "v0.1.0"]
    assert sections[1].date == "01-01-2026"


def test_format_changelog_normalizes():
    assert format_changelog(MESSY) == CANONICAL


def test_format_changelog_preserves_section_order():
    # format does not sort; it only normalizes.
    text = "## [v0.1.0]\n\n* one\n\n\n\n## [v0.2.0]\n\n* two\n"
    assert format_changelog(text) == "## [v0.1.0]\n\n* one\n\n\n## [v0.2.0]\n\n* two\n"


def test_render_empty_section_two_blank_line_gap():
    out = render_changelog("", [Section("v0.2.0"), Section("v0.1.0", body="* one")])
    assert out == "## [v0.2.0]\n\n\n## [v0.1.0]\n\n* one\n"


def test_render_collapses_excess_blank_lines_within_section():
    out = render_changelog("", [Section("v0.1.0", body="* a\n\n\n\n* b")])
    assert out == "## [v0.1.0]\n\n* a\n\n* b\n"


def test_format_changelog_empty():
    assert format_changelog("") == ""


# ===== gh release links in section headers

REPO_URL = "https://github.com/acme/widgets"


def release_link(v: str) -> str:
    return f"[{v}]({REPO_URL}/releases/tag/{v})"


def test_parse_strips_release_links():
    text = f"## {release_link('v0.2.0')} - 01-02-2026\n\n* two\n"
    _preamble, sections = parse_changelog(text)
    assert sections[0].name == "v0.2.0"
    assert sections[0].date == "01-02-2026"
    assert sections[0].link == f"{REPO_URL}/releases/tag/v0.2.0"


def test_render_keeps_existing_link_without_repo_url():
    s = Section("v0.2.0", date="01-02-2026", body="* two")
    s.link = f"{REPO_URL}/releases/tag/v0.2.0"
    out = render_changelog("", [s])  # no repo_url: keep link, create none
    assert f"## {release_link('v0.2.0')} - 01-02-2026" in out


def test_format_changelog_without_repo_url_never_creates_links():
    # Existing link is preserved as-is ...
    linked = f"## {release_link('v0.2.0')} - 01-02-2026\n\n* two\n"
    assert format_changelog(linked) == linked
    # ... and an unlinked version section stays unlinked.
    plain = "## [v0.2.0] - 01-02-2026\n\n* two\n"
    assert format_changelog(plain) == plain


def test_render_links_version_sections_only():
    sections = [
        Section("unreleased", body="* wip"),
        Section("v0.2.0", date="01-02-2026", body="* two"),
    ]
    out = render_changelog("# Changelog\n\n", sections, repo_url=REPO_URL)
    assert "## [unreleased]\n" in out  # not a version: no link
    assert f"## {release_link('v0.2.0')} - 01-02-2026" in out


def test_format_changelog_with_links_is_idempotent():
    text = (
        "# Changelog\n\n\n"
        "## [unreleased]\n\n* wip\n\n\n"
        f"## {release_link('v0.2.0')} - 01-02-2026\n\n* two\n"
    )
    assert format_changelog(text, repo_url=REPO_URL) == text


def test_bump_changelog_links_version_sections():
    out = bump_changelog(SAMPLE, "v0.3.0", "* notes", today=TODAY, repo_url=REPO_URL)
    assert f"## {release_link('v0.3.0')} - {TODAY}" in out
    # Existing version sections get linked too.
    assert f"## {release_link('v0.2.0')} - 01-02-2026" in out
    # [unreleased] is consumed by the bump and has no link anyway.
    assert "## [unreleased]" not in out


def test_changelog_from_releases_links_version_sections():
    releases = [{"tag": "v0.3.0", "date": "2026-10-01T10:00:00Z", "body": "* three"}]
    out = changelog_from_releases(SAMPLE, releases, repo_url=REPO_URL)
    assert f"## {release_link('v0.3.0')} - 01-10-2026" in out
