import os
import subprocess
import sys
from pathlib import Path

import pytest

from alver import cli

REMOTE = "git@github.com:acme/widgets.git"
REPO_URL = "https://github.com/acme/widgets"


def release_link(v: str) -> str:
    """The linked section header name for version v, as written by alver."""
    return f"[{v}]({REPO_URL}/releases/tag/{v})"


CHANGELOG = """# Changelog

Preamble.


## [unreleased]

* wip


## [v0.1.0] - 01-01-2026

* one
"""

# A fake gh executable: answers the generate-notes and releases endpoints.
FAKE_GH = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if any("generate-notes" in a for a in args):
    print("* gh generated note")
elif any("/releases" in a for a in args):
    print(json.dumps({"id": 2, "tag": "v0.2.0", "date": "2026-09-15T10:00:00Z", "body": "* gh release b"}))
    print(json.dumps({"id": 1, "tag": "v0.1.0", "date": "2026-08-01T10:00:00Z", "body": "* gh release a"}))
else:
    sys.exit(1)
"""

# A fake gh that also answers PATCH (release update) calls and logs them.
FAKE_GH_PATCH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
log = os.environ.get("FAKE_GH_LOG", "")
if "PATCH" in args:
    endpoint = args[args.index("-X") + 2]
    body = args[args.index("-f") + 1].split("=", 1)[1] if "-f" in args else ""
    with open(log, "a") as f:
        f.write("PATCH %s body=%r\\n" % (endpoint, body))
    print(json.dumps({"id": 2}))
    sys.exit(0)
if any("/releases" in a for a in args):
    print(json.dumps({"id": 2, "tag": "0.2.0", "date": "2026-09-15T10:00:00Z", "body": "* old"}))
    print(json.dumps({"id": 1, "tag": "v0.1.0", "date": "2026-08-01T10:00:00Z", "body": "* gh release a"}))
    sys.exit(0)
sys.exit(1)
"""


PYPROJECT = """\
[project]
name = "widgets"
version = "0.1.0"
requires-python = ">=3.10"

[tool.other]
version = "9.9.9"
"""

DYNAMIC_PYPROJECT = """\
[project]
name = "widgets"
dynamic = ["version"]
"""


