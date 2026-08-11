---
id: NB-0003
title: Add node reboot operations to the Slurm REST API
status: active
applies_to:
  - nebius/26.05
depends_on:
  - NB-0001
upstream: not-submitted
---

# NB-0003: Add node reboot operations to the Slurm REST API

## Summary

Adds REST API equivalents of `scontrol reboot` for a node or a node list:

- `POST /slurm/v0.0.45/nodes/reboot`;
- `POST /slurm/v0.0.45/node/{node_name}/reboot`.

The request accepts `nodes`, `asap`, `force`, `next_state`, `reason`, and
`power_action`. The singular endpoint takes the target from the path and
ignores `nodes` from the body with a warning.

## Motivation

Nebius control-plane services use Slurm's REST interface. Rebooting compute
nodes should not require shelling out to `scontrol` or implementing Slurm RPC
transport separately.

## Scope

The patch:

- exposes the existing reboot RPC as the public `slurm_reboot_nodes()` API;
- makes `scontrol reboot` use that API rather than a private duplicate;
- adds the v0.0.44 and v0.0.45 data-parser request models;
- adds singular and plural `slurmrestd` routes;
- validates that `next_state` is unset, `DOWN`, or `RESUME` before sending the
  RPC;
- preserves the 26.05 `force` and `PowerAction` functionality.

It does not change slurmctld reboot scheduling, authorization, or power-action
execution. The controller continues to require a superuser and a valid
`RebootProgram` or reboot `PowerAction`.

Example request:

```json
{
  "nodes": "node[001-004]",
  "asap": true,
  "force": false,
  "next_state": ["RESUME"],
  "reason": "planned maintenance",
  "power_action": "reboot-slurmd"
}
```

## Porting notes

- The initial implementation is based on the working 25.11 downstream patch.
- Slurm 26.05 added `force` and named `PowerAction` support to `scontrol
  reboot`; keep those fields when porting the REST operation.
- Register the request model in the current data-parser version. Retain the
  v0.0.44 registration while that API remains supported by the target release.
- Recheck the valid `next_state` constants and `reboot_msg_t` whenever the
  reboot RPC changes upstream.
- If the patch is ported to a release with a new data-parser version, update
  the route tests and the downstream exception in that version's frozen
  OpenAPI specification test.

## Validation

- Build `libslurm`, `scontrol`, the v0.0.44 and v0.0.45 data parsers, and the
  slurmctld OpenAPI plugin.
- Run `testsuite/python/tests/test_nebius_reboot_rest_api.py`.
- Verify both paths and all request fields are present in the generated
  OpenAPI schema.
- Verify plural and singular successful requests put only the requested,
  allocated nodes into `REBOOT_REQUESTED` and preserve the supplied reason.
- Verify the plural route rejects a missing node list and invalid
  `next_state`, and that an invalid `power_action` is rejected by slurmctld.
- Run the full candidate comparison against the immutable 26.05 baseline.

## History

- 2026-08-11: Merged into `nebius/26.05`.
- Initial 26.05 port: adapted the existing 25.11 REST reboot patch to the
  26.05 `force` and named `PowerAction` semantics and added ATF coverage.
