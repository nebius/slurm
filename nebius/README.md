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
git switch -c 26.05/patch/NB-0001-sync-docs-and-tests origin/nebius/26.05
```

Bring the applicable documentation, test suite, and CI workflow files from
`origin/master` into this branch, review the resulting diff, run the tests,
and open a pull request into `nebius/26.05`. This pull request establishes the
common test baseline for all subsequent Nebius patches on the release.

Synchronize the complete `testsuite/` tree, not only `testsuite/python/`.
The Python wrappers invoke files under `testsuite/expect/` and use the common
runner and libraries under `testsuite/run-tests` and `testsuite/src/`. The
full-ATF workflow checks for these paths before creating a VM so an incomplete
sync fails quickly without consuming cloud resources.

Use a tree-level restore so additions, updates, and removals from `master` are
all applied together. Including `--staged` also carries files that an older
release's `.gitignore` may still ignore:

```sh
git restore --source=origin/master --staged --worktree -- testsuite
```

The testsuite is part of the Autotools build graph. When the sync adds,
renames, or removes a directory containing `Makefile.am` or `Makefile.in`,
reconcile the release branch's build metadata as well:

- update the corresponding test entries in `AC_CONFIG_FILES` in
  `configure.ac`;
- update the checked-in generated `configure` in the same commit;
- keep each `Makefile.am` and generated `Makefile.in` pair consistent.

Prefer porting the matching generated hunk from the same upstream commit. If
the files must be regenerated locally, use the Autoconf and Automake versions
used by that release line and review the complete generated diff.

Do not copy the complete `configure.ac` from a different Slurm release line:
it also describes product plugins and dependencies that may not exist on the
target release. Port only the test build-graph changes that apply, together
with their generated output. Do not create placeholder `Makefile.in` files to
make a stale `configure` pass. The ATF and release builders intentionally run
the checked-in `configure` without repairing missing inputs, so inconsistent
Autotools metadata fails before a baseline or release can be published.

Before merging `NB-0001`, publish the vanilla full-ATF baseline and add its
immutable release tag to `nebius/ci/atf/baselines/26.05.txt` in the same pull
request. The detailed procedure is in
[Full ATF baseline and patch comparison](#full-atf-baseline-and-patch-comparison).

After `NB-0001` is merged, create each remaining `<release>/patch/NB-*` branch
from the updated `origin/nebius/26.05`. Apply patches in the order recorded in
`PATCHES.md` and submit each logical change through a separate reviewed pull
request. The release prefix makes the target line explicit and lets CI reject
a branch whose version does not match its `nebius/<release>` pull-request
target.

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

Never sync upstream directly into an active `<release>/patch/NB-*` development
branch. Update the downstream release first, then rebase or recreate the
development branch on the reviewed result.

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

Fetch the fork and start work from the current downstream branch for the
target release:

```sh
git fetch origin
git switch -c 26.05/patch/NB-0002-short-description origin/nebius/26.05
```

Submit the branch as a pull request into `nebius/26.05`. Keep unrelated
changes in separate patches. Avoid merge commits in the downstream patch
queue so individual changes can be ported, reordered, or dropped.

Create the next patch branch only after its dependencies have been merged and
the local `origin/nebius/26.05` tracking ref has been refreshed. For example,
after `NB-0002` is merged:

```sh
git fetch origin
git switch -c 26.05/patch/NB-0003-next-change origin/nebius/26.05
```

Do not normally create `NB-0003` from an unmerged `NB-0002` branch. That
turns the pull requests into an implicit stack and makes the second diff
contain both patches. If parallel development is necessary, start both
branches from `origin/nebius/<release>`, declare the dependency in
`PATCHES.md`, then rebase or recreate the dependent branch after the first
patch merges.

Before opening the pull request, verify the branch relationship and target:

```sh
git merge-base --is-ancestor origin/nebius/26.05 HEAD
git log --oneline origin/nebius/26.05..HEAD
```

The source branch must match `<release>/patch/<description>`, normally with a
stable patch ID such as `26.05/patch/NB-0002-short-description`, and the pull
request must target `nebius/<release>`. CI rejects a release prefix that does
not match the target branch.

If a change is intended for SchedMD, develop or reproduce it on a branch based
on the clean upstream release branch. This prevents other Nebius changes from
leaking into the upstream pull request.

### Stamping the Nebius release version

Keep `NB-0001` limited to documentation, tests, and CI. In particular, do not
change `META` there: the vanilla baseline workflow treats it as a product file
and rejects it at the baseline boundary.

Add the Nebius version stamp as a separate downstream patch immediately after
`NB-0001`, before patches that change Slurm behavior. Create it from the
updated release branch in the same way as any other patch. Allocate its stable
`NB-*` identifier, add it to `PATCHES.md`, and create its specification from
`nebius/patches/TEMPLATE.md`:

```sh
git fetch origin
git switch -c \
  26.05/patch/NB-XXXX-nebius-release-version \
  origin/nebius/26.05
