#!/usr/bin/env bash
set -euo pipefail

if (($# != 14)); then
	echo "usage: $0 PHASE SOURCE_DIR TESTS_DIR INFRA_DIR BUILD_DIR OUTPUT_DIR RUN_ID RELEASE_LINE SOURCE_COMMIT TESTS_COMMIT VM_PROFILE SHARD_ID SHARD_INDEX SHARD_TOTAL" >&2
	exit 2
fi

phase="$1"
shift
source_dir="$(realpath "$1")"
tests_dir="$(realpath "$2")"
infra_dir="$(realpath "$3")"
build_dir="$(realpath -m "$4")"
output_dir="$(realpath -m "$5")"
run_id="$6"
release_line="$7"
source_commit="$8"
tests_commit="$9"
vm_profile="${10}"
shard_id="${11}"
shard_index="${12}"
shard_total="${13}"
atf_profile=generic

atf_root=/opt/slurm-atf
install_dir="${atf_root}/install"
pmix_prefix="${atf_root}/pmix/5.0.11"
openmpi_prefix="${atf_root}/openmpi/5.0.9"
mpich_version=5.0.1
mpich_device=ch3:sock
mpich_profile="${mpich_device//:/-}"
mpich_source="${atf_root}/src/mpich-${mpich_version}"
mpich_build="${atf_root}/build/mpich-${mpich_version}-${mpich_profile}"
mpich_prefix="${atf_root}/mpich/${mpich_version}-${mpich_profile}"
run_dir="${atf_root}/results/${run_id}"
manifest="${run_dir}/run-manifest.json"
jobs="${BUILD_JOBS:-$(nproc)}"
phase_status=0

[[ "${phase}" == expect || "${phase}" == pytest ]]
[[ "${run_id}" =~ ^[a-zA-Z0-9._-]+$ ]]
[[ "${release_line}" =~ ^[0-9]+\.[0-9]+$ ]]
[[ "${source_commit}" =~ ^[0-9a-f]{40}$ ]]
[[ "${tests_commit}" =~ ^[0-9a-f]{40}$ ]]
[[ "${vm_profile}" == generic || "${vm_profile}" == h200 ]]
[[ "${shard_id}" =~ ^[a-zA-Z0-9._-]+$ ]]
[[ "${shard_index}" =~ ^[0-9]+$ ]]
[[ "${shard_total}" =~ ^[1-9][0-9]*$ ]]
((shard_index < shard_total))
if ((shard_index == shard_total - 1)); then
	[[ "${vm_profile}" == h200 ]]
else
	[[ "${vm_profile}" == generic ]]
fi
[[ "${jobs}" =~ ^[1-9][0-9]*$ ]]

sudo test -f /etc/slurm-atf-disposable
test -s /etc/slurm-atf-image.json
test -f "${source_dir}/META"
test -x "${source_dir}/configure"
test -d "${tests_dir}/testsuite/expect"
test -d "${tests_dir}/testsuite/python/expect"
test -d "${tests_dir}/testsuite/python/tests"
test -x "${tests_dir}/testsuite/run-tests"
test -x "${tests_dir}/testsuite/python/run-tests-python"
test -f "${tests_dir}/nebius/ci/atf/merge_junit.py"
test -f "${tests_dir}/nebius/ci/atf/shard_tests.py"
test -x "${pmix_prefix}/bin/pmix_info"
test -x "${openmpi_prefix}/bin/mpirun"
test -x "${mpich_source}/configure"
test -x "${infra_dir}/configure-atf.sh"
jq -e '
  .schema == 1 and
  .os.id == "ubuntu" and
  .os.version == "24.04" and
  .os.architecture == "amd64" and
  .stack.pmix_tag == "v5.0.11" and
  .stack.openmpi_tag == "v5.0.9" and
  .stack.mpich_version == "5.0.1"
' /etc/slurm-atf-image.json >/dev/null

if [[ "${vm_profile}" == h200 ]]; then
	command -v nvidia-smi >/dev/null
	test -x /usr/local/cuda/bin/nvcc
	test -f /usr/local/cuda/include/nvml.h
	jq -e '
	  .gpu.profile == "h200" and
	  .gpu.count == 8 and
	  .gpu.product == "NVIDIA H200"
	' /etc/slurm-atf-image.json >/dev/null
	mapfile -t gpu_names < <(
		nvidia-smi --query-gpu=name --format=csv,noheader
	)
	((${#gpu_names[@]} == 8))
	for gpu_name in "${gpu_names[@]}"; do
		[[ "${gpu_name}" == *H200* ]]
	done
fi

requirements_sha256="$(sha256sum "${infra_dir}/requirements.lock" | awk '{print $1}')"
test "${requirements_sha256}" = \
	"$(jq -er '.python_requirements_sha256' /etc/slurm-atf-image.json)"

configure_atf() {
	sudo -u atf -H env \
		SLURM_SUT_SOURCE_DIR="${source_dir}" \
		SLURM_SUT_BUILD_DIR="${build_dir}" \
		SLURM_SUT_INSTALL_DIR="${install_dir}" \
		SLURM_TESTS_SOURCE_DIR="${tests_dir}" \
		SLURM_ATF_PROFILE="${atf_profile}" \
		"${infra_dir}/configure-atf.sh"
}

disable_broken_modules_profile() {
	local modules_profile=/etc/profile.d/modules.sh
	local modules_init=/usr/share/modules/init/sh
	local disabled_profile=/etc/profile.d/modules.sh.disabled-by-slurm-atf

	# Some GPU images ship an Environment Modules profile that sources a
	# missing init script. Every ATF login shell then prefixes stderr with an
	# unrelated error and breaks tests that assert the first diagnostic line.
	if [[ -f "${modules_profile}" ]] &&
		grep -Fq "${modules_init}" "${modules_profile}" &&
		[[ ! -f "${modules_init}" ]]; then
		sudo mv -f "${modules_profile}" "${disabled_profile}"
	fi
}

ensure_lmod_command() {
	local lmod_executable=/usr/share/lmod/lmod/libexec/lmod
	local lmod_link="${atf_root}/bin/lmod"

	# Ubuntu installs Lmod's executable outside the default PATH. ATF checks
	# for and invokes a literal `lmod` command, so leaving it there silently
	# skips the module tests even though the package and modulefiles exist.
	if sudo -u atf -H "${atf_root}/run-env.sh" \
		sh -c 'command -v lmod >/dev/null 2>&1'; then
		return
	fi

	if [[ ! -x "${lmod_executable}" ]]; then
		echo "Lmod is required by the full ATF suite, but ${lmod_executable} is unavailable" >&2
		return 1
	fi

	sudo install -d -o root -g root -m 0755 "$(dirname "${lmod_link}")"
	sudo ln -sfn "${lmod_executable}" "${lmod_link}"
	sudo -u atf -H "${atf_root}/run-env.sh" \
		sh -c 'command -v lmod >/dev/null 2>&1'
}

legacy_topology_makefile=""
legacy_topology_dir_created=false

prepare_release_configure_compat() {
	local topology_dir="${source_dir}/testsuite/slurm_unit/topology"
	local topology_makefile="${topology_dir}/Makefile.in"

	# The 26.05 release configure script still emits a Makefile for the old
	# topology unit-test directory. That test was removed on master, so an
	# NB-0001 testsuite sync intentionally removes its Makefile.in while the
	# otherwise vanilla release configure script continues to require it.
	if ! grep -Fq 'testsuite/slurm_unit/topology/Makefile' \
		"${source_dir}/configure" || [[ -e "${topology_makefile}" ]]; then
		return
	fi
	if grep -Eq '(^|[[:space:]])topology([[:space:]]|$)' \
		"${source_dir}/testsuite/slurm_unit/Makefile.am"; then
		echo "Refusing to mask a missing topology Makefile.in for a topology directory that is still built" >&2
		return 1
	fi

	if [[ ! -d "${topology_dir}" ]]; then
		mkdir -p "${topology_dir}"
		legacy_topology_dir_created=true
	fi
	printf '%s\n' \
		'# Temporary compatibility input for a release configure script.' \
		>"${topology_makefile}"
	legacy_topology_makefile="${topology_makefile}"
}

cleanup_release_configure_compat() {
	if [[ -z "${legacy_topology_makefile}" ]]; then
		return
	fi
	rm -f "${legacy_topology_makefile}"
	if [[ "${legacy_topology_dir_created}" == true ]]; then
		rmdir "$(dirname "${legacy_topology_makefile}")"
	fi
	legacy_topology_makefile=""
	legacy_topology_dir_created=false
}

prepare_release_build_compat() {
	local testsuite_makefile="${build_dir}/testsuite/Makefile"
	local synced_subdirs='SUBDIRS = expect slurm_unit'

	# Master has an Automake-only testsuite/expect directory, but the 26.05
	# release configure script does not emit its Makefile. The wrappers are
	# executed directly from tests_dir later, so do not descend into this empty
	# build-only directory when compiling and installing the vanilla release.
	if grep -Fq 'testsuite/expect/Makefile' "${source_dir}/configure"; then
		return
	fi
	test -f "${testsuite_makefile}"
	if ! grep -Fxq "${synced_subdirs}" "${testsuite_makefile}"; then
		echo "Release configure does not support testsuite/expect, but the generated testsuite SUBDIRS are unexpected" >&2
		return 1
	fi
	sed -i \
		's/^SUBDIRS = expect slurm_unit$/SUBDIRS = slurm_unit/' \
		"${testsuite_makefile}"
}

prepare_build() {
	local configure_status=0

	mkdir -p "${build_dir}" "${output_dir}"
	sudo install -d -o root -g root -m 0755 "${install_dir}"
	sudo find "${install_dir}" -mindepth 1 -delete

	bpf_root=/usr
	bpf_uapi_root="${atf_root}/kernel-uapi"
	kernel_bpf_header="/usr/src/linux-headers-$(uname -r)/include/uapi/linux/bpf.h"
	if [[ -f "${kernel_bpf_header}" ]] &&
		grep -q BPF_TOKEN_CREATE "${kernel_bpf_header}"; then
		sudo install -D -m 0644 "${kernel_bpf_header}" \
			"${bpf_uapi_root}/include/linux/bpf.h"
		bpf_root="${bpf_uapi_root}"
	fi

	nvml_args=()
	if [[ -f /usr/local/cuda/include/nvml.h ]]; then
		nvml_args+=(--with-nvml=/usr/local/cuda)
	fi

	prepare_release_configure_compat
	cd "${build_dir}"
	PKG_CONFIG_PATH="${pmix_prefix}/lib/pkgconfig" \
	CPPFLAGS="-I${bpf_root}/include" \
	"${source_dir}/configure" \
		--prefix="${install_dir}" \
		--sysconfdir="${install_dir}/etc" \
		--localstatedir=/var/lib/slurm-atf \
		--runstatedir=/run/slurm-atf \
		--enable-multiple-slurmd \
		--enable-pam \
		"${nvml_args[@]}" \
		--with-pmix="${pmix_prefix}" \
		--with-json=/usr \
		--with-jwt=/usr \
		--with-yaml=/usr \
		--with-hdf5=yes \
		--with-lz4=/usr \
		--with-hwloc=/usr \
		--with-bpf="${bpf_root}" \
		--with-lua \
		--with-freeipmi=/usr \
		CFLAGS="-O2 -g3 -fno-omit-frame-pointer" || configure_status=$?
	cleanup_release_configure_compat
	if ((configure_status != 0)); then
		return "${configure_status}"
	fi
	prepare_release_build_compat

	make -j"${jobs}"
	sudo make install
	sudo make -C contribs/pmi2 install
	sudo make -C contribs/pmi install
	sudo make -C contribs/perlapi install
	for contrib in torque openlava seff; do
		sudo make -C "contribs/${contrib}" install
	done
	sudo install -o root -g root -m 0755 \
		"${source_dir}/src/plugins/burst_buffer/datawarp/dw_wlm_cli" \
		"${install_dir}/sbin/dw_wlm_cli"
	sudo install -o root -g root -m 0755 \
		"${source_dir}/src/plugins/burst_buffer/datawarp/dwstat" \
		"${install_dir}/sbin/dwstat"

	sudo find "${mpich_build}" -mindepth 1 -delete 2>/dev/null || true
	sudo find "${mpich_prefix}" -mindepth 1 -delete 2>/dev/null || true
	sudo install -d -o "$(id -u)" -g "$(id -g)" -m 0755 \
		"${mpich_build}" "${mpich_prefix}"
	cd "${mpich_build}"
	LD_LIBRARY_PATH="${install_dir}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
	"${mpich_source}/configure" \
		--prefix="${mpich_prefix}" \
		--with-pmilib=slurm \
		--with-pmi=pmi2 \
		--with-pm=none \
		--with-slurm="${install_dir}" \
		--with-device="${mpich_device}" \
		--disable-fortran \
		CPPFLAGS="-DMISSING_PMI2_KEYVAL_T" \
		CFLAGS="-O2 -g3 -fno-omit-frame-pointer"
	make -j"${jobs}"
	make install

	# Tests modify generated configuration and temporary files, but never the
	# separate source-under-test checkout.
	sudo chown -R atf:atf "${tests_dir}"
	disable_broken_modules_profile
	configure_atf
	ensure_lmod_command
}

write_manifest() {
	local manifest_tmp
	local release_version
	release_version="$(awk '$1 == "Version:" {print $2; exit}' "${source_dir}/META")"
	manifest_tmp="$(mktemp)"
	jq -n \
		--arg release_line "${release_line}" \
		--arg release_version "${release_version}" \
		--arg source_commit "${source_commit}" \
		--arg tests_commit "${tests_commit}" \
		--arg atf_profile "${atf_profile}" \
		--arg vm_profile "${vm_profile}" \
		--arg shard_id "${shard_id}" \
		--argjson shard_index "${shard_index}" \
		--argjson shard_total "${shard_total}" \
		'{
		  schema: 1,
		  release: {
		    line: $release_line,
		    version: $release_version,
		    commit: $source_commit
		  },
		  tests: {master_commit: $tests_commit},
		  atf: {profile: $atf_profile, vm_profile: $vm_profile},
		  shard: {id: $shard_id, index: $shard_index, total: $shard_total}
		}' >"${manifest_tmp}"
	sudo install -o atf -g atf -m 0644 "${manifest_tmp}" "${manifest}"
	rm -f "${manifest_tmp}"
	sudo install -o atf -g atf -m 0644 /etc/slurm-atf-image.json \
		"${run_dir}/image-metadata.json"
}

capture_inventory() {
	{
		echo "run_id=${run_id}"
		echo "host=$(hostname -f)"
		echo "slurm_version=$(${install_dir}/bin/sinfo --version)"
		echo "tests_master_commit=${tests_commit}"
		echo "atf_profile=${atf_profile}"
		echo "vm_profile=${vm_profile}"
		echo "shard_id=${shard_id}"
		echo "shard_index=${shard_index}"
		echo "shard_total=${shard_total}"
	} | sudo -u atf tee "${run_dir}/run-info.txt" >/dev/null
	if command -v nvidia-smi >/dev/null 2>&1; then
		nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total \
			--format=csv,noheader |
			sudo -u atf tee "${run_dir}/gpu-inventory.csv" >/dev/null || \
			printf '%s\n' "nvidia-smi present but no GPU inventory available" |
				sudo -u atf tee "${run_dir}/gpu-inventory.csv" >/dev/null
	else
		printf '%s\n' "no NVIDIA driver on this VM" |
			sudo -u atf tee "${run_dir}/gpu-inventory.csv" >/dev/null
	fi
	sudo -u atf -H "${atf_root}/run-env.sh" env | sort |
		sudo -u atf tee "${run_dir}/environment.txt" >/dev/null
	dpkg-query -W -f='${binary:Package}\t${Version}\n' | sort |
		sudo -u atf tee "${run_dir}/package-inventory.tsv" >/dev/null
}

capture_phase_evidence() {
	local label="$1"
	local daemon_dir="${run_dir}/daemon-logs/${label}"
	local config_dir="${run_dir}/config/${label}"
	sudo install -d -o atf -g atf -m 0755 "${daemon_dir}" "${config_dir}"
	if [[ -d /var/log/slurm-atf ]]; then
		sudo rsync -a --delete /var/log/slurm-atf/ "${daemon_dir}/"
	fi
	sudo find "${install_dir}/etc" -maxdepth 1 -type f -name '*.conf' \
		-exec cp -p {} "${config_dir}/" \;
	sudo chown -R atf:atf "${daemon_dir}" "${config_dir}"
	sudo -u atf -H bash -c \
		'cd "$1" && find . -type f -name "*.conf" -print0 | sort -z | xargs -0 -r sha256sum' \
		_ "${config_dir}" |
		sudo -u atf tee "${run_dir}/config-${label}.sha256" >/dev/null
}

run_pytest_group() {
	local label="$1"
	local phase="$2"
	local junit_file="${run_dir}/${label}-junit.xml"
	local log_file="${run_dir}/${label}.out"
	local status_file="${run_dir}/${label}-exit-status"
	local selection_file="${run_dir}/${label}-selection.json"
	local -a selected_files=()

	sudo -u atf -H python3 "${tests_dir}/nebius/ci/atf/shard_tests.py" \
		--test-root "${tests_dir}/testsuite/python" \
		--phase "${phase}" \
		--shard-id "${shard_id}" \
		--shard-index "${shard_index}" \
		--shard-total "${shard_total}" \
		--vm-profile "${vm_profile}" \
		--output "${selection_file}"
	mapfile -t selected_files < <(jq -er '.selected_files[]' "${selection_file}")
	((${#selected_files[@]} > 0))

	date -u --iso-8601=seconds |
		sudo -u atf tee "${run_dir}/${label}-started-utc" >/dev/null
	set +e
	sudo -u atf -H env \
		SLURM_SUT_SOURCE_DIR="${source_dir}" \
		SLURM_SUT_BUILD_DIR="${build_dir}" \
		SLURM_SUT_INSTALL_DIR="${install_dir}" \
		SLURM_TESTS_SOURCE_DIR="${tests_dir}" \
		SLURM_RELEASE_MANIFEST="${manifest}" \
		SLURM_ATF_RUN_ID="${run_id}" \
		"${atf_root}/run-env.sh" \
		"${tests_dir}/testsuite/python/run-tests-python" \
		--auto-config \
		-vv \
		-s \
		-ra \
		--tb=long \
		--durations=200 \
		--junitxml="${junit_file}" \
		"${selected_files[@]}" 2>&1 |
		sudo -u atf tee "${log_file}"
	phase_status=${PIPESTATUS[0]}
	set -e
	printf '%s\n' "${phase_status}" |
		sudo -u atf tee "${status_file}" >/dev/null
	date -u --iso-8601=seconds |
		sudo -u atf tee "${run_dir}/${label}-finished-utc" >/dev/null
	capture_phase_evidence "${label}"
}

sync_output() {
	mkdir -p "${output_dir}"
	sudo rsync -a --delete "${run_dir}/" "${output_dir}/"
	sudo chown -R "$(id -u):$(id -g)" "${output_dir}"
}

case "${phase}" in
expect)
	prepare_build
	sudo -u atf -H mkdir -p "${run_dir}"
	write_manifest
	capture_inventory
	run_pytest_group expect expect
	sync_output
	if [[ "${phase_status}" != 0 && "${phase_status}" != 1 ]]; then
		echo "Expect wrappers did not complete normally (exit status ${phase_status})" >&2
		exit "${phase_status}"
	fi
	echo "Expect phase completed; raw pytest status: ${phase_status}."
	;;
pytest)
	test -x "${install_dir}/bin/sinfo"
	test -d "${build_dir}"
	test -s "${manifest}"
	test -s "${run_dir}/expect-junit.xml"
	expect_status="$(<"${run_dir}/expect-exit-status")"
	[[ "${expect_status}" == 0 || "${expect_status}" == 1 ]]
	configure_atf
	ensure_lmod_command
	run_pytest_group python python
	# Make the second phase diagnosable even if validation or JUnit merging
	# below fails. A successful merge is synced once more with final metadata.
	sync_output
	if [[ "${phase_status}" != 0 && "${phase_status}" != 1 ]]; then
		echo "Python tests did not complete normally (exit status ${phase_status})" >&2
		exit "${phase_status}"
	fi
	test -s "${run_dir}/python-junit.xml"
	sudo -u atf -H python3 "${tests_dir}/nebius/ci/atf/merge_junit.py" \
		"${run_dir}/expect-junit.xml" \
		"${run_dir}/python-junit.xml" \
		"${run_dir}/junit.xml"
	aggregate_status=0
	if [[ "${expect_status}" == 1 || "${phase_status}" == 1 ]]; then
		aggregate_status=1
	fi
	printf '%s\n' "${aggregate_status}" |
		sudo -u atf tee "${run_dir}/pytest-exit-status" >/dev/null
	{
		echo "===== EXPECT WRAPPERS ====="
		sudo cat "${run_dir}/expect.out"
		echo
		echo "===== PYTHON TESTS ====="
		sudo cat "${run_dir}/python.out"
	} | sudo -u atf tee "${run_dir}/pytest.out" >/dev/null
	sync_output
	echo "Full ATF result created; aggregate pytest status: ${aggregate_status}."
	echo "The raw phase statuses are recorded; comparison against the baseline is the gate."
	;;
esac
