# Slurm ATF H200 image

This directory builds the immutable image required by the `h200` ATF profile
on one 8xH200 VM. Project and subnet placement are mandatory Packer variables;
no Nebius tenant identifiers are committed to the repository.

The current CPU-only image `computeimage-e00sphs75y9ej9nw9j` cannot be attached
to `gpu-h200-sxm`. The template therefore starts from the public Ubuntu 24.04
CUDA 13 image `computeimage-e00dyqcvp4vzdvkg3b`, verifies all eight H200 GPUs,
and installs the same pinned ATF dependency stack used by the workflow.
`valgrind` is installed only when its matching Ubuntu `libc6-dbg` package is
available; the normal full suite does not enable its optional diagnostic mode.
Ubuntu installs Lmod outside the default executable search path; the runtime
harness exposes it as `/opt/slurm-atf/bin/lmod` and fails early if it is
missing, instead of silently skipping the module tests.

Prerequisites:

- Packer 1.16.0;
- Nebius CLI configured with access to the target project;
- quota and capacity for `gpu-h200-sxm/8gpu-128vcpu-1600gb` in the target
  subnet.

Build:

```sh
cd nebius/ci/images/slurm-atf-h200
unset PKR_VAR_packer_ssh_private_key_file
export PKR_VAR_nebius_token="$(nebius iam get-access-token --profile default)"
export PKR_VAR_parent_id=project-e00example
export PKR_VAR_subnet_id=vpcsubnet-e00example
packer init .
packer fmt -check .
packer validate .
packer build .
unset PKR_VAR_nebius_token
unset PKR_VAR_parent_id
unset PKR_VAR_subnet_id
```

Do not set `PKR_VAR_packer_ssh_private_key_file`. The Nebius plug-in's generated
temporary key is the verified connection path for this image. It is injected
into cloud-init for the builder and discarded automatically during cleanup.

Packer prints the resulting `computeimage-*` ID. Verify it before spending a
full test run:

```sh
nebius compute image get --id <computeimage-id> --format json | jq '{metadata, spec, status}'
```

The resulting image must be `READY`, `AMD64`, and recommend
`gpu-h200-sxm`. Use that ID as the baseline workflow's `image_id`, select
`atf_profile=h200`, and configure the `e2e` environment VM profile as described
in the repository documentation.

Here `atf_profile=h200` selects and validates the physical VM. The full
Expect/Python suite deliberately runs a four-CPU, hardware-neutral `generic`
Slurm configuration inside that VM so ATF can create synthetic nodes without
cloning physical H200 GRES. Real-GPU checks should use a separate smoke/shard.

No GPU cluster is needed for this single-VM ATF image build. The exact image
ID is recorded by the baseline workflow and inherited by candidate runs.