def make_repo(
    tmp_path,
    *,
    version="0.1.0",
    version_rel="pkg/_version.py",
    changelog=None,
    remote=REMOTE,
    version_text=None,
):
    """Create a git repo in tmp_path with a version file and optional CHANGELOG.md."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Tester")
    git("remote", "add", "origin", remote)
    version_file = repo / version_rel
    version_file.parent.mkdir(parents=True, exist_ok=True)
    if version_text is None:
        version_text = f'__version__ = "{version}"\n'
    version_file.write_text(version_text)
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog)
    git("add", "-A")
    git("commit", "-qm", "init")
    return repo


@pytest.fixture
def install_fake_gh(tmp_path, monkeypatch):
    """Factory: put a fake gh executable (given script) first on PATH."""

    def _install(script):
        bindir = tmp_path / "bin"
        bindir.mkdir(exist_ok=True)
        gh = bindir / "gh"
        gh.write_text(script)
        gh.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        return bindir

    return _install


@pytest.fixture
def fake_gh(install_fake_gh):
    return install_fake_gh(FAKE_GH)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = make_repo(tmp_path, changelog=CHANGELOG)
    monkeypatch.chdir(r)
    return r


# ===== help / no command


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 2
    out = capsys.readouterr().out
    assert "usage:" in out
    for cmd in (
        "bump",
        "notes",
        "version",
        "gitversion",
        "format",
        "changelog-from-gh",
        "changelog-to-gh",
    ):
        assert cmd in out


def test_help_shows_multiline_description(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # RawDescriptionHelpFormatter keeps the docstring's newlines intact.
    assert "\n* Run `alver bump" in out


# ===== version


def test_version_command(repo, capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_version_command_outside_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["version"])


# ===== gitversion


def test_gitversion_with_tag_and_commits(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "tag", "v0.1.0"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"
    assert cli.main(["gitversion"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("0.1.0.post1+g")  # one commit since tag v0.1.0


def test_gitversion_without_tags(repo, capsys):
    # No tags in the repo: the detailed version is just the plain version.
    assert cli.main(["gitversion"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_gitversion_with_init_py(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, version_rel="pkg/__init__.py")
    subprocess.run(["git", "tag", "v0.1.0"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    assert cli.main(["gitversion"]) == 0
    assert capsys.readouterr().out.strip().startswith("0.1.0.post1+g")


def test_gitversion_with_pyproject(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, version_rel="pyproject.toml", version_text=PYPROJECT)
    subprocess.run(["git", "tag", "v0.1.0"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    assert cli.main(["gitversion"]) == 0
    assert capsys.readouterr().out.strip().startswith("0.1.0.post1+g")


def test_gitversion_outside_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["gitversion"])


def test_python_m_alver_version(repo):
    project_root = Path(__file__).resolve().parent.parent
    env = dict(os.environ, PYTHONPATH=str(project_root))
    p = subprocess.run(
        [sys.executable, "-m", "alver", "version"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )
    assert p.returncode == 0
    assert p.stdout.strip() == "0.1.0"


def test_version_command_with_init_py(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, version_rel="pkg/__init__.py")
    monkeypatch.chdir(repo)
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_version_command_with_pyproject(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, version_rel="pyproject.toml", version_text=PYPROJECT)
    monkeypatch.chdir(repo)
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


# ===== bump


def test_bump_creates_changelog_and_updates_version(
    tmp_path, monkeypatch, fake_gh, capsys
):
    repo = make_repo(tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(repo)
    assert cli.main(["bump", "v0.2.0"]) == 0
    assert '__version__ = "0.2.0"' in (repo / "pkg/_version.py").read_text()
    changelog = (repo / "CHANGELOG.md").read_text()
    assert f"## {release_link('v0.2.0')} - " in changelog
    assert "* gh generated note" in changelog


def test_bump_merges_unreleased(repo, fake_gh):
    assert cli.main(["bump", "v0.2.0"]) == 0
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "[unreleased]" not in changelog
    section = changelog.split(f"## {release_link('v0.2.0')}")[1]
    assert "* wip" in section and "* gh generated note" in section


def test_bump_invalid_version(repo, fake_gh):
    with pytest.raises(SystemExit):
        cli.main(["bump", "not-a-version"])


def test_bump_updates_init_py(tmp_path, monkeypatch, fake_gh):
    repo = make_repo(tmp_path, version_rel="pkg/__init__.py", changelog=CHANGELOG)
    monkeypatch.chdir(repo)
    assert cli.main(["bump", "v0.2.0"]) == 0
    assert '__version__ = "0.2.0"' in (repo / "pkg/__init__.py").read_text()


def test_bump_updates_pyproject_project_version(tmp_path, monkeypatch, fake_gh):
    repo = make_repo(
        tmp_path,
        version_rel="pyproject.toml",
        version_text=PYPROJECT,
        changelog=CHANGELOG,
    )
    monkeypatch.chdir(repo)
    assert cli.main(["bump", "v0.2.0"]) == 0
    text = (repo / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in text
    # Other tables and keys are left alone.
    assert 'version = "9.9.9"' in text
    assert 'requires-python = ">=3.10"' in text


def test_bump_falls_back_to_git_log_without_gh(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, changelog=CHANGELOG)
    subprocess.run(["git", "tag", "v0.1.0"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "special change"], cwd=repo, check=True)
    monkeypatch.chdir(repo)

    real_run = subprocess.run

    def no_gh(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            raise FileNotFoundError("gh")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", no_gh)
    assert cli.main(["bump", "v0.2.0"]) == 0
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "* special change" in changelog


# ===== notes


def test_notes(repo, capsys):
    assert cli.main(["notes", "v0.1.0"]) == 0
    assert capsys.readouterr().out.strip() == "* one"


def test_notes_missing_version(repo):
    with pytest.raises(SystemExit):
        cli.main(["notes", "v9.9.9"])


# ===== changelog-from-gh


def test_changelog_from_gh(repo, fake_gh):
    # Explicit '*' processes all releases (the old default behavior).
    assert cli.main(["changelog-from-gh", "*"]) == 0
    changelog = (repo / "CHANGELOG.md").read_text()
    # unreleased on top, then v0.2.0 (from gh), then v0.1.0 (body updated from gh)
    assert (
        changelog.index("## [unreleased]")
        < changelog.index(f"## {release_link('v0.2.0')}")  # new section: linked
        < changelog.index("## [v0.1.0]")  # existing section: left as-is
    )
    assert "* gh release b" in changelog
    assert "* gh release a" in changelog
    assert "* wip" in changelog


def test_changelog_from_gh_single_version(repo, fake_gh):
    assert cli.main(["changelog-from-gh", "v0.2.0"]) == 0
    changelog = (repo / "CHANGELOG.md").read_text()
    assert f"## {release_link('v0.2.0')}" in changelog
    assert "* gh release b" in changelog
    # The v0.1.0 release was not processed: its hand-written body is kept and
    # its header is left as-is (no link added to existing sections).
    v010_section = changelog.split("## [v0.1.0]")[1]
    assert "* one" in v010_section
    assert "* gh release a" not in changelog


def test_changelog_from_gh_version_without_v_prefix(repo, fake_gh):
    # "0.2.0" matches the gh release tagged "v0.2.0".
    assert cli.main(["changelog-from-gh", "0.2.0"]) == 0
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "* gh release b" in changelog
    assert "* gh release a" not in changelog


def test_changelog_from_gh_partial_wildcard(repo, fake_gh):
    assert cli.main(["changelog-from-gh", "v0.2.*"]) == 0
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "* gh release b" in changelog
    assert "* gh release a" not in changelog


def test_changelog_from_gh_unknown_version_adds_no_section(repo, fake_gh):
    assert cli.main(["changelog-from-gh", "v9.9.9"]) == 0
    after = (repo / "CHANGELOG.md").read_text()
    assert "v9.9.9" not in after
    # Existing sections are preserved as-is (no new release links added).
    assert "## [unreleased]" in after
    assert "## [v0.1.0] - 01-01-2026" in after
    assert "* wip" in after and "* one" in after


def test_changelog_from_gh_creates_file(tmp_path, monkeypatch, fake_gh):
    repo = make_repo(tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(repo)
    assert cli.main(["changelog-from-gh", "*"]) == 0
    assert (repo / "CHANGELOG.md").is_file()


def test_changelog_from_gh_without_gh_executable(repo, monkeypatch):
    real_run = subprocess.run

    def no_gh(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            raise FileNotFoundError("gh")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", no_gh)
    with pytest.raises(SystemExit):
        cli.main(["changelog-from-gh", "*"])


# ===== format


MESSY_CHANGELOG = (
    "# Changelog\n\n\n## [unreleased]\n\n\n* wip\n\n\n"
    "### [v0.1.0] - 01-01-2026\n\n* one\n\n## Sub\n"
)


def test_format_command(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, changelog=MESSY_CHANGELOG)
    monkeypatch.chdir(repo)
    assert cli.main(["format"]) == 0
    out = (repo / "CHANGELOG.md").read_text()
    # format does not create release links (bump / changelog-from-gh do).
    assert out == (
        "# Changelog\n\n\n"
        "## [unreleased]\n\n* wip\n\n\n"
        "## [v0.1.0] - 01-01-2026\n\n* one\n\n### Sub\n"
    )
    assert "Formatted CHANGELOG.md" in capsys.readouterr().out


def test_format_command_preserves_existing_links(tmp_path, monkeypatch):
    changelog = f"# Changelog\n\n\n## {release_link('v0.1.0')} - 01-01-2026\n\n* one\n"
    repo = make_repo(tmp_path, changelog=changelog)
    monkeypatch.chdir(repo)
    assert cli.main(["format"]) == 0
    out = (repo / "CHANGELOG.md").read_text()
    assert f"## {release_link('v0.1.0')} - 01-01-2026" in out


def test_format_command_without_github_remote_adds_no_links(tmp_path, monkeypatch):
    repo = make_repo(
        tmp_path,
        changelog=MESSY_CHANGELOG,
        remote="https://gitlab.com/acme/widgets.git",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["format"]) == 0
    out = (repo / "CHANGELOG.md").read_text()
    assert "## [v0.1.0] - 01-01-2026" in out  # plain header, no link
    assert "](http" not in out


def test_format_command_requires_changelog(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit):
        cli.main(["format"])


# ===== changelog-to-gh


def test_changelog_to_gh(tmp_path, monkeypatch, install_fake_gh, capsys):
    log = tmp_path / "gh.log"
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    install_fake_gh(FAKE_GH_PATCH)
    changelog = (
        "# Changelog\n\n"
        "## [unreleased]\n\n* wip\n\n"
        "## [v0.2.0] - 01-09-2026\n\n* two notes\n\n"
        "## [v0.5.0] - 01-10-2026\n\n* no release for this\n"
    )
    repo = make_repo(tmp_path, changelog=changelog)
    monkeypatch.chdir(repo)
    # Explicit '*' processes all sections (the old default behavior).
    assert cli.main(["changelog-to-gh", "*"]) == 0
    calls = log.read_text()
    # Section [v0.2.0] matches the release tagged "0.2.0"; the larger text
    # ("v0.2.0") is picked as the tag for the PATCH.
    assert "releases/tags/v0.2.0" in calls
    assert "body='* two notes'" in calls
    # [unreleased], the unmatched [v0.5.0], and the section-less release are not pushed.
    assert "v0.5.0" not in calls
    assert "unreleased" not in calls
    assert "v0.1.0" not in calls
    out = capsys.readouterr().out
    assert "Updated release v0.2.0" in out
    assert "Skipped [v0.5.0]" in out


def test_changelog_to_gh_single_version(tmp_path, monkeypatch, install_fake_gh, capsys):
    log = tmp_path / "gh.log"
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    install_fake_gh(FAKE_GH_PATCH)
    changelog = (
        "# Changelog\n\n"
        "## [v0.2.0] - 01-09-2026\n\n* two notes\n\n"
        "## [v0.5.0] - 01-10-2026\n\n* no release for this\n"
    )
    repo = make_repo(tmp_path, changelog=changelog)
    monkeypatch.chdir(repo)
    assert cli.main(["changelog-to-gh", "v0.2.0"]) == 0
    calls = log.read_text()
    assert "releases/tags/v0.2.0" in calls
    out = capsys.readouterr().out
    assert "Updated release v0.2.0" in out
    # [v0.5.0] is filtered out by the version argument, not even reported.
    assert "v0.5.0" not in out


def test_changelog_to_gh_version_without_matching_release(
    tmp_path, monkeypatch, install_fake_gh, capsys
):
    log = tmp_path / "gh.log"
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    install_fake_gh(FAKE_GH_PATCH)
    changelog = (
        "# Changelog\n\n"
        "## [v0.2.0] - 01-09-2026\n\n* two notes\n\n"
        "## [v0.5.0] - 01-10-2026\n\n* no release for this\n"
    )
    repo = make_repo(tmp_path, changelog=changelog)
    monkeypatch.chdir(repo)
    assert cli.main(["changelog-to-gh", "v0.5.0"]) == 0
    # No PATCH calls were made.
    assert not log.exists() or log.read_text() == ""
    out = capsys.readouterr().out
    assert "Updated release" not in out
    assert "Skipped [v0.5.0]" in out
    # [v0.2.0] was filtered out by the version argument.
    assert "v0.2.0" not in out


def test_changelog_to_gh_requires_changelog(tmp_path, monkeypatch, fake_gh):
    repo = make_repo(tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit):
        cli.main(["changelog-to-gh", "*"])


# ===== required version argument / help usage


@pytest.mark.parametrize("cmd", ["changelog-from-gh", "changelog-to-gh"])
def test_changelog_commands_require_version(cmd, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([cmd])
    assert exc.value.code == 2  # argparse error: missing required argument
    assert "version" in capsys.readouterr().err


@pytest.mark.parametrize(
    "cmd,usage",
    [
        ("bump", "usage: alver bump [-h] version"),
        ("notes", "usage: alver notes [-h] version"),
        ("changelog-from-gh", "usage: alver changelog-from-gh [-h] version"),
        ("changelog-to-gh", "usage: alver changelog-to-gh [-h] version"),
    ],
)
def test_command_help_specifies_version_argument(cmd, usage, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([cmd, "-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert usage in out
    assert "[version]" not in out.splitlines()[0]  # required, not optional


# ===== helpers


@pytest.mark.parametrize(
    "url,expected",
    [
        ("git@github.com:acme/widgets.git", ("acme", "widgets")),
        ("https://github.com/acme/widgets.git", ("acme", "widgets")),
        ("https://github.com/acme/widgets", ("acme", "widgets")),
        ("ssh://git@github.com/acme/widgets.git", ("acme", "widgets")),
    ],
)
def test_get_owner_repo(tmp_path, url, expected):
    repo = make_repo(tmp_path, remote=url)
    assert cli.get_owner_repo(repo) == expected


def test_find_version_file_prefers_shallow_and_skips_venv(tmp_path):
    repo = make_repo(tmp_path, version_rel="pkg/_version.py")
    venv_version = repo / ".venv" / "lib" / "_version.py"
    venv_version.parent.mkdir(parents=True)
    venv_version.write_text('__version__ = "9.9.9"\n')
    found = cli.find_version_file(repo)
    assert found == repo / "pkg" / "_version.py"


def test_find_version_file_missing(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "pkg" / "_version.py").unlink()
    with pytest.raises(SystemExit):
        cli.find_version_file(repo)


def test_find_version_file_init_py(tmp_path):
    repo = make_repo(tmp_path, version_rel="pkg/__init__.py")
    assert cli.find_version_file(repo) == repo / "pkg" / "__init__.py"


def test_find_version_file_ignores_init_py_without_version_assignment(tmp_path):
    repo = make_repo(tmp_path, version_rel="pkg/_version.py")
    (repo / "pkg" / "__init__.py").write_text("from ._version import __version__\n")
    assert cli.find_version_file(repo) == repo / "pkg" / "_version.py"


def test_find_version_file_prefers_shallowest_pyproject(tmp_path):
    repo = make_repo(tmp_path, version_rel="pkg/_version.py")
    (repo / "pyproject.toml").write_text(PYPROJECT)
    assert cli.find_version_file(repo) == repo / "pyproject.toml"


def test_find_version_file_ignores_dynamic_pyproject(tmp_path):
    repo = make_repo(tmp_path, version_rel="pkg/_version.py")
    (repo / "pyproject.toml").write_text(DYNAMIC_PYPROJECT)
    assert cli.find_version_file(repo) == repo / "pkg" / "_version.py"


def test_set_version_in_file_pyproject_scopes_to_project_table(tmp_path):
    f = tmp_path / "pyproject.toml"
    f.write_text(PYPROJECT)
    assert cli.set_version_in_file(f, "1.2.3") == "0.1.0"
    text = f.read_text()
    assert 'version = "1.2.3"' in text
    assert 'version = "9.9.9"' in text  # [tool.other] untouched


def test_load_version_pyproject(tmp_path):
    f = tmp_path / "pyproject.toml"
    f.write_text(PYPROJECT)
    assert cli.load_version(f) == "0.1.0"
