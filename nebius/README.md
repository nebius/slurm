# Nebius downstream patches

This directory describes the Nebius-specific changes carried on top of
upstream Slurm and tracks the currently maintained patch queue.

## Repository model

The official SchedMD repository is configured as `upstream`; the Nebius fork
is configured as `origin`.

## Initial clone setup

Clone the Nebius repository directly. Git creates `origin` automatically from
the URL used for the clone:

```sh
git clone git@github.com:nebius/slurm.git
cd slurm
```

Add the official SchedMD repository as a fetch-only `upstream` remote:

```sh
git remote add upstream https://github.com/SchedMD/slurm.git
git config --local remote.upstream.pushurl DISABLED
git fetch upstream --prune
```

The following local settings make the intended workflow safer and more
convenient:

```sh
git config --local remote.pushDefault origin
git config --local push.default current
git config --local fetch.prune true
git config --local pull.ff only
git config --local rerere.enabled true
```

Verify the result with `git remote -v`: fetches from `origin` should use the
Nebius repository, fetches from `upstream` should use SchedMD, and the
`upstream` push URL should be `DISABLED`.

Git intentionally does not apply repository-provided configuration to a new
clone, so these local settings cannot be enabled automatically by committing
a `.gitconfig` file. Contributors only need to perform this setup once per
clone.

For every supported Slurm release, Nebius maintains a separate downstream
branch:

```text
upstream/slurm-26.05 -> origin/slurm-26.05 -> origin/nebius/26.05
upstream/slurm-26.11 -> origin/slurm-26.11 -> origin/nebius/26.11
upstream/slurm-27.05 -> origin/slurm-27.05 -> origin/nebius/27.05
```

Each `nebius/<release>` branch is based on the corresponding upstream branch
and contains a linear, ordered queue of Nebius patches. Old release branches
are retained and are not rebased or force-pushed after release.

The `master` branch does not serve as the source base for a downstream Slurm
release. It holds the upstream development history together with this
documentation and the registry of current Nebius changes. The tested commits
on release branches and release tags are the source of truth; `master` does
not store generated `.patch` exports.

## Creating release branches

Create two branches in the Nebius fork for every supported Slurm release:

- `slurm-<release>` is a clean mirror of the corresponding SchedMD branch;
- `nebius/<release>` is the downstream branch containing the ordered Nebius
  patch queue.

First fetch the upstream release and publish its clean mirror. For example,
for Slurm 26.05:

```sh
git fetch upstream \
  refs/heads/slurm-26.05:refs/remotes/upstream/slurm-26.05
git push origin \
  refs/remotes/upstream/slurm-26.05:refs/heads/slurm-26.05
```

Then create the downstream release branch from exactly the same upstream
commit and publish it:

```sh
git switch -c nebius/26.05 upstream/slurm-26.05
git push -u origin nebius/26.05
```

The new `nebius/26.05` branch is initially identical to
`upstream/slurm-26.05`. The first pull request always synchronizes the current
documentation and tests from `master`:

```sh
git fetch origin
git switch -c patch/NB-0001-sync-docs-and-tests origin/nebius/26.05
```

Bring the applicable documentation, test suite, and CI workflow files from
`origin/master` into this branch, review the resulting diff, run the tests,
and open a pull request into `nebius/26.05`. This pull request establishes the
common test baseline for all subsequent Nebius patches on the release.

After `NB-0001` is merged, create each remaining `patch/NB-*` branch from the
updated `origin/nebius/26.05`. Apply patches in the order recorded in
`PATCHES.md` and submit each logical change through a separate reviewed pull
request.

Repeat the same process when a new upstream release appears, substituting its
version in every branch name:

```sh
git fetch upstream \
  refs/heads/slurm-26.11:refs/remotes/upstream/slurm-26.11
git push origin \
  refs/remotes/upstream/slurm-26.11:refs/heads/slurm-26.11
git switch -c nebius/26.11 upstream/slurm-26.11
git push -u origin nebius/26.11
```

Never create a new `nebius/<release>` branch from `master` or from the
previous `nebius/<release>` branch. Starting from the matching upstream branch
prevents source changes from an older Slurm release from leaking into the new
one. Port only the active Nebius patches, one by one and in registry order.

## Syncing an upstream patch release

When SchedMD publishes fixes on a supported release branch, update its clean
mirror in the Nebius fork with:

