import logging
import subprocess
from pathlib import Path


def get_version_tuple(v: str) -> tuple:
    """Given a version string, produce a version tuple, where integer parts are actual integers."""

    # Create raw parts
    raw_parts = []
    sortable, _, labels = v.partition("+")
    raw_parts.extend(sortable.split("."))
    if labels:
        raw_parts.append("+")
        raw_parts.extend(labels.split("."))

    # Turn integer parts into actual integers
    parts = []
    for part in raw_parts:
        if not part:
            pass
        elif part.startswith("post"):
            try:
                parts.extend(["post", int(part[4:])])
            except ValueError:
                parts.append(part)
        else:
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(part)

    return tuple(parts)


def get_detailed_version_of_lib(module) -> str | None:
    """Get the detailed version of a library module, based on its git history.

    Uses the module's ``__version__`` as the base version and its ``__file__``
    to locate the repository (see ``get_detailed_version``).
    Returns the detailed version string.
    """
    # Extract version
    version = None
    try:
        version = module.__version__
    except AttributeError:
        pass
    if version is None:
        try:
            version = ".".join(str(i) for i in module.version_info)
        except AttributeError:
            pass

    # Try get more details
    filename = getattr(module, "__file__", None)
    if version and filename:
        version = get_detailed_version(version, filename)

    return version


def get_detailed_version(version: str, filename: str):
    """Get a more detailed version string, based on the git tags and history."""

    # Get path to the library dir, assume that filename is the dir or a file directly in that dir
    path = Path(filename)
    if path.name.endswith(".py"):
        path = path.parent

    # Get repository dir from that: walk up until a .git dir is found
    # (by default the repo is exactly one directory up).
    repo_dir = path if path.is_dir() else path.parent
    while repo_dir is not None and not repo_dir.joinpath(".git").is_dir():
        repo_dir = repo_dir.parent if repo_dir.parent != repo_dir else None

    # Get sensible project name, only for reporting warnings and errors
    project_name = path.name
    if project_name == "src" and repo_dir is not None:
        project_name = repo_dir.name

    # If the repo_dir is indeed a git repo, do our thing, otherwise, just return given version
    if repo_dir and repo_dir.joinpath(".git").is_dir():
        base_version = version.partition("+")[0].partition(".post")[0]  # Sanity
        getter = DetailedVersionGetter(base_version, project_name, repo_dir)
        return getter.get_version()
    else:
        return version


class DetailedVersionGetter:
    def __init__(self, base_version: str, project_name: str, repo_dir: Path):
        self.base_version = base_version
        self.project_name = project_name
        self.repo_dir = repo_dir
        self.logger = logging.getLogger(project_name)

    def warning(self, m: str) -> None:
        self.logger.warning(m)

    def get_version(self) -> str:
        try:
            if self.repo_dir:
                release, post, tag, dirty = self.get_version_info_from_git()
                result = self.get_extended_version(release, post, tag, dirty)

                # Warn if release does not match base_version.
                # Can happen between bumping and tagging. And also when merging a
                # version bump into a working branch, because we use --first-parent.
                if release and release != self.base_version:
                    release2, _post, _tag, _dirty = self.get_version_info_from_git(
                        first_parent=False
                    )
                    if release2 != self.base_version:
                        self.warning(
                            f"{self.project_name} version from git ({release})"
                            f" and __version__ ({self.base_version}) don't match."
                        )

                return result

        except Exception as err:
            self.warning(f"Error getting refined version: {err}")

        return self.base_version

    def get_extended_version(
        self, release: str, post: str, tag: str, dirty: str
    ) -> str:
        # Start version string (__version__ string is leading).
        version = self.base_version
        labels = []

        if release and release != self.base_version:
            pre_label = "from_tag_" + release.replace(".", "_")
            labels = [pre_label, f"post{post}", tag, dirty]
        elif post and post != "0":
            version += f".post{post}"
            labels = [tag, dirty]
        elif dirty:
            labels = [tag, dirty]
        else:
            # If not post and not dirty, show 'clean' version without git tag.
            pass

        # Compose final version (remove empty labels, e.g. when not dirty).
        # Everything after the '+' is not sortable (does not get in version_info).
        label_str = ".".join(label for label in labels if label)
        if label_str:
            version += "+" + label_str
        return version

    def get_version_info_from_git(
        self, *, first_parent: bool = True
    ) -> tuple[str, str, str, str]:
        """
        Get (release, post, tag, dirty) from Git.

        With `release` the version number from the latest tag, `post` the
        number of commits since that tag, `tag` the git hash, and `dirty` a string
        that is either empty or says 'dirty'.
        """
        # Call out to Git.
        command = ["git", "describe", "--long", "--always", "--tags", "--dirty"]
        if first_parent:
            command.append("--first-parent")
        try:
            p = subprocess.run(
                command, check=False, cwd=self.repo_dir, capture_output=True
            )
        except Exception as e:
            self.warning(f"Could not get {self.project_name} version: {e}")
            p = None

        # Parse the result into parts.
        if p is None:
            parts = ("", "", "unknown")
        else:
            output = p.stdout.decode(errors="ignore")
            if p.returncode:
                stderr = p.stderr.decode(errors="ignore")
                self.warning(
                    f"Could not get {self.project_name} version.\n\nstdout: "
                    + output
                    + "\n\nstderr: "
                    + stderr
                )
                parts = ("", "", "unknown")
            else:
                parts = output.strip().lstrip("v").split("-")
                if len(parts) <= 2:
                    # No tags (and thus no post). Only git hash and maybe 'dirty'.
                    parts = ("", "", *parts)

        # Return unpacked parts.
        release = parts[0]
        post = parts[1]
        tag = parts[2]
        dirty = "dirty" if len(parts) > 3 else ""
        return release, post, tag, dirty