```

In that branch, preserve the SchedMD `Major`, `Minor`, `Micro`, and `Version`
values in `META` and set only its downstream `Release` value. For example:

```text
  Major:       26
  Minor:       05
  Micro:       3
  Version:     26.05.3
  Release:     nebius-1
```

The normal `configure` step reads `META` directly, so a clean rebuild then
reports `slurm 26.05.3-nebius-1` from `sinfo --version`, `slurmctld -V`, and
the other Slurm binaries. Do not edit the generated version macros or hard-code
the suffix in individual commands.

Treat the final number as the Nebius build revision for one SchedMD patch
version. If the same `26.05.3` source needs another downstream release, bump
it to `nebius-2`. When SchedMD updates the branch to `26.05.4`, take its new
`Micro` and `Version` values and start that upstream version at `nebius-1`.
An upstream sync will commonly touch `META`, so resolving this small conflict
is an explicit part of refreshing the version-stamp patch.

RPM and Debian package versions must express the same downstream revision in
their own metadata (`slurm.spec` and `debian/changelog`), but their version
grammars are not identical to the runtime string. Update and validate those
files in the packaging workflow instead of blindly copying `nebius-1` into
every package field. The `META` change alone is sufficient for source builds
and the version printed by Slurm binaries.

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

The reviewed downstream branch is published with the manual release workflow.
Repository setup, version stamping, tag naming, and artifact verification are
documented in [`RELEASING.md`](RELEASING.md).

### ATF environment and initial smoke test

The initial [`Slurm smoke test`](../.github/workflows/slurm-smoke-test.yml)
workflow is manual while the CI setup is being validated. It creates a
disposable VM from image `computeimage-e00sphs75y9ej9nw9j`, copies the exact
selected Git ref to it, builds Slurm, and runs only
`slurm_unit/common/log-test`. Logs are uploaded as a workflow artifact and the
VM and its managed boot disk are deleted even when the build or test fails.

Configure the following values in the GitHub `e2e` environment:

| Kind | Name | Purpose |
| --- | --- | --- |
| Variable | `NEBIUS_CLI_CONFIG` | Nebius CLI `config.yaml` without the private key |
| Variable | `SLURM_ATF_PROFILE` | Project, subnet, shape, and SSH user for four CPU shards |
| Variable | `SLURM_ATF_H200_PROFILE` | Project, subnet, shape, and SSH user for the 8xH200 shard |
| Secret | `NEBIUS_PRIVATE_KEY` | Private key for the selected Nebius CLI profile |
| Secret | `SLURM_ATF_SSH_PRIVATE_KEY` | Unencrypted OpenSSH key used for the disposable VM |
| Secret | `SLURM_ATF_DEBUG_SSH_PUBLIC_KEYS` | Optional newline-separated public keys for human debugging |

#### `NEBIUS_CLI_CONFIG` variable

Store the complete Nebius CLI YAML configuration except for the private key.
The profile name must match the `nebius_cli_profile` workflow input, which
defaults to `default`:

```yaml
default: default
profiles:
  default:
    endpoint: api.nebius.cloud
    auth-type: service account
    service-account-id: serviceaccount-e00example
    public-key-id: publickey-e00example
    parent-id: project-e00example
```

Do not add `private-key` or `private-key-file-path` to this variable. The
workflow injects the private key from `NEBIUS_PRIVATE_KEY` into the selected
profile at runtime.

#### `NEBIUS_PRIVATE_KEY` secret

Store the complete PEM private key belonging to the authorized public-key ID
from `NEBIUS_CLI_CONFIG`. Nebius accepts PKCS#1 or PKCS#8 PEM keys. A typical
PKCS#8 value looks like:

```text
-----BEGIN PRIVATE KEY-----
base64-encoded-service-account-private-key
-----END PRIVATE KEY-----
```

Keep the header, footer, and original line breaks. This is the Nebius service
account authentication key; it is not an SSH key.

#### `SLURM_ATF_PROFILE` variable

Store the VM placement and shape as YAML:

```yaml
nebius_project_id: project-e00example
slurm_atf:
  subnet_id: vpcsubnet-e00example
  security_group_id: vpcsecuritygroup-e00example
  platform: cpu-d3
  preset: 32vcpu-128gb
  boot_disk_gib: 512
  boot_disk_type: network_ssd
  ssh_user: slurm-atf-ci