```sh
git fetch upstream \
  refs/heads/slurm-26.05:refs/remotes/upstream/slurm-26.05 && \
  git push origin \
  refs/remotes/upstream/slurm-26.05:refs/heads/slurm-26.05
```

Change `26.05` in both places for another supported release. A normal Git push
rejects a non-fast-forward update, so this command does not overwrite a mirror
branch that has diverged from SchedMD. Do not use `--force` to bypass that
check; investigate and restore the mirror instead.

This command updates only the clean `origin/slurm-26.05` mirror. Bring the new
upstream commits into `nebius/26.05` through a dedicated sync branch and pull
request so the Nebius patch queue is rebuilt or merged, tested, and reviewed:

```sh
git fetch origin
git switch -c sync/26.05-YYYYMMDD origin/nebius/26.05
git merge origin/slurm-26.05
git push -u origin sync/26.05-YYYYMMDD
```

Never sync upstream directly into an active `patch/NB-*` development branch.
Update the downstream release first, then rebase or recreate the development
branch on the reviewed result.

## Patch organization

Each logical change has a permanent identifier such as `NB-0001`. The same
identifier is retained when the change is ported to a newer Slurm release,
even if its implementation has to change.

An active patch is represented by:

- one logical commit, or a small and clearly identified commit series, on
  each applicable `nebius/<release>` branch;
- a standardized description in [`patches/`](patches/README.md) explaining
  what the patch changes, why Nebius carries it, and how to validate and port
  it;
- an entry in [`PATCHES.md`](PATCHES.md) describing dependencies, upstream
  status, and supported Slurm releases.

Rows in `PATCHES.md` are kept in application order. No generated `.patch`
files are maintained on `master`, because they can become stale and are not
used to build or test releases. The Markdown files under `patches/` describe
logical changes; tested commits and tags remain the implementation source of
truth.

`NB-0001` is reserved for synchronizing the current documentation and test
suite from upstream `master`. It is the first pull request in every downstream
queue so subsequent Nebius patches can add code and tests against the same
baseline. Keep the logical patch and its identifier the same across releases,
even when some files or conflict resolutions differ.

## Developing a patch

Start work from the downstream branch for the target release:

```sh
git switch -c patch/NB-0002-short-description origin/nebius/26.05
```

Submit the branch as a pull request into `nebius/26.05`. Keep unrelated
changes in separate patches. Avoid merge commits in the downstream patch
queue so individual changes can be ported, reordered, or dropped.

If a change is intended for SchedMD, develop or reproduce it on a branch based
on the clean upstream release branch. This prevents other Nebius changes from
leaking into the upstream pull request.

## Porting to a new Slurm release

Create the new downstream branch directly from the new upstream release:

```sh
git fetch upstream --prune
git switch -c port/26.11 upstream/slurm-26.11
```

Cherry-pick the active patches from the most recent supported Nebius release
in the order recorded in `PATCHES.md`. Create and merge `NB-0001` first, then
port the remaining patch commits:

```sh
git cherry-pick -x <NB-0002-commit>
git cherry-pick -x <NB-0003-commit>
```

Resolve and test each patch separately. Port sequentially between releases
(`26.05` to `26.11`, then `26.11` to `27.05`) so conflict resolutions are not
repeated unnecessarily.

When an upstream release already contains a patch, do not apply it again.
Mark it as `upstream` in `PATCHES.md` and remove it from the active registry
when the oldest supported release no longer requires it.

After the complete queue passes CI, publish it as the new
`nebius/<release>` branch. Do not rewrite older release branches.

## CI workflows on release branches

GitHub Actions workflow files used to build or test a release must be present
in that release branch. Keeping them only on `master` is not sufficient for
pushes to `nebius/<release>`, tag builds, or pull requests targeting the
release branch.

Therefore the first `NB-0001` pull request for each release should also copy
the applicable `.github/workflows/` files from `master`. Keep those workflow
files versioned with the release code so a release tag contains both the exact
source and the exact CI definition that validated it.

Configure the workflow triggers to cover downstream branches and tags, for
example `nebius/**` and the chosen Nebius release-tag pattern. Scheduled
workflows are a special case: GitHub runs them only from the repository's
default branch, so a scheduled orchestration workflow belongs on `master` and
can explicitly check out the release branch it needs to test.
