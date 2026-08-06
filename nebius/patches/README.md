# Nebius patch specifications

This directory contains the maintained specification for every logical
Nebius patch. It does not contain generated `.patch` or `.diff` files.

Use one Markdown file per patch, named with its stable identifier and a short
description:

```text
NB-0001-sync-docs-and-tests.md
NB-0002-short-description.md
```

Each specification uses YAML front matter for concise metadata and the same
Markdown sections for human-readable context. Start new specifications from
[`TEMPLATE.md`](TEMPLATE.md).

Required metadata:

- `id`: permanent `NB-*` identifier;
- `title`: short description of the logical change;
- `status`: `proposed`, `active`, `upstream`, or `retired`;
- `applies_to`: supported downstream release branches;
- `depends_on`: patch identifiers that must be applied first;
- `upstream`: upstream issue/PR URL, `not-submitted`, `downstream-only`, or
  the release that contains the change.

Required sections:

- **Summary** — what the patch changes;
- **Motivation** — why Nebius needs it;
- **Scope** — important files and behavior included or excluded;
- **Porting notes** — ordering, expected conflicts, and release differences;
- **Validation** — tests and acceptance criteria;
- **History** — material changes to the logical patch between releases.

Keep [`../PATCHES.md`](../PATCHES.md) as the ordered index. Update the index
and the corresponding specification in the same pull request whenever a patch
is added, ported, accepted upstream, or retired. Release-branch commits and
release tags remain the implementation source of truth.
