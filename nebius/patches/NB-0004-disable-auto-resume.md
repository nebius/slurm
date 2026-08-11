---
id: NB-0004
title: Disable automatic resume for selected nodes
status: proposed
applies_to:
  - nebius/26.05
depends_on:
  - NB-0001
upstream: not-submitted
---

# NB-0004: Disable automatic resume for selected nodes

## Summary

Adds the `AutoResume` option to `NodeName` records. With
`AutoResume=off`, a node in `POWERED_DOWN` state is not available to the
scheduler, so submitting a job does not automatically invoke the node resume
path. The default is `on`, preserving upstream behavior.

An explicit administrator request such as `scontrol power up <nodes>` or
`scontrol update NodeName=<nodes> State=POWER_UP` still powers up the node.
Once it registers and leaves `POWERED_DOWN`, it is scheduled normally.

Example:

```ini
NodeName=ephemeral[001-100] State=CLOUD AutoResume=off
NodeSet=ephemeral Nodes=ephemeral[001-100]
PartitionName=batch Nodes=ephemeral
```

## Motivation

Nebius ephemeral workers can be intentionally kept stopped even while jobs
are queued. Operators or external capacity-management automation can then
decide when to create the instances instead of every schedulable job
implicitly triggering `ResumeProgram`.

## Scope

- Parse `AutoResume` on `NodeName` and `NodeName=DEFAULT` records.
- Accept `on` and `off` as boolean configuration values in addition to the
  existing boolean spellings.
- Keep `AutoResume=off` nodes out of the scheduler availability bitmap only
  while they are `POWERED_DOWN`.
- Preserve explicit administrator power-up and normal scheduling after node
  registration.
- Do not add `AutoResume` to `NodeSet`. A NodeSet is only a reusable node
  selection alias, may overlap another NodeSet, and does not own node policy.
  A `NodeName` range provides concise grouping without ambiguous precedence.

## Porting notes

The new field must be copied from `slurm_conf_node_t` into `config_record_t`,
included when configuration records are compared or duplicated, and default
to enabled in both structures. When porting, re-check the availability bitmap
construction and `make_node_avail()` path: a powered-down node with automatic
resume disabled must not become schedulable after startup, reconfigure, or
suspend completion.

Do not implement this solely by skipping `ResumeProgram`. At that point the
scheduler may already have allocated the powered-down node, which would leave
the job stuck in `CONFIGURING`.

## Validation

- `testsuite/python/tests/test_nb_0004_auto_resume.py` configures a CLOUD node
  with `AutoResume=off` and verifies that a submitted job remains `PENDING`.
- The same test verifies that the node remains `POWERED_DOWN` and that an
  explicit `scontrol` power-up is still honored.
- The frozen common suite continues to exercise the default automatic resume
  behavior for CLOUD nodes.

## History

- 2026-08-10: Initial implementation for `nebius/26.05`.
