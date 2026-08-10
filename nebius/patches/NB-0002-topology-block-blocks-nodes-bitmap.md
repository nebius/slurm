---
id: NB-0002
title: Fix node dropped from blocks_nodes_bitmap in topology/block
status: active
applies_to:
  - nebius/26.05
depends_on:
  - NB-0001
upstream: not-submitted
---

# NB-0002: Fix node dropped from blocks_nodes_bitmap in topology/block

## Summary

Keeps a node in the `topology/block` aggregate `blocks_nodes_bitmap` when its
topology is re-applied without change. Without this fix, assigning a node to
the block it already belongs to silently removes it from that bitmap, and jobs
touching the affected nodes stop being scheduled with block awareness:
`--segment` and `--spread-segments` are ignored without any error or log line.

## Motivation

Nebius clusters describe block topology in `topology.conf`, so every node is
already a member of its block when the controller starts. Any subsequent
re-application of the same topology therefore takes the no-op path in
`topology_p_add_rm_node()` and drains the node from the aggregate bitmap.

The corruption is reachable without any operator action, because slurmctld
itself re-applies a persisted `topology_str` on startup, on reconfigure, on
dynamic node re-registration, and on power save transitions. Since Nebius
enables power save for ephemeral nodes, an untouched cluster degrades on its
own. Once the candidate nodes of a job are all cleared, segment-based
placement is lost, which defeats the reason for running `topology/block` at
all.

The failure is silent and hard to attribute: `scontrol show topology` and
`scontrol show node` both keep reporting the correct topology, because they
render from state the bug does not touch.

## Scope

Included:

- `src/plugins/topology/block/topology_block.c`,
  `topology_p_add_rm_node()`: restore the aggregate bitmap bit for every block
  the node belongs to, not only when its membership transitions;
- the same function: recompute `ctx->blocks_nodes_cnt`, which was previously
  set only by `block_record_validate()` and went stale after dynamic adds and
  removals, skewing the fragmentation score used by
  `topology_p_get_frag()`.

Not included:

- any change to `topology/tree`, which short-circuits the no-op case and has
  no equivalent aggregate bitmap;
- any change to the operator-side workaround of not re-applying an unchanged
  topology, which remains valid and independent of this patch;
- coverage of the `blocks_nodes_cnt` recount, which only shifts the
  fragmentation score and has no directly observable output.

## Porting notes

- Apply after `NB-0001`, per the downstream ordering rule. There is no
  functional dependency between the two.
- The hunk applies without conflict to `slurm-25.11` (verified against
  25.11.5 and 25.11.7), `slurm-26.05` and upstream `master`.
- Release difference to watch: in `slurm-25.11` the unconditional
  `bit_clear(ctx->blocks_nodes_bitmap, ...)` sits *before* the block-name
  validation; upstream commit `bde6000c42` moved it after validation in
  `26.05` and `master`. That reordering fixes a different bug and does not
  affect this patch, but the surrounding context differs between releases.
- If upstream accepts the change, mark this entry `upstream since <release>`
  and drop the commit when the oldest supported release contains it.

## Validation

- `testsuite/python/tests/test_nb_0002_topology_block.py` is the regression
  test. On an eight-node `topology/block` cluster with `BlockName=b1
  Nodes=node[1-4]`, `BlockName=b2 Nodes=node[5-8]`, and `BlockSizes=4,8`, it
  re-applies to every node the block it already belongs to, then requires that
  a two-node and a three-node exclusive job still land in separate blocks and
  that a further three-node job stays pending instead of spanning both blocks.
  Without the fix the aggregate bitmap is empty after the redundant update,
  the generic node evaluation replaces `eval_nodes_block()`, and both
  assertions fail. It carries the patch identifier rather than an upstream
  `test_<group>_<n>.py` number so ports cannot collide with a future SchedMD
  test.
- Manual checks below remain useful on a real cluster.
- `topology/block` cluster with more than one block, `topology.conf`
  enumerating every worker.
- Re-apply an unchanged topology to a node
  (`scontrol update nodename=<X> topology=<name>:<block>`), then confirm
  segment placement still groups nodes by block:
  `srun -N30 --cpu-bind=none --segment=10 hostname | sort`.
  Before the fix the allocation ignores block boundaries; after it, nodes are
  grouped in blocks.
- Repeat after a slurmctld restart and after a power down/up cycle of an
  ephemeral node, since both re-apply the persisted topology through the same
  code path.
- `scontrol show topology` must stay unchanged throughout, since it renders
  from the per-block bitmaps that the bug never corrupted.

## History

- Initial specification for `nebius/26.05`. Bug present in all releases
  examined, from 25.11.3 through 26.05.3 and upstream `master`; not fixed
  upstream at the time of writing.
