import subprocess
import types

from alver.version import (
    get_detailed_version,
    get_detailed_version_of_lib,
    get_version_tuple,
)


def make_git_repo(tmp_path, *, tag=None, extra_commit=False):
    """Create a git repo with a mylib package; return (repo, init_file)."""
    repo = tmp_path / "repo"
    pkg = repo / "mylib"
    pkg.mkdir(parents=True)
    init_file = pkg / "__init__.py"
    init_file.write_text('__version__ = "0.1.0"\n')

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Tester")
    git("add", "-A")
    git("commit", "-qm", "init")
    if tag:
        git("tag", tag)
    if extra_commit:
        (repo / "f.txt").write_text("x")
        git("add", "-A")
        git("commit", "-qm", "change")
    return repo, init_file


def make_module(version=None, file=None, version_info=None):
    module = types.ModuleType("mylib")
    if version is not None:
        module.__version__ = version
    if version_info is not None:
        module.version_info = version_info
    if file is not None:
        module.__file__ = str(file)
    return module


# ===== get_version_tuple


def test_get_version_tuple():
    assert get_version_tuple("1.2.3") == (1, 2, 3)
    assert get_version_tuple("1.2.3.post4+gabc1") == (1, 2, 3, "post", 4, "+", "gabc1")
    assert get_version_tuple("1.0.0rc1") == (1, 0, "0rc1")


# ===== get_detailed_version


def test_get_detailed_version_with_tag_and_commit(tmp_path):
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0", extra_commit=True)
    v = get_detailed_version("0.1.0", str(init_file))
    assert v.startswith("0.1.0.post1+g")


def test_get_detailed_version_clean_tagged_repo(tmp_path):
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0")
    assert get_detailed_version("0.1.0", str(init_file)) == "0.1.0"


def test_get_detailed_version_outside_git_repo(tmp_path):
    f = tmp_path / "mylib" / "__init__.py"
    f.parent.mkdir(parents=True)
    f.write_text('__version__ = "2.3.4"\n')
    assert get_detailed_version("2.3.4", str(f)) == "2.3.4"


# ===== get_detailed_version_of_lib


def test_get_detailed_version_of_lib_with_git(tmp_path):
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0", extra_commit=True)
    module = make_module("0.1.0", init_file)
    v = get_detailed_version_of_lib(module)
    assert v.startswith("0.1.0.post1+g")
    # The module itself is not modified.
    assert module.__version__ == "0.1.0"
    assert not hasattr(module, "version_info")


def test_get_detailed_version_of_lib_clean_tagged_repo(tmp_path):
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0")
    module = make_module("0.1.0", init_file)
    assert get_detailed_version_of_lib(module) == "0.1.0"


def test_get_detailed_version_of_lib_outside_git_repo(tmp_path):
    f = tmp_path / "mylib" / "__init__.py"
    f.parent.mkdir(parents=True)
    f.write_text('__version__ = "2.3.4"\n')
    module = make_module("2.3.4", f)
    assert get_detailed_version_of_lib(module) == "2.3.4"


def test_get_detailed_version_of_lib_without_file():
    # No __file__: no git refinement, just the plain version.
    module = make_module("1.0.0")
    assert get_detailed_version_of_lib(module) == "1.0.0"


def test_get_detailed_version_of_lib_falls_back_to_version_info(tmp_path):
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0", extra_commit=True)
    module = make_module(file=init_file, version_info=(0, 1, 0))  # no __version__
    v = get_detailed_version_of_lib(module)
    assert v.startswith("0.1.0.post1+g")


def test_get_detailed_version_of_lib_version_info_without_git(tmp_path):
    f = tmp_path / "mylib" / "__init__.py"
    f.parent.mkdir(parents=True)
    module = make_module(file=f, version_info=(2, 3, 4))
    assert get_detailed_version_of_lib(module) == "2.3.4"


def test_get_detailed_version_of_lib_without_any_version_returns_none(tmp_path):
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0")
    # Neither __version__ nor version_info: nothing to base the version on.
    assert get_detailed_version_of_lib(make_module(file=init_file)) is None
    assert get_detailed_version_of_lib(make_module()) is None


# ===== already-refined __version__ (set by get_detailed_version earlier)


def test_get_detailed_version_of_lib_already_refined_version(tmp_path):
    # A lib that already set __version__ via get_detailed_version must not get
    # labels or .post repeated when passed through get_detailed_version_of_lib.
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0", extra_commit=True)
    module = make_module(file=init_file)
    module.__version__ = get_detailed_version("0.1.0", str(init_file))
    assert module.__version__.startswith("0.1.0.post1+g")
    v = get_detailed_version_of_lib(module)
    assert v == module.__version__
    assert v.count("post") == 1
    assert v.count("+") == 1


def test_get_detailed_version_of_lib_already_refined_dirty(tmp_path):
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0", extra_commit=True)
    init_file.write_text('__version__ = "0.1.0"  # modified, uncommitted\n')
    module = make_module(file=init_file)
    module.__version__ = get_detailed_version("0.1.0", str(init_file))
    assert module.__version__.endswith(".dirty")
    v = get_detailed_version_of_lib(module)
    assert v == module.__version__
    assert v.count("dirty") == 1
    assert v.count("+") == 1


def test_get_detailed_version_of_lib_refined_version_without_git(tmp_path):
    # E.g. installed from an sdist: no git repo, the refined __version__ is
    # returned as-is, not mangled or duplicated.
    f = tmp_path / "mylib" / "__init__.py"
    f.parent.mkdir(parents=True)
    module = make_module("0.1.0.post4+gabcdef1.dirty", f)
    assert get_detailed_version_of_lib(module) == "0.1.0.post4+gabcdef1.dirty"


def test_get_detailed_version_of_lib_post_only_version(tmp_path):
    # A bare ".postN" suffix (no labels) is stripped too, not repeated.
    _repo, init_file = make_git_repo(tmp_path, tag="v0.1.0", extra_commit=True)
    module = make_module("0.1.0.post4", init_file)
    v = get_detailed_version_of_lib(module)
    assert v.startswith("0.1.0.post1+g")  # current git state wins
    assert v.count("post") == 1
