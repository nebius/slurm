# Nebius downstream patches

This directory describes the Nebius-specific changes carried on top of
upstream Slurm and stores an export of the currently maintained patch set.

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
documentation and an export of the current Nebius patch set.

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
`upstream/slurm-26.05`. Consult `nebius/patches/series` on `master`, apply the
active patches in that order starting with `NB-0001`, and submit them to
`nebius/26.05` through reviewed pull requests. The metadata and exported
patches remain on `master`; they do not need to be copied into the release
branch.

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
one. Port only the active Nebius patches, one by one and in series order.

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
- a Git-format patch in [`patches/`](patches/);
- an entry in [`PATCHES.md`](PATCHES.md) describing dependencies, upstream
  status, and supported Slurm releases.

Patch filenames begin with their identifier, for example:

```text
NB-0001-topology-configuration.patch
NB-0002-gpu-accounting.patch
```

The ordered list in [`patches/series`](patches/series) is authoritative when
patches depend on one another. Patch files are portable snapshots; commits on
the release branches remain the source of truth for development and review.

`NB-0001` is reserved for backporting the test suite from upstream `master`.
It is the first patch in every downstream queue so subsequent Nebius patches
can add code and tests against the same test baseline. The logical patch and
its identifier stay the same across releases. Its generated patch file may
still require a release-specific refresh when the target release already
contains some of the tests or surrounding upstream code changes.

## Developing a patch

Start work from the downstream branch for the target release:

```sh
git switch -c patch/NB-0001-short-description origin/nebius/26.05
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
in the order recorded in `patches/series`:

```sh
git cherry-pick -x <NB-0001-commit>
git cherry-pick -x <NB-0002-commit>
```

Resolve and test each patch separately. Port sequentially between releases
(`26.05` to `26.11`, then `26.11` to `27.05`) so conflict resolutions are not
repeated unnecessarily.

When an upstream release already contains a patch, do not apply it again.
Mark it as `upstream` in `PATCHES.md` and remove it from `patches/series` when
the oldest supported release no longer requires it.

After the complete queue passes CI, publish it as the new
`nebius/<release>` branch. Do not rewrite older release branches.

## Updating the exported patch set

After a patch is accepted or ported, regenerate its Git-format patch from the
tested downstream commit, update `patches/series`, and update its row in
`PATCHES.md`. Review these three changes together so the exported set cannot
silently diverge from the release branches.

For example, a single commit can be exported with:

```sh
git format-patch -1 <commit> --stdout > \
  nebius/patches/NB-0001-short-description.patch
```

Never edit the same change independently in both a release branch and its
exported patch file. Make the source change on the release branch, test it,
and then regenerate the export.
