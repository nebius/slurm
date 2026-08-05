# Exported patch set

This directory contains Git-format exports of the active Nebius patches.

Files use stable identifiers and descriptive names:

```text
NB-0001-short-description.patch
NB-0002-another-change.patch
```

[`series`](series) lists the files in application order. Whenever a patch is
added, removed, reordered, or regenerated, update the series file and the
registry in [`../PATCHES.md`](../PATCHES.md) in the same change.

Do not place temporary diffs or superseded patch revisions here. Git commits
on the corresponding `nebius/<release>` branch are the development source of
truth; this directory is their portable, reviewed export.
