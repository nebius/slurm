---
id: NB-0005
title: Refresh cloud registration fields after power up
status: active
applies_to:
  - nebius/26.05
depends_on:
  - NB-0001
upstream: not-submitted
implementation:
  - https://github.com/nebius/slurm/pull/56
  - https://github.com/nebius/slurm/pull/64
---

# NB-0005: Refresh cloud registration fields after power up

Upstream Slurm 26.05.6 fixes the main case of this problem in a different way
(see [Relation to the upstream fix](#relation-to-the-upstream-fix)). Since
`slurm-26-05-6-nebius-1` the downstream patch is a small addition on top of
the upstream gate. It may no longer be needed; this has not been verified.

## Summary

Apply slurmd-supplied `Topology`, `Extra`, `InstanceId`, and `InstanceType`
when a node registers from `POWERING_UP` or `POWERED_DOWN`, as well as when
its reported boot time advances past its last response. A new cloud instance
replaces the previous instance's metadata, including administrator overrides
from before the power transition. Ordinary re-registration and daemon
restarts continue to preserve administrator values.

## Motivation

The ticket 25041 backports in `slurm-26-05-3-nebius-2` gate these fields on
`boot_time > last_response`. During an expected power up,
`validate_node_specs()` first sets `last_response` to the current time to
avoid marking the node as unexpectedly rebooted. The subsequent field gate
therefore fails, silently discarding the values supplied by slurmd. Nodes
keep their configured fallback topology, so topology-aware scheduling uses
the wrong placement.

Both an administrator's `scontrol update State=POWER_UP` request and a
job-triggered resume reach this path.

## Relation to the upstream fix

Upstream fixed the same failure in 26.05.6 without power-state flags:

- `a403e46e74` "slurmctld - Apply slurmd-supplied node fields on node power
  up" compares `boot_time` with `last_response` saved before the registration
  (`orig_last_response`) and additionally requires that slurmd restarted since
  its last registration (`slurmd_restarted`).
- `c5743ef3ca` "slurmctld - Keep instance fields when an update interrupts a
  power up" ([SchedMD/slurm#232](https://github.com/SchedMD/slurm/pull/232))
  stops `_require_node_reg()` from refreshing `last_response` on a node that
  is powering up.

The upstream gate is `(boot_time > orig_last_response) && slurmd_restarted`.
It covers a power up where slurmd reports a boot time newer than the node's
previous response, which is the failure this patch was written for
(SCHED-2558). By code reading it does not apply the fields when the reported
boot time is older than the previous response, for example when slurmd starts
out of band on an already running host and the node registers from
`POWERED_DOWN`. The downstream patch keeps that case working.

Open question: whether Soperator still needs the remaining downstream
behaviour. To check, remove the downstream block and run
`test_nb_0005_cloud_registration.py`. If only
`test_powered_down_registration_refreshes_fields_without_reboot` fails and
that scenario is not required in production, retire this patch and that test.

## Scope

Up to `slurm-26-05-4-nebius-3`:

- Extend the shared field-application gate in
  `src/slurmctld/node_mgr.c:validate_node_specs()` with the saved
  `was_powering_up` and `was_powered_down` flags.
- Keep the existing timestamp gate for first registration and reboot
  detection, including its protection of administrator overrides during
  ordinary re-registration.

Since `slurm-26-05-6-nebius-1`:

- Leave the upstream gate and its comment unchanged.
- Insert one block before it in `validate_node_specs()`: when
  `was_powering_up` or `was_powered_down` is set, assign
  `orig_last_response = 0` and `slurmd_restarted = true`, so that the upstream
  gate passes. The block is a pure insertion and changes no upstream line.

In both versions:

- Add `testsuite/python/tests/test_nb_0005_cloud_registration.py`, with a
  minimum version of 26.05, independently of the 26.11-only upstream tests.

The earlier `waiting_for_node_boot()` check remains in force: a node in
`POWERING_UP` must report a boot time at least as recent as `boot_req_time`.
Container-based deployments reporting an older host boot time still need
`slurmd -b` for this path. Registration directly from `POWERED_DOWN` does not
have that earlier guard and can refresh fields without `-b`.

## Porting notes

Apply after `NB-0001` in the maintained queue. The 26.05 implementation builds
on backports `69f5ceed3f` (topology after reboot) and `3ee1b98e21`
(administrator-set instance fields), corresponding to upstream commits
`cf35c13a8f` and `78ac1f960f` for ticket 25041.

When porting, check the ordering of the power-state cleanup, field application,
and reboot detection in `validate_node_specs()`. The flags must capture the
state before it is cleared. Leave the expected-boot update of `last_response`
in place so normal power ups do not become unexpected reboots.

For release lines based on 26.05.6 or later:

- The downstream block overrides `orig_last_response` and `slurmd_restarted`.
  In 26.05.6 these two variables are read only by the field gate. On every
  upstream sync check that this is still true; if upstream starts using them
  elsewhere, the override silently changes that code as well.
- Because the block does not touch upstream lines, a change of the upstream
  gate does not produce a merge conflict. Review the gate by hand on every
  sync.
- Resolve the open question above before porting the patch to a new release
  line.

## Validation

In a disposable ATF installation built from the candidate branch, run:

```sh
testsuite/python/run-tests-python --auto-config \
  tests/test_nb_0005_cloud_registration.py
```

The regression test uses no-op resume/suspend programs and verifies:

- Administrator and job-triggered resumes reach `POWERING_UP` before slurmd
  starts with `-b --conf Topology=...`.
- Both first boot and a later power cycle refresh all four fields, including
  metadata previously set by an administrator.
- The node's `Topology` field and actual leaf-switch membership agree, and
  the node leaves the configured fallback switch.
- An ordinary slurmd restart preserves administrator overrides after a
  completed resume.
- Out-of-band startup from `POWERED_DOWN` refreshes the fields even when
  slurmd reports the existing host's uptime without `-b`.
- Expected power ups complete successfully with `ReturnToService=1` rather
  than being marked as unexpected reboots.

The patch-specific CI phase discovers the new test file automatically. The
frozen common suite and its baseline pointer are unchanged. A full Slurm ATF
run is required before merging; source and Python checks alone do not verify
the controller and daemon interactions.

## History

- 2026-09-17: Initial implementation for `nebius/26.05`, following the
  Soperator cloud-node registration failure tracked as SCHED-2558.
- 2026-11-17: Reworked during the sync with upstream 26.05.6 (#64), which carries
  its own fix for the power-up case. The gate is now the upstream one and the
  downstream change is a block that forces it open for `POWERING_UP` and
  `POWERED_DOWN` registrations. The regression test passes unchanged.
