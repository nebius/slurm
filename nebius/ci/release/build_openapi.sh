#!/usr/bin/env bash
set -euo pipefail

if (($# != 8)); then
	echo "usage: $0 SOURCE_DIR BUILD_DIR INSTALL_DIR ASSET_DIR ASSET_PREFIX EXPECTED_VERSION API_PREVIOUS API_CURRENT" >&2
	exit 2
fi

source_dir="$(cd "$1" && pwd)"
build_root="$2"
install_root="$3"
asset_dir="$4"
asset_prefix="$5"
expected_version="$6"
api_previous="$7"
api_current="$8"

[[ "${api_previous}" =~ ^[0-9]+$ ]]
[[ "${api_current}" =~ ^[0-9]+$ ]]
((api_previous + 1 == api_current))
[[ "${asset_prefix}" =~ ^slurm-[0-9]+\.[0-9]+\.[0-9]+-nebius-[1-9][0-9]*$ ]]
[[ "${expected_version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+-nebius-[1-9][0-9]*$ ]]

topology_dir="${source_dir}/testsuite/slurm_unit/topology"
topology_makefile="${topology_dir}/Makefile.in"
temporary_topology=false

cleanup() {
	if [[ "${temporary_topology}" == true ]]; then
		rm -f "${topology_makefile}"
		rmdir "${topology_dir}" 2>/dev/null || true
	fi
}
trap cleanup EXIT

# NB-0001 synchronizes the master testsuite while preserving the release
# configure script. Slurm 26.05 therefore still asks for this removed input.
if grep -Fq 'testsuite/slurm_unit/topology/Makefile' \
	"${source_dir}/configure" && [[ ! -e "${topology_makefile}" ]]; then
	if grep -Eq '(^|[[:space:]])topology([[:space:]]|$)' \
		"${source_dir}/testsuite/slurm_unit/Makefile.am"; then
		echo "Refusing to mask an active topology build input" >&2
		exit 1
	fi
	mkdir -p "${topology_dir}"
	printf '%s\n' '# Temporary release configure compatibility input.' \
		>"${topology_makefile}"
	temporary_topology=true
fi

mkdir -p "${build_root}" "${install_root}" "${asset_dir}"
cd "${build_root}"
"${source_dir}/configure" \
	--prefix="${install_root}" \
	--sysconfdir="${install_root}/etc" \
	--with-json=/usr \
	--with-jwt=/usr \
	--with-libhttp-parser=/usr \
	--with-munge=/usr \
	--with-yaml=/usr \
	CFLAGS='-O2 -g'
make --no-print-directory -s -C src -j"$(nproc)"
make --no-print-directory -s -C src install

actual_version="$("${install_root}/sbin/slurmrestd" -V)"
test "${actual_version}" = "slurm ${expected_version}"

export LD_LIBRARY_PATH="${install_root}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
for api in "${api_previous}" "${api_current}"; do
	parser="v0.0.${api}"
	test -d "${source_dir}/src/plugins/data_parser/${parser}"
	output="${asset_dir}/${asset_prefix}-openapi-${parser}.json"
	temporary="${output}.tmp"
	"${install_root}/sbin/slurmrestd" \
		-f /dev/null \
		-s openapi/slurmctld,openapi/slurmdbd \
		-d "data_parser/${parser}" \
		--generate-openapi-spec >"${temporary}"
	jq -S . "${temporary}" >"${output}"
	rm -f "${temporary}"
	jq -e '.openapi | startswith("3.")' "${output}" >/dev/null
	jq -e \
		--arg prefix "/slurm/${parser}/" \
		'[.paths | keys[] | select(startswith($prefix))] | length > 0' \
		"${output}" >/dev/null
	jq -e \
		--arg prefix "/slurmdb/${parser}/" \
		'[.paths | keys[] | select(startswith($prefix))] | length > 0' \
		"${output}" >/dev/null
done
