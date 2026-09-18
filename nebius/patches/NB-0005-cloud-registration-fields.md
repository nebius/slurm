---
id: NB-0005
title: Refresh cloud registration fields after power up
status: proposed
applies_to:
  - nebius/26.05
depends_on:
  - NB-0001
upstream: not-submitted
---

# NB-0005: Refresh cloud registration fields after power up

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
job-triggered resume reach this path. Moving the timestamp comparison earlier
would also depend on the uptime reported by slurmd; explicit power-state
flags express the instance lifecycle directly.

## Scope

- Extend the shared field-application gate in
  `src/slurmctld/node_mgr.c:validate_node_specs()` with the saved
  `was_powering_up` and `was_powered_down` flags.
- Keep the existing timestamp gate for first registration and reboot
  detection, including its protection of administrator overrides during
  ordinary re-registration.
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
