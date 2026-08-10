#!/usr/bin/env bash
set -euo pipefail

root=/opt/slurm-atf
jobs="${BUILD_JOBS:-$(nproc)}"
multiarch="$(dpkg-architecture -qDEB_HOST_MULTIARCH)"

pmix_source="${root}/src/openpmix"
pmix_build="${root}/build/pmix-5.0.11"
pmix_prefix="${root}/pmix/5.0.11"
pmix_commit=3795947f0fa625f406f1d085d1e70a8413b3febc

ompi_source="${root}/src/openmpi-5.0.9"
ompi_build="${root}/build/openmpi-5.0.9"
ompi_prefix="${root}/openmpi/5.0.9"
ompi_commit=b79100b3fbbf45b3c6ed82a6b67b6346f8cfdc41

if [[ ! -d "${pmix_source}/.git" ]]; then
	git clone --branch v5.0.11 --depth 1 \
		https://github.com/openpmix/openpmix.git "${pmix_source}"
fi
if [[ ! -d "${ompi_source}/.git" ]]; then
	git clone --branch v5.0.9 --depth 1 \
		https://github.com/open-mpi/ompi.git "${ompi_source}"
fi
if [[ "$(git -C "${pmix_source}" rev-parse HEAD)" != "${pmix_commit}" ]]; then
	echo "PMIx v5.0.11 did not resolve to pinned ${pmix_commit}" >&2
	exit 1
fi
if [[ "$(git -C "${ompi_source}" rev-parse HEAD)" != "${ompi_commit}" ]]; then
	echo "OpenMPI v5.0.9 did not resolve to pinned ${ompi_commit}" >&2
	exit 1
fi

# Release tags still reference build-system files through git submodules.
# A shallow parent clone does not initialize them, which makes autogen fail
# with errors such as "The submodule config/oac files are missing".  Update
# recursively after verifying the pinned parent commits so both fresh and
# resumed image builds get the exact submodule commits recorded upstream.
git -C "${pmix_source}" submodule sync --recursive
git -C "${pmix_source}" submodule update --init --recursive --depth 1
git -C "${ompi_source}" submodule sync --recursive
git -C "${ompi_source}" submodule update --init --recursive --depth 1

(
	cd "${pmix_source}"
	./autogen.pl
	mkdir -p "${pmix_build}"
	cd "${pmix_build}"
	"${pmix_source}/configure" \
		--prefix="${pmix_prefix}" \
		--with-hwloc=/usr \
		--with-hwloc-libdir="/usr/lib/${multiarch}" \
		--with-libevent=/usr \
		--with-libevent-libdir="/usr/lib/${multiarch}"
	make -j"${jobs}"
	make install
)

(
	cd "${ompi_source}"
	./autogen.pl
	mkdir -p "${ompi_build}"
	cd "${ompi_build}"
	PKG_CONFIG_PATH="${pmix_prefix}/lib/pkgconfig" \
	"${ompi_source}/configure" \
		--prefix="${ompi_prefix}" \
		--with-pmix="${pmix_prefix}" \
		--with-pmix-libdir="${pmix_prefix}/lib" \
		--with-libevent=/usr \
		--with-libevent-libdir="/usr/lib/${multiarch}" \
		--with-hwloc=/usr \
		--with-hwloc-libdir="/usr/lib/${multiarch}" \
		--disable-mpi-fortran \
		CFLAGS="-O2 -g3 -fno-omit-frame-pointer"
	make -j"${jobs}"
	make install
)

echo "Image-resident PMIx 5.0.11 and OpenMPI 5.0.9 are installed."
