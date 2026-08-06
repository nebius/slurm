#!/usr/bin/env bash
set -euo pipefail

if (($# != 10)); then
	echo "usage: $0 SOURCE_DIR TESTS_DIR INFRA_DIR BUILD_DIR OUTPUT_DIR RUN_ID RELEASE_LINE SOURCE_COMMIT TESTS_COMMIT ATF_PROFILE" >&2
	exit 2
fi

source_dir="$(realpath "$1")"
tests_dir="$(realpath "$2")"
infra_dir="$(realpath "$3")"
build_dir="$(realpath -m "$4")"
output_dir="$(realpath -m "$5")"
run_id="$6"
release_line="$7"
source_commit="$8"
tests_commit="$9"
atf_profile="${10}"

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
jobs="${BUILD_JOBS:-$(nproc)}"

[[ "${run_id}" =~ ^[a-zA-Z0-9._-]+$ ]]
[[ "${release_line}" =~ ^[0-9]+\.[0-9]+$ ]]
[[ "${source_commit}" =~ ^[0-9a-f]{40}$ ]]
[[ "${tests_commit}" =~ ^[0-9a-f]{40}$ ]]
[[ "${atf_profile}" == generic || "${atf_profile}" == b200 || \
	"${atf_profile}" == h200 ]]
[[ "${jobs}" =~ ^[1-9][0-9]*$ ]]

sudo test -f /etc/slurm-atf-disposable
test -s /etc/slurm-atf-image.json
test -f "${source_dir}/META"
test -x "${source_dir}/configure"
test -d "${tests_dir}/testsuite/expect"
test -d "${tests_dir}/testsuite/src"
test -x "${tests_dir}/testsuite/run-tests"
test -x "${tests_dir}/testsuite/python/run-tests-python"
test -x "${pmix_prefix}/bin/pmix_info"
test -x "${openmpi_prefix}/bin/mpirun"
test -x "${mpich_source}/configure"
test -x "${infra_dir}/configure-atf.sh"
test -x "${infra_dir}/run-full-python.sh"
jq -e '
  .schema == 1 and
  .os.id == "ubuntu" and
  .os.version == "24.04" and
  .os.architecture == "amd64" and
  .stack.pmix_tag == "v5.0.11" and
  .stack.openmpi_tag == "v5.0.9" and
  .stack.mpich_version == "5.0.1"
' /etc/slurm-atf-image.json >/dev/null

if [[ "${atf_profile}" == h200 ]]; then
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
	CFLAGS="-O2 -g3 -fno-omit-frame-pointer"

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

# The test harness modifies its generated configuration and temporary files.
# It is a separate checkout from the product source, so granting it to the ATF
# user cannot alter the candidate that was built above.
sudo chown -R atf:atf "${tests_dir}"

sudo -u atf -H env \
	SLURM_SUT_SOURCE_DIR="${source_dir}" \
	SLURM_SUT_BUILD_DIR="${build_dir}" \
	SLURM_SUT_INSTALL_DIR="${install_dir}" \
	SLURM_TESTS_SOURCE_DIR="${tests_dir}" \
	SLURM_ATF_PROFILE="${atf_profile}" \
	"${infra_dir}/configure-atf.sh"

release_version="$(awk '$1 == "Version:" {print $2; exit}' "${source_dir}/META")"
manifest="${output_dir}/run-manifest.json"
jq -n \
	--arg release_line "${release_line}" \
	--arg release_version "${release_version}" \
	--arg source_commit "${source_commit}" \
	--arg tests_commit "${tests_commit}" \
	--arg atf_profile "${atf_profile}" \
	'{
	  schema: 1,
	  release: {
	    line: $release_line,
	    version: $release_version,
	    commit: $source_commit
	  },
	  tests: {master_commit: $tests_commit},
	  atf: {profile: $atf_profile}
	}' >"${manifest}"

set +e
sudo -u atf -H env \
	SLURM_SUT_SOURCE_DIR="${source_dir}" \
	SLURM_SUT_BUILD_DIR="${build_dir}" \
	SLURM_SUT_INSTALL_DIR="${install_dir}" \
	SLURM_TESTS_SOURCE_DIR="${tests_dir}" \
	SLURM_RELEASE_MANIFEST="${manifest}" \
	SLURM_ATF_RUN_ID="${run_id}" \
	"${atf_root}/run-env.sh" "${atf_root}/run-full-python.sh"
pytest_status=$?
set -e

run_dir="${atf_root}/results/${run_id}"
test -s "${run_dir}/junit.xml" || {
	echo "Full ATF run did not produce ${run_dir}/junit.xml" >&2
	exit 1
}
printf '%s\n' "${pytest_status}" | sudo -u atf tee \
	"${run_dir}/pytest-exit-status" >/dev/null
sudo install -o atf -g atf -m 0644 "${manifest}" \
	"${run_dir}/run-manifest.json"
sudo install -o atf -g atf -m 0644 /etc/slurm-atf-image.json \
	"${run_dir}/image-metadata.json"
sudo rsync -a "${run_dir}/" "${output_dir}/"
sudo chown -R "$(id -u):$(id -g)" "${output_dir}"

if [[ "${pytest_status}" != 0 && "${pytest_status}" != 1 ]]; then
	echo "Pytest did not complete normally (exit status ${pytest_status})" >&2
	exit "${pytest_status}"
fi

echo "Full ATF result created; raw pytest status: ${pytest_status}."
echo "The raw status is recorded but comparison against the baseline is the gate."
