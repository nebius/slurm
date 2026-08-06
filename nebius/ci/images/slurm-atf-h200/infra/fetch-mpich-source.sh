#!/usr/bin/env bash
set -euo pipefail

root=/opt/slurm-atf
mpich_version=5.0.1
mpich_source="${root}/src/mpich-${mpich_version}"
mpich_archive="${root}/src/mpich-${mpich_version}.tar.gz"
mpich_sha256=8c1832a13ddacf071685069f5fadfd1f2877a29e1a628652892c65211b1f3327

if [[ ! -x "${mpich_source}/configure" ]]; then
	curl --fail --location --retry 5 --retry-all-errors \
		"https://www.mpich.org/static/downloads/${mpich_version}/mpich-${mpich_version}.tar.gz" \
		-o "${mpich_archive}"
	echo "${mpich_sha256}  ${mpich_archive}" | sha256sum -c -
	tar -xzf "${mpich_archive}" -C "${root}/src"
fi

echo "Verified MPICH ${mpich_version} source is available at ${mpich_source}."