```

Required fields are `nebius_project_id`, `subnet_id`, `platform`, and
`preset`. `security_group_id` is optional. The defaults for omitted optional
fields are:

```yaml
boot_disk_gib: 512
boot_disk_type: network_ssd
ssh_user: slurm-atf-ci
```

`boot_disk_gib` must be a positive integer. `ssh_user` must be a lowercase
Linux username containing only letters, digits, underscores, or hyphens. The
compute image does not belong in this variable: the baseline workflow receives
an immutable image ID explicitly, and candidate runs inherit it from the
published baseline metadata.

For the dedicated GPU shard, store this 8xH200 VM shape in
`SLURM_ATF_H200_PROFILE`:

```yaml
nebius_project_id: project-e00y7jt0r898cb4xmw
slurm_atf:
  subnet_id: vpcsubnet-e00sn03j64ps398smm
  platform: gpu-h200-sxm
  preset: 8gpu-128vcpu-1600gb
  boot_disk_gib: 512
  boot_disk_type: network_ssd
  ssh_user: slurm-atf-ci
```

The H200 VM profile requires an ATF image whose metadata declares eight
H200 GPUs and whose Nebius image metadata recommends `gpu-h200-sxm`. The
workflow checks the image state, architecture, minimum disk size, platform,
CUDA compiler, NVML headers, and all eight GPUs before starting the long test
suite. The CPU-only image `computeimage-e00sphs75y9ej9nw9j` is not compatible
with this profile.

`atf_profile=h200` selects and validates the physical VM only. All shards
configure a hardware-neutral `generic` Slurm node with four synthetic CPUs.
ATF clones and reshapes that node for individual tests; cloning the physical
128-CPU, eight-GPU node would make synthetic `slurmd` instances invalid because
NVML devices exist only for `node0`. The base `gres.conf` therefore remains
empty even on the GPU shard. The upstream-skipped `expect/test_39_9.py` remains
skipped because H200 does not provide all memory-clock controls assumed by the
legacy `srun --gpu-freq` test. The GPU shard still exposes the real H200 devices,
CUDA compiler, and NVML libraries to supported tests such as
`expect/test_40_8.py`.

Build and version that image using the repository-owned
[`nebius/ci/images/slurm-atf-h200`](ci/images/slurm-atf-h200/README.md)
Packer definition. Its project and subnet are runtime variables and are not
stored in Git.

Keeping H200 in a separate variable leaves `SLURM_ATF_PROFILE` available to
the CPU smoke workflow and the four CPU test shards. Full runs automatically
select `SLURM_ATF_H200_PROFILE` only for the GPU shard while keeping the
in-guest ATF cluster generic; no variable has to be swapped between runs.

The effective security group must allow TCP/22 from GitHub-hosted runners.
The Nebius identity must be allowed to create, inspect, and delete Compute
instances, managed disks, and dynamic public IP addresses in the selected
project.

#### `SLURM_ATF_SSH_PRIVATE_KEY` secret

Store one complete, unencrypted OpenSSH private key used only by CI to reach
the disposable VM:

```text
-----BEGIN OPENSSH PRIVATE KEY-----
base64-encoded-openssh-private-key
-----END OPENSSH PRIVATE KEY-----
```

Generate a dedicated key pair rather than using a personal key:

```sh
ssh-keygen -t ed25519 -N '' -C slurm-atf-ci -f ./slurm-atf-ci
```

Upload the contents of `slurm-atf-ci` to this secret. Do not upload the `.pub`
file here. The workflow derives the public key and injects it into the VM.
Because the workflow is non-interactive, this key must not have a passphrase.

#### `SLURM_ATF_DEBUG_SSH_PUBLIC_KEYS` secret

This optional secret contains up to 20 personal **public** keys, one complete
key per line. Empty content is allowed. Supported formats are `ssh-ed25519`,
`ssh-rsa`, and `ecdsa-*`:

```text
ssh-ed25519 AAAA... alice@example
ssh-ed25519 AAAA... bob@example
```

Do not put personal private keys in this secret. The workflow validates every
public-key line before creating the VM and adds the keys to the temporary
`SLURM_ATF_PROFILE.slurm_atf.ssh_user` account. The job summary prints the VM
IP and SSH command. Human access is normally useful together with
`keep_vm_on_failure=true`; otherwise the VM is deleted immediately after the
test completes.

#### Workflow inputs

`nebius_cli_profile` is a profile name present under
`NEBIUS_CLI_CONFIG.profiles`; it defaults to `default`. Valid names contain
letters, digits, dots, underscores, or hyphens.

`keep_vm_on_failure` is a boolean. Keep the default `false` for normal runs.
Set it to `true` only when someone is ready to connect over SSH and delete the
retained VM manually after debugging.

After the workflow is present on both `master` and the target release branch,
run it from the Actions UI and select the release ref. The equivalent GitHub
CLI command is:

```sh
gh workflow run slurm-smoke-test.yml \
  --ref nebius/26.05 \
  -f nebius_cli_profile=default \
  -f keep_vm_on_failure=false
