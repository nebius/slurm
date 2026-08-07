#!/usr/bin/env bash
set -euo pipefail

if (($# != 11)); then
	echo "usage: $0 PHASE PUBLIC_IP REMOTE_ROOT RUN_ID RELEASE_LINE SOURCE_COMMIT TESTS_COMMIT VM_PROFILE SHARD_ID SHARD_INDEX SHARD_TOTAL" >&2
	exit 2
fi

phase="$1"
public_ip="$2"
remote_root="$3"
run_id="$4"
release_line="$5"
source_commit="$6"
tests_commit="$7"
vm_profile="$8"
shard_id="$9"
shard_index="${10}"
shard_total="${11}"

: "${SLURM_ATF_SSH_PRIVATE_KEY_FILE:?}"
: "${SLURM_ATF_SSH_KNOWN_HOSTS_FILE:?}"
: "${SLURM_ATF_SSH_USER:?}"

[[ "${phase}" == expect || "${phase}" == pytest ]]
[[ "${public_ip}" =~ ^[0-9a-fA-F:.]+$ ]]
[[ "${remote_root}" == /home/${SLURM_ATF_SSH_USER}/* ]]
[[ "${run_id}" =~ ^[a-zA-Z0-9._-]+$ ]]
[[ "${release_line}" =~ ^[0-9]+\.[0-9]+$ ]]
[[ "${source_commit}" =~ ^[0-9a-f]{40}$ ]]
[[ "${tests_commit}" =~ ^[0-9a-f]{40}$ ]]
[[ "${vm_profile}" == generic || "${vm_profile}" == h200 ]]
[[ "${shard_id}" =~ ^[a-zA-Z0-9._-]+$ ]]
[[ "${shard_index}" =~ ^[0-9]+$ ]]
[[ "${shard_total}" =~ ^[1-9][0-9]*$ ]]

ssh \
	-i "${SLURM_ATF_SSH_PRIVATE_KEY_FILE}" \
	-o BatchMode=yes \
	-o ServerAliveInterval=30 \
	-o ServerAliveCountMax=60 \
	-o StrictHostKeyChecking=yes \
	-o "UserKnownHostsFile=${SLURM_ATF_SSH_KNOWN_HOSTS_FILE}" \
	"${SLURM_ATF_SSH_USER}@${public_ip}" \
	bash -s -- \
		"${phase}" \
		"${remote_root}" \
		"${run_id}" \
		"${release_line}" \
		"${source_commit}" \
		"${tests_commit}" \
		"${vm_profile}" \
		"${shard_id}" \
		"${shard_index}" \
		"${shard_total}" <<'REMOTE'
set -euo pipefail
phase="$1"
root="$2"
run_id="$3"
release_line="$4"
source_commit="$5"
tests_commit="$6"
vm_profile="$7"
shard_id="$8"
shard_index="$9"
shard_total="${10}"
source_dir="${root}/source"
tests_dir="${root}/tests"
infra_dir="${root}/external-infra/slurm-atf/infra"
build_dir="${root}/build"
output_dir="${root}/result"

# The ATF user needs directory traversal, but not listing access, to execute
# the copied harness and tests below the CI user's home.
chmod o+x "${HOME}"
mkdir -p "${output_dir}"
set +e
"${tests_dir}/nebius/ci/atf/run-full-suite.sh" \
	"${phase}" \
	"${source_dir}" \
	"${tests_dir}" \
	"${infra_dir}" \
	"${build_dir}" \
	"${output_dir}" \
	"${run_id}" \
	"${release_line}" \
	"${source_commit}" \
	"${tests_commit}" \
	"${vm_profile}" \
	"${shard_id}" \
	"${shard_index}" \
	"${shard_total}" \
	2>&1 | tee "${root}/orchestration-${phase}.log"
status=${PIPESTATUS[0]}
set -e
exit "${status}"
REMOTE
