# Release baseline pointers

Each supported downstream release has one text file named `<release>.txt`.
The file contains exactly one immutable GitHub Release tag produced by the
`Slurm ATF vanilla baseline` workflow, for example:

```text
slurm-atf-baseline-26.05-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

Run the baseline workflow on
`<release>/patch/NB-0001-sync-docs-and-tests`, then add the reported tag to
`baselines/<release>.txt` in the same pull request. Do not change this pointer
merely to rerun CI. A new pointer requires a deliberate new vanilla baseline
and review.

Patch comparison workflows read this file from the release branch. This pins
the baseline evidence, source and common-test commit, ATF infrastructure, CPU
and GPU images and shapes, plus the five-shard assignment used for every later
patch.
