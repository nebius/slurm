# Nebius patch registry

This table tracks the Nebius-specific patches that are currently maintained.
Add one row per logical patch and keep its `NB-*` identifier stable across
Slurm releases.

| ID | Description | Depends on | Upstream status | Supported releases |
| --- | --- | --- | --- | --- |
| [NB-0001](patches/NB-0001-sync-docs-and-tests.md) | Sync current documentation, tests, and CI workflows from `master` | — | Nebius downstream only | All supported releases |
| [NB-0002](patches/NB-0002-topology-block-blocks-nodes-bitmap.md) | Keep a node in the `topology/block` aggregate bitmap when its topology is re-applied unchanged | NB-0001 | upstream since 26.05.6 ([SchedMD/slurm#225](https://github.com/SchedMD/slurm/pull/225)) | nebius/26.05 up to 26.05.4-nebius-3 |
| [NB-0003](patches/NB-0003-reboot-rest-api.md) | Add node reboot operations to the Slurm REST API | NB-0001 | not submitted | nebius/26.05 |
| [NB-0004](patches/NB-0004-disable-auto-resume.md) | Keep selected powered-down nodes from being resumed automatically by scheduling | NB-0001 | not submitted | nebius/26.05 |
| [NB-0005](patches/NB-0005-cloud-registration-fields.md) | Refresh slurmd-supplied topology and instance metadata when a CLOUD node powers up | NB-0001 | not submitted; upstream 26.05.6 fixes the power-up case differently ([SchedMD/slurm#232](https://github.com/SchedMD/slurm/pull/232)) | nebius/26.05 |
| [NB-0006](patches/NB-0006-stale-node-topology.md) | Recover from stale node topology assignments during startup and reconfigure | NB-0001 | [SchedMD/slurm#246](https://github.com/SchedMD/slurm/pull/246) | nebius/26.05 |

Possible upstream statuses include `not submitted`, a link to the upstream
issue or pull request, and `upstream since <release>`.
