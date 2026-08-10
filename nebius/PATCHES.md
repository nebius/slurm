# Nebius patch registry

This table tracks the Nebius-specific patches that are currently maintained.
Add one row per logical patch and keep its `NB-*` identifier stable across
Slurm releases.

| ID | Description | Depends on | Upstream status | Supported releases |
| --- | --- | --- | --- | --- |
| [NB-0001](patches/NB-0001-sync-docs-and-tests.md) | Sync current documentation, tests, and CI workflows from `master` | — | Nebius downstream only | All supported releases |

Possible upstream statuses include `not submitted`, a link to the upstream
issue or pull request, and `upstream since <release>`.
