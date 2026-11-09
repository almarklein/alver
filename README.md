# alver

Easy management of versions, releases and changelog.

Alver is a CLI tool that promotes a simple, no-magic, release flow.


## The alver release flow

This flow is based on the idea that a release deserves the care of a human to at least approve the generated release notes,
but from then on a release should be as automatic as it can get.

* Run `alver bump vx.y.z` to update your project's `__version__` and draft release notes in the changelog.
* Edit the CHANGELOG.md as needed.
* Create a branch named `release`, commit, create a PR.
* When merged, Github Actions builds a release and publishes it to pypi and Github.

Note: alver can deal with versions defined in `pyproject.toml`, `__init__.py`, and `_version.py`.

Note: the release workflow on Github Actions can also be triggered manually or by pushing a tag `vx.y.z`.
So if you e.g. forgot to setup the trusted publisher, you can just retry.


## The alver CLI tool

```
usage: alver [-h] {version,bump,notes,changelog-from-gh,changelog-to-gh} ...

Commands to easily manage releases and changelog

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


## Adopting the alver GH workflow

Should be really easy:

* Copy [release.yml](.github/workflows/release.yml) into your project.
* Create a `build.yml` that does the build and published the artifacts to `dist`.
* At Pypi: setup trusted publishing, using `release.yml` and the `pypi` environment.
* At Github: in the settings create an environment called `pypi`.


## Using alver as a library

The alver library has a few convenient functions to deal with version numbers. Experimental. TODO.
