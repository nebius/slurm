#!/usr/bin/env bash
set -euo pipefail

if (($# != 6)); then
	echo "usage: $0 PUBLIC_IP REMOTE_ROOT RUN_ID SOURCE_COMMIT TESTS_COMMIT SELECTION" >&2
	exit 2
fi

public_ip="$1"
remote_root="$2"
run_id="$3"
source_commit="$4"
tests_commit="$5"
selection_file="$(realpath "$6")"

: "${SLURM_ATF_SSH_PRIVATE_KEY_FILE:?}"
: "${SLURM_ATF_SSH_KNOWN_HOSTS_FILE:?}"
: "${SLURM_ATF_SSH_USER:?}"

[[ "${public_ip}" =~ ^[0-9a-fA-F:.]+$ ]]
[[ "${remote_root}" == /home/${SLURM_ATF_SSH_USER}/* ]]
[[ "${run_id}" =~ ^[a-zA-Z0-9._-]+$ ]]
[[ "${source_commit}" =~ ^[0-9a-f]{40}$ ]]
[[ "${tests_commit}" =~ ^[0-9a-f]{40}$ ]]
test -s "${selection_file}"
jq -e '.schema == 1 and (.selected_files | length > 0)' \
	"${selection_file}" >/dev/null

remote_selection="${remote_root}/patch-selection.json"
scp \
	-i "${SLURM_ATF_SSH_PRIVATE_KEY_FILE}" \
	-o BatchMode=yes \
	-o ServerAliveInterval=30 \
	-o ServerAliveCountMax=6 \
	-o StrictHostKeyChecking=yes \
	-o "UserKnownHostsFile=${SLURM_ATF_SSH_KNOWN_HOSTS_FILE}" \
	"${selection_file}" \
	"${SLURM_ATF_SSH_USER}@${public_ip}:${remote_selection}"

ssh \
	-i "${SLURM_ATF_SSH_PRIVATE_KEY_FILE}" \
	-o BatchMode=yes \
	-o ServerAliveInterval=30 \
	-o ServerAliveCountMax=60 \
	-o StrictHostKeyChecking=yes \
	-o "UserKnownHostsFile=${SLURM_ATF_SSH_KNOWN_HOSTS_FILE}" \
	"${SLURM_ATF_SSH_USER}@${public_ip}" \
	bash -s -- \
		"${remote_root}" \
		"${run_id}" \
		"${source_commit}" \
		"${tests_commit}" <<'REMOTE'
set -euo pipefail
root="$1"
run_id="$2"
source_commit="$3"
tests_commit="$4"

source_dir="${root}/source"
common_tests_dir="${root}/tests"
patch_tests_dir="${root}/patch-tests"
infra_dir="${root}/external-infra/slurm-atf/infra"
build_dir="${root}/build"
selection="${root}/patch-selection.json"
output_dir="${root}/patch-result"
atf_root=/opt/slurm-atf
install_dir="${atf_root}/install"
common_run_dir="${atf_root}/results/${run_id}"
patch_run_dir="${atf_root}/results/${run_id}-patch"
manifest="${common_run_dir}/run-manifest.json"

[[ "${root}" == /home/*/slurm-atf ]]
[[ "${run_id}" =~ ^[a-zA-Z0-9._-]+$ ]]
[[ "${source_commit}" =~ ^[0-9a-f]{40}$ ]]
[[ "${tests_commit}" =~ ^[0-9a-f]{40}$ ]]
sudo test -f /etc/slurm-atf-disposable
test -f "${source_dir}/META"
test -x "${source_dir}/testsuite/python/run-tests-python"
test -x "${infra_dir}/configure-atf.sh"
test -x "${atf_root}/run-env.sh"
test -x "${install_dir}/bin/sinfo"
test -d "${build_dir}"
test -s "${manifest}"
test "$(jq -er '.release.commit' "${manifest}")" = "${source_commit}"
test "$(jq -er '.tests.master_commit' "${manifest}")" = "${tests_commit}"
jq -e '.schema == 1 and (.selected_files | length > 0)' "${selection}" >/dev/null

mkdir -p "${patch_tests_dir}" "${output_dir}"
find "${patch_tests_dir}" -mindepth 1 -delete
rsync -a --delete --exclude=.git "${source_dir}/" "${patch_tests_dir}/"
sudo chown -R atf:atf "${patch_tests_dir}"

while IFS=$'\t' read -r repository_path expected_sha256; do
	[[ "${repository_path}" =~ ^testsuite/python/(expect|tests)/test_[A-Za-z0-9_.-]+\.py$ ]]
	test -f "${patch_tests_dir}/${repository_path}"
	test "$(sha256sum "${patch_tests_dir}/${repository_path}" | awk '{print $1}')" = \
		"${expected_sha256}"
done < <(jq -er '.selected_files[] | [.repository_path, .sha256] | @tsv' "${selection}")

sudo -u atf -H env \
	SLURM_SUT_SOURCE_DIR="${source_dir}" \
	SLURM_SUT_BUILD_DIR="${build_dir}" \
	SLURM_SUT_INSTALL_DIR="${install_dir}" \
	SLURM_TESTS_SOURCE_DIR="${patch_tests_dir}" \
	SLURM_ATF_PROFILE=generic \
	"${infra_dir}/configure-atf.sh"

sudo -u atf -H mkdir -p "${patch_run_dir}"
sudo -u atf cp "${selection}" "${patch_run_dir}/selection.json"
mapfile -t selected_files < <(jq -er '.selected_files[].path' "${selection}")
((${#selected_files[@]} > 0))

date -u --iso-8601=seconds |
	sudo -u atf tee "${patch_run_dir}/started-utc" >/dev/null
set +e
sudo -u atf -H env \
	SLURM_SUT_SOURCE_DIR="${source_dir}" \
	SLURM_SUT_BUILD_DIR="${build_dir}" \
	SLURM_SUT_INSTALL_DIR="${install_dir}" \
	SLURM_TESTS_SOURCE_DIR="${patch_tests_dir}" \
	SLURM_RELEASE_MANIFEST="${manifest}" \
	SLURM_ATF_RUN_ID="${run_id}-patch" \
	SLURM_ATF_VM_PROFILE=h200 \
	"${atf_root}/run-env.sh" \
	"${patch_tests_dir}/testsuite/python/run-tests-python" \
	--auto-config \
	-vv \
	-s \
	-ra \
	--tb=long \
	--durations=100 \
	--junitxml="${patch_run_dir}/junit.xml" \
	"${selected_files[@]}" 2>&1 |
	sudo -u atf tee "${patch_run_dir}/pytest.out"
status=${PIPESTATUS[0]}
set -e
printf '%s\n' "${status}" |
	sudo -u atf tee "${patch_run_dir}/pytest-exit-status" >/dev/null
date -u --iso-8601=seconds |
	sudo -u atf tee "${patch_run_dir}/finished-utc" >/dev/null

sudo install -d -o atf -g atf -m 0755 \
	"${patch_run_dir}/daemon-logs" "${patch_run_dir}/config"
if [[ -d /var/log/slurm-atf ]]; then
	sudo rsync -a --delete /var/log/slurm-atf/ "${patch_run_dir}/daemon-logs/"
fi
sudo find "${install_dir}/etc" -maxdepth 1 -type f -name '*.conf' \
	-exec cp -p {} "${patch_run_dir}/config/" \;
sudo chown -R atf:atf "${patch_run_dir}/daemon-logs" "${patch_run_dir}/config"
# Some daemon logs and configuration files intentionally remain mode 0600.
# Copy them with privilege, then hand the exported evidence back to the SSH
# user so that the following scp step can download every file.
sudo rsync -a --delete "${patch_run_dir}/" "${output_dir}/"
sudo chown -R "$(id -u):$(id -g)" "${output_dir}"

if [[ "${status}" != 0 && "${status}" != 1 ]]; then
	echo "Patch tests did not complete normally (exit status ${status})" >&2
	exit "${status}"
fi
echo "Patch-specific tests completed; raw pytest status: ${status}."
REMOTE
