#!/usr/bin/env bash
set -euo pipefail

infra_dir=/tmp/slurm-atf-infra
image_version="${SLURM_ATF_IMAGE_VERSION:?set SLURM_ATF_IMAGE_VERSION}"
build_jobs="${BUILD_JOBS:-128}"

source /etc/os-release
[[ "${ID}" == ubuntu && "${VERSION_ID}" == 24.04 ]]
[[ "$(dpkg --print-architecture)" == amd64 ]]
[[ "${build_jobs}" =~ ^[1-9][0-9]*$ ]]

command -v nvidia-smi >/dev/null
test -x /usr/local/cuda/bin/nvcc
test -f /usr/local/cuda/include/nvml.h
mapfile -t gpu_names < <(
	nvidia-smi --query-gpu=name --format=csv,noheader
)
((${#gpu_names[@]} == 8))
for gpu_name in "${gpu_names[@]}"; do
	[[ "${gpu_name}" == *H200* ]]
done

sudo bash "${infra_dir}/bootstrap-deps.sh"
sudo -u atf -H env BUILD_JOBS="${build_jobs}" \
	bash "${infra_dir}/build-mpi-image-stack.sh"
sudo -u atf -H bash "${infra_dir}/fetch-mpich-source.sh"
sudo /opt/slurm-atf/venv/bin/pip install \
	-r "${infra_dir}/requirements.lock"
sudo /opt/slurm-atf/venv/bin/pip check

# Catch driver/toolkit damage from package installation before publishing the
# immutable image rather than during a multi-hour baseline run.
nvidia-smi >/dev/null
/usr/local/cuda/bin/nvcc --version
test -f /usr/local/cuda/include/nvml.h

requirements_sha256="$(sha256sum "${infra_dir}/requirements.lock" | awk '{print $1}')"
metadata_tmp="$(mktemp)"
trap 'rm -f "${metadata_tmp}"' EXIT
jq -n \
	--arg image_version "${image_version}" \
	--arg requirements_sha256 "${requirements_sha256}" \
	--arg os_id "${ID}" \
	--arg os_version "${VERSION_ID}" \
	--arg architecture "$(dpkg --print-architecture)" \
	'{
      schema: 1,
      image_version: $image_version,
      os: {id: $os_id, version: $os_version, architecture: $architecture},
      python_requirements_sha256: $requirements_sha256,
      gpu: {
        profile: "h200",
        product: "NVIDIA H200",
        count: 8,
        cuda: "13.0"
      },
      stack: {
        pmix_tag: "v5.0.11",
        pmix_commit: "3795947f0fa625f406f1d085d1e70a8413b3febc",
        openmpi_tag: "v5.0.9",
        openmpi_commit: "b79100b3fbbf45b3c6ed82a6b67b6346f8cfdc41",
        mpich_version: "5.0.1",
        mpich_sha256: "8c1832a13ddacf071685069f5fadfd1f2877a29e1a628652892c65211b1f3327"
      }
    }' >"${metadata_tmp}"
sudo install -o root -g root -m 0644 \
	"${metadata_tmp}" /etc/slurm-atf-image.json

sudo systemctl stop influxdb mariadb munge || true
sudo find \
	/opt/slurm-atf/results \
	/opt/slurm-atf/sut \
	/opt/slurm-atf/tests \
	/run/slurm-atf \
	/var/lib/slurm-atf/slurmctld \
	/var/lib/slurm-atf/slurmd \
	/var/log/slurm-atf \
	-mindepth 1 -delete
sudo apt-get clean
sudo rm -rf /var/lib/apt/lists/* /tmp/slurm-atf-infra
sudo cloud-init clean --logs
sudo sync

echo "Slurm ATF H200 image ${image_version} is provisioned."
