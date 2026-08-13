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

validate_testsuite_makefiles() {
	local generated makefile_am missing=0 relative

	while IFS= read -r -d '' makefile_am; do
		relative="${makefile_am#"${source_dir}/"}"
		generated="${relative%.am}"
		if [[ ! -f "${build_root}/${generated}" ]]; then
			echo "configure did not generate ${generated} for ${relative}" >&2
			missing=1
		fi
	done < <(
		find "${source_dir}/testsuite" -type f -name Makefile.am -print0 |
			sort -z
	)

	if ((missing)); then
		echo "Testsuite Autotools inputs are incomplete; update configure.ac and configure." >&2
		return 1
	fi
}

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
validate_testsuite_makefiles
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
