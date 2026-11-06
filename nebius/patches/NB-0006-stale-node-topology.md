---
id: NB-0006
title: Recover from stale node topology assignments
status: proposed
applies_to:
  - nebius/26.05
depends_on:
  - NB-0001
upstream: not-submitted
---

# NB-0006: Recover from stale node topology assignments

## Summary

Allow slurmctld to start or reconfigure when a node's saved topology names a
block that no longer exists. Log the rejected assignment and try the
nonempty, different topology from the node's config record (from the current
`slurm.conf` for configured nodes). If there is no such fallback, or that
fallback also fails, clear the node's assignment and remove its membership
from every topology context. Continue applying topology to the remaining
nodes.

## Motivation

Soperator can remove an entire rack from `topology.yaml` while Slurm still
has powered-up CLOUD nodes with persisted assignments to that rack. During
configuration loading, `load_all_node_state()` restores those assignments
and `_set_nodes_topo()` reapplies them. The block plugin rejects a missing
block, causing configuration loading to fail.

With the foreground `slurmctld -D` invocation used by Soperator, reconfigure
executes the replacement controller in place. A configuration-loading fatal
therefore terminates the controller immediately; there is no surviving
parent daemon to keep serving requests. A successful reconfigure RPC reply
does not establish that the replacement controller started successfully.

Dynamic-node creation already logs and discards invalid topology supplied
by slurmd. This patch applies a similar recovery policy during configuration
loading, without clearing jobs or other saved controller state.

## Scope

- Change only `_set_nodes_topo()` in `src/slurmctld/read_config.c`.
- Apply the recovery policy to all node types, including static nodes. This
  function also runs on a clean start, so invalid node-level `Topology=`
  values are logged and discarded there too; the policy is not limited to
  values proven to originate in saved state.
- Reapply the fallback or empty assignment through
  `topology_g_add_rm_node()`. Its comma-separated context updates are not
  transactional: a tree assignment may already have succeeded when a later
  block assignment fails. Freeing the string alone would leave membership
  inconsistent. Empty switch definitions created by an earlier attempt can
  remain, but the node must no longer belong to those switches.
- Check the fallback result and retry with an empty assignment if necessary.
  If even removal fails, retain the configuration-loading error rather than
  claiming that the topology is consistent.
- Preserve the existing `topology_orig_str` handling for power-save resets.
  Clearing the current assignment removes even memberships supplied by
  `topology.yaml`; it does not restore the YAML baseline at this point.
- Keep block validation, explicit administrator topology updates, and node
  registration logic unchanged. Do not create missing blocks at runtime.

Node state is unchanged: this patch does not drain or quarantine a node that
loses its topology. Block scheduling can use generic node evaluation when
its candidate set has no overlap with configured blocks. Operators requiring
block placement guarantees must account for nodes without membership. A
later registration can restore topology only when the existing registration
field-update gate permits it; ordinary re-registration is not guaranteed to
do so. A valid explicit topology update can also restore membership.

## Porting notes

Apply after `NB-0001` in the maintained queue. Check `_set_nodes_topo()`,
`load_all_node_state()`, and `topology_g_add_rm_node()` when porting. In
particular, verify that an empty assignment removes a node from every
context, and that fallback strings are owned independently of the config
record. Do not change the interface to silently accept invalid administrator
updates.

## Validation

In a disposable ATF installation built from the candidate branch, run:

```sh
testsuite/python/run-tests-python --auto-config \
  tests/test_nb_0006_stale_node_topology.py
```

The regression tests must verify:

- Restart with preserved state and foreground (`-D`) reconfigure after
  removing a block both recover without a cold start.
- An absent or identical configured fallback clears the stale assignment;
  a valid different fallback is applied; an invalid different fallback is
  cleared as well.
- Partial tree membership and YAML block membership are repaired, and a
  later node still receives its valid saved assignment.
- The resulting node assignment and actual topology membership agree.
- A further restart remains healthy. When the saved string is empty and
  no node-level topology is configured, the YAML baseline applies again.
- Invalid configured topology on a static node is also cleared on a clean
  start, while an explicit update to a missing block still returns an error.

The test file is discovered automatically by the patch-specific CI phase.
Run full ATF validation on Linux before merging. Source and Python checks
alone do not replace daemon and plugin integration tests. Also verify
foreground reconfigure in the Soperator deployment, rack
stop/start, and full cluster stop/start with the state volume preserved.

## History

- 2026-11-03: Initial implementation for `nebius/26.05`, addressing stale rack
  assignments tracked as SCHED-2738.
