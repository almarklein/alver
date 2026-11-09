# simpleversion

Version management and release notes made easy.

```
usage: simpleversion [-h] {version,bump,notes,changelog-from-gh,changelog-to-gh} ...

Commands to easily manage releases and changelog

* Run `simpleversion bump vx.y.z`.
* Edit the changelog as needed.
* Commit and create a PR for this version bump.
* When merged, push a tag to roll the release.

positional arguments:
  {version,bump,notes,changelog-from-gh,changelog-to-gh}
    version             Print the current project version from _version.py.
    bump                Bump the version and add a changelog section with gh-generated release notes.
    notes               Print the release notes for a version from CHANGELOG.md.
    changelog-from-gh   Create/update CHANGELOG.md sections from the GitHub releases of this repo.
    changelog-to-gh     Update the release notes of all gh releases that have a section in CHANGELOG.md.

options:
  -h, --help            show this help message and exit
```