```

Set `keep_vm_on_failure=true` only for intentional SSH debugging and delete
the retained VM manually afterwards. Once this manual workflow is stable, add
a `pull_request` trigger for `nebius/**` branches to make it a required merge
check.

### Full ATF baseline and patch comparison

The full workflow runs the complete ATF suite on five disposable VMs in
parallel: four generic CPU shards and one 8xH200 GPU shard. Test paths are put
in a stable SHA-256 order and then assigned to the currently smallest shard.
This keeps per-phase file counts within one file of each other while scattering
similarly named tests. Tests that require real GPU tooling are assigned to the
GPU shard first; that shard then receives enough ordinary files to reach the
same target count as the CPU shards. Tests with known H200 topology limits,
such as the legacy 64-bit affinity-mask `expect/test_1_91.py`, remain on a CPU
shard.

Each shard has two sequential GitHub jobs. The first creates its VM, builds
Slurm and the SUT-linked MPICH, and runs its assigned wrappers under
`testsuite/python/expect/`. The second reconnects to the same VM using the SSH
host key pinned by the first job, resets the disposable ATF configuration and
accounting database, and runs its assigned files under
`testsuite/python/tests/` without rebuilding Slurm. All five shard workflows
execute concurrently.

Each phase stores its selection manifest, log, exit status, JUnit report,
daemon logs, configuration, and timestamps. After all shards finish, an
aggregation job requires exactly the fixed `cpu-0` through `cpu-3` plus `gpu`
topology, identical source/test/infrastructure revisions, disjoint selection,
and complete collected testcase coverage. It then publishes one stable
`junit.xml` consumed by baseline/candidate comparison while retaining every
per-shard artifact below `shards/`. Cleanup runs independently for every VM
unless `keep_vm_on_failure=true`.

This version balances exact file counts rather than historical duration. The
hash-ordered assignment is reproducible across baseline and candidate runs and
keeps new tests deterministic. If timing data later shows a persistent skew,
the assignment algorithm can be versioned and replaced when creating a new
baseline; it must not change underneath an existing baseline pointer.

The Nebius projects referenced by the two environment profiles must have
enough quota to allocate four CPU VMs and one 8xH200 VM concurrently. Be
especially careful with `keep_vm_on_failure=true`: a failed run can retain all
five machines, and each must then be deleted manually.

The user-facing workflows intentionally separate two operations:

1. [`Slurm ATF vanilla baseline`](../.github/workflows/slurm-atf-baseline.yml)
   builds the release while `NB-0001` contains only documentation, tests, and
   CI changes. It publishes the complete evidence as an immutable GitHub
   Release and also keeps a 30-day Actions artifact.
2. [`Slurm ATF patch comparison`](../.github/workflows/slurm-atf-candidate.yml)
   builds a later patch but checks out the common tests from the exact
   baseline commit. It compares every JUnit testcase with the published
   vanilla result. After the common suite, the existing H200 shard also runs
   tests added or changed by the patch from the candidate tree.

The baseline run may contain failures already present in the vanilla release.
Its raw pytest exit status is recorded rather than used as the gate. A patch
passes when every common testcase either keeps its baseline outcome or
improves to `passed` and no baseline test disappears. The separate
patch-specific gate requires every testcase collected from a new or modified
test file to be `passed`; failed, errored, skipped, and xfailed outcomes all
fail this gate. Changing a known common failure into a skip or another failure
mode still fails the comparison, and a patch may not remove a frozen baseline
test file.

Patch-specific tests run after the common Expect and Python phases on the same
8xH200 VM, so they do not allocate a sixth machine or change the immutable
five-shard baseline assignment. CI selects top-level `test_*.py` files added
or modified below `testsuite/python/expect/` and
`testsuite/python/tests/`. Changing a raw `testsuite/expect/testN.M` program
also selects its `expect/test_N_M.py` wrapper. The complete candidate test
tree is used for this phase, including candidate helper changes, while the
source under test remains the already built candidate commit.

Prefer adding a new test file for each product patch. Modifying an existing
file reruns that whole file under the stricter all-passed policy, so any
pre-existing skip or xfail in it will reject the patch-specific gate. A patch
that changes only shared test support must also add or modify a runnable test;
otherwise CI refuses the change rather than silently leaving it uncovered.

Only stable assertion-level failures caused by the vanilla Slurm source are
acceptable baseline outcomes. Harness setup errors, order-dependent failures,
profile-size assumptions, and state leaks must be fixed in the common tests on
`master` before publishing a baseline. Recording those as expected failures
would leave their assertions unexecuted and make later A/B comparisons noisy
or misleading.

#### Creating the baseline in `NB-0001`

Push `26.05/patch/NB-0001-sync-docs-and-tests`, then run the baseline workflow
on that exact ref:

```sh
gh workflow run slurm-atf-baseline.yml \
  --ref 26.05/patch/NB-0001-sync-docs-and-tests \
  -f release_line=26.05 \
  -f upstream_branch=slurm-26.05 \
  -f cpu_image_id=computeimage-e00sphs75y9ej9nw9j \
  -f gpu_image_id=computeimage-e00gq5v1eyswsdk55g \
  -f nebius_cli_profile=default \
  -f keep_vm_on_failure=false
```

The workflow first verifies that the selected clean mirror commit is an
ancestor and that `NB-0001` changes only `.github/`, `nebius/`, `testsuite/`,
documentation, and Markdown files. Product changes abort publication.

When the run completes, copy the tag printed in its summary into the one-line
pointer file `nebius/ci/atf/baselines/26.05.txt`:

```text
slurm-atf-baseline-26.05-<64-character-baseline-key>
```

Commit that pointer to `NB-0001` before merging it. On this bootstrap PR the
target release does not have a pointer yet, so the candidate workflow accepts
the pointer from the PR only when its branch matches
`<release>/patch/NB-0001-<description>` and the branch release matches the
`nebius/<release>` target. It fully validates the immutable release but skips
the redundant five-VM candidate rerun. Later patch PRs must use the pointer
already merged into the target release and cannot replace it.

The release contains the JUnit report, pytest and daemon logs, generated
configuration, package and VM metadata, and SHA256 checksums. An existing tag
is never overwritten.
This also works with squash merging: the release tag keeps the pre-merge test
commit reachable, while later candidates are tied to the recorded clean
`slurm-<release>` ancestor rather than to a particular merge strategy.

Before publishing the first baseline, enable
[GitHub release immutability](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes)
under **Settings → Releases → Enable release immutability**. The workflow
itself refuses to overwrite an existing baseline; the repository setting
additionally locks the published tag and assets against later manual changes.

#### Testing later patches

Pull requests targeting `nebius/**` run the patch comparison automatically and
must use a `<release>/patch/<description>` source branch matching the target
release. Except for the explicitly validated `NB-0001` bootstrap described
above, the workflow reads the pointer specifically from the target release
branch (a patch cannot replace its own comparison input), verifies the
baseline archive and provenance, and uses the baseline's exact test commit,
ATF infrastructure commit, two images, CPU/GPU VM shapes, and five-shard
assignment manifest.

A manual rerun normally needs only the release ref; it reads the same pointer:

```sh
gh workflow run slurm-atf-candidate.yml \
  --ref 26.05/patch/NB-0002-short-description \
  -f release_line=26.05 \
  -f nebius_cli_profile=default \
  -f keep_vm_on_failure=false
```

The optional `baseline_tag` input overrides the pointer for diagnosis. Do not
use an override as the normal merge result: the committed pointer is the
reviewed comparison contract for the release.

Candidate runs also inherit both image IDs and the exact CPU/GPU VM shapes
from that immutable baseline. The comparison requires the same sharding
algorithm and inventories. A changed GitHub environment profile therefore
fails during VM validation instead of producing an invalid multi-hour
comparison. Patch-specific tests are deliberately outside that inventory:
their selection and JUnit report are stored separately and must be fully
passing.

After a comparison, three 30-day Actions artifacts are available: the complete
candidate evidence, the patch-specific H200 evidence (including an empty
selection when the patch has no tests), and a smaller A/B report in Markdown
and JSON. The vanilla evidence remains permanently available from its GitHub
Release.
