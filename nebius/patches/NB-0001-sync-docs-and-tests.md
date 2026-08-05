---
id: NB-0001
title: Sync documentation, tests, and CI workflows from master
status: active
applies_to:
  - all-supported-releases
depends_on: []
upstream: downstream-only
---

# NB-0001: Sync documentation, tests, and CI workflows from master

## Summary

Synchronizes the current documentation, test suite, and applicable GitHub
Actions workflow files from `master` into a newly created
`nebius/<release>` branch.

This is always the first pull request for a new downstream release:

```sh
git switch -c patch/NB-0001-sync-docs-and-tests origin/nebius/26.05
```

## Motivation

Nebius release branches need a consistent documentation and test baseline
before product-specific code patches are introduced. Keeping the CI workflow
with the release code also makes branch, pull-request, and tag validation
reproducible.

## Scope

The patch includes:

- current applicable documentation from `master`;
- the current Slurm test suite from `master`;
- CI workflow files required to build and test the release branch and its
  tags.

It does not intentionally backport unrelated production behavior from
`master`. Compatibility changes required to build or run the synchronized
tests must be explicit in the pull request and kept to the minimum necessary.

## Porting notes

- Create the target `nebius/<release>` branch from the matching clean
  `upstream/slurm-<release>` branch before starting this patch.
- Apply `NB-0001` before every other Nebius patch.
- Review files already present in the target upstream release to avoid
  overwriting release-specific documentation or test expectations blindly.
- Record tests that are intentionally excluded or adapted because the target
  release does not contain the feature they exercise.
- Keep the logical patch ID unchanged across releases even when the resulting
  commit differs.

## Validation

- The release branch builds using the synchronized CI workflow.
- The synchronized test suite completes with no unexplained new failures.
- Any skipped, adapted, or excluded master tests are documented in the pull
  request.
- CI runs for pull requests targeting the release branch and for the intended
  Nebius release-tag pattern.

## History

- Initial specification: establish documentation, tests, and CI as the first
  downstream change on every supported release.
