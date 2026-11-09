import os
import subprocess

import pytest

from simpleversion import cli

REMOTE = "git@github.com:acme/widgets.git"

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


def make_repo(
    tmp_path,
    *,
    version="0.1.0",
    version_rel="pkg/_version.py",
    changelog=None,
    remote=REMOTE,
):
    """Create a git repo in tmp_path with a _version.py and optional CHANGELOG.md."""
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
    version_file.write_text(f'__version__ = "{version}"\n')
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


# ===== version


def test_version_command(repo, capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_version_command_outside_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["version"])


# ===== bump


def test_bump_creates_changelog_and_updates_version(
    tmp_path, monkeypatch, fake_gh, capsys
):
    repo = make_repo(tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(repo)
    assert cli.main(["bump", "v0.2.0"]) == 0
    assert '__version__ = "0.2.0"' in (repo / "pkg/_version.py").read_text()
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "## [v0.2.0] - " in changelog
    assert "* gh generated note" in changelog


def test_bump_merges_unreleased(repo, fake_gh):
    assert cli.main(["bump", "v0.2.0"]) == 0
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "[unreleased]" not in changelog
    section = changelog.split("## [v0.2.0]")[1]
    assert "* wip" in section and "* gh generated note" in section


def test_bump_invalid_version(repo, fake_gh):
    with pytest.raises(SystemExit):
        cli.main(["bump", "not-a-version"])


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


# ===== extract


def test_extract(repo, capsys):
    assert cli.main(["extract", "v0.1.0"]) == 0
    assert capsys.readouterr().out.strip() == "* one"


def test_extract_missing_version(repo):
    with pytest.raises(SystemExit):
        cli.main(["extract", "v9.9.9"])


# ===== changelog-from-gh


def test_changelog_from_gh(repo, fake_gh):
    assert cli.main(["changelog-from-gh"]) == 0
    changelog = (repo / "CHANGELOG.md").read_text()
    # unreleased on top, then v0.2.0 (from gh), then v0.1.0 (body updated from gh)
    assert (
        changelog.index("## [unreleased]")
        < changelog.index("## [v0.2.0]")
        < changelog.index("## [v0.1.0]")
    )
    assert "* gh release b" in changelog
    assert "* gh release a" in changelog
    assert "* wip" in changelog


def test_changelog_from_gh_creates_file(tmp_path, monkeypatch, fake_gh):
    repo = make_repo(tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(repo)
    assert cli.main(["changelog-from-gh"]) == 0
    assert (repo / "CHANGELOG.md").is_file()


def test_changelog_from_gh_without_gh_executable(repo, monkeypatch):
    real_run = subprocess.run

    def no_gh(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            raise FileNotFoundError("gh")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", no_gh)
    with pytest.raises(SystemExit):
        cli.main(["changelog-from-gh"])


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
    assert cli.main(["changelog-to-gh"]) == 0
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


def test_changelog_to_gh_requires_changelog(tmp_path, monkeypatch, fake_gh):
    repo = make_repo(tmp_path)  # no CHANGELOG.md
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit):
        cli.main(["changelog-to-gh"])


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
