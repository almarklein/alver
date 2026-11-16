# alver

Easy management of versions, releases and changelog.

## The alver release flow

* Run `alver bump vx.y.z`
* Edit CHANGELOG.md as needed.
* Create a PR, discuss, merge.
* -> Github does the rest (publish release to Pypi and GH).

This flow is based on the idea that a release deserves the care of a human to at least approve the generated release notes,
but from then on a release should be as automatic as it can get.

The release workflow on Github Actions triggers when a branch named `release` is merged into `main`,
but can also be triggered manually or by pushing a tag `vx.y.z`.
So if you e.g. forgot to setup the trusted publisher, you can just retry.


## Adopting the alver flow in your project

Install alver:

* `pip install alver` or use your favorite installer.

Meet the assumptions made by alver:

* Your version is defined in `pyproject.toml`, `__init__.py`, or `_version.py`.
* You have a CHANGELOG.md with headers marked as `## [v1.0.0] - 09-11-2026`. If no changelog exists, alver will create it. 

To setup Github actions:

* Create a small workflow in your project that calls the release workflow from this repo as a reusable workflow:

  ```yaml
  name: Release

  on:
    workflow_dispatch:
    push:
      tags: ["v[0-9]*.[0-9]*.[0-9]*"]
    pull_request:
      types: [closed]
      branches: [main]

  permissions:
    contents: write # push the tag, create the gh release
    id-token: write # PyPI trusted publishing (OIDC)

  jobs:
    release:
      uses: almarklein/alver/.github/workflows/release.yml@main
      # Optionally override the defaults:
      # with:
      #   python-version: "3.12"
      #   environment: pypi
      #   dist-artifact: dist
  ```

  The release workflow runs entirely in your repo: it reads the version from your code, pushes the `vx.y.z` tag, and creates the GitHub release in your repo. Trigger it the same way as in this repo: manually, by pushing a `vx.y.z` tag, or by merging a `release` -> `main` PR.
* Create `.github/workflows/build.yml` in your project (copy [build.yml](.github/workflows/build.yml) and adapt the build steps); it must upload the built files as an artifact named `dist` (or set the `dist-artifact` input to match).
* At Github: in the settings create an environment called `pypi`.
* At Pypi: setup trusted publishing (OIDC) for your repository and your release workflow, using the `pypi` environment.


## Using the alver CLI tool

```
usage: alver [-h] {version,gitversion,format,bump,notes,changelog-from-gh,changelog-to-gh} ...

positional arguments:
  {version,bump,notes,changelog-from-gh,changelog-to-gh}
    version             Print the current project version (from _version.py, __init__.py, or pyproject.toml).
    gitversion          Print the detailed project version based on git tags and history (like 'version', but refined), e.g. 1.2.3.post4+gabcdef1.
    format              Format CHANGELOG.md in place, fixes section headers and blank lines.
    bump                Bump to the given version and add a changelog section with gh-generated release notes, e.g. `alver bump v1.2.3`.
    notes               Print the release notes for the given version from CHANGELOG.md, e.g. `alver notes v1.2.3`.
    changelog-from-gh   Create/update CHANGELOG.md sections from the GitHub releases of this repo for the given version, e.g. `alver
                        changelog-from-gh v1.2.3` ('*' = all releases).
    changelog-to-gh     Update the gh release notes from the CHANGELOG.md section of the given version, e.g. `alver changelog-to-gh v1.2.3`
                        ('*' = all sections).

options:
  -h, --help            show this help message and exit
```


## Using alver as a library

* `get_detailed_version_of_lib(module) -> str | None`: get the git-enhanced version of a library.
* `get_detailed_version(version: str, filename: str) -> str`: get the git-enhanced version of a module's version and filename.
