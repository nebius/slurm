packer {
  required_version = "= 1.16.0"

  required_plugins {
    nebius = {
      source  = "github.com/nebius/nebius"
      version = "= 0.0.4"
    }
  }
}

variable "nebius_token" {
  type      = string
  sensitive = true
}

variable "parent_id" {
  type        = string
  description = "Nebius project that owns the builder VM, disk, and resulting image."
}

variable "subnet_id" {
  type        = string
  description = "Subnet used by the temporary H200 image-builder VM."
}

variable "base_image_id" {
  type    = string
  default = "computeimage-e00dyqcvp4vzdvkg3b"
}

variable "image_name" {
  type    = string
  default = "slurm-atf-ubuntu2404-cuda130-h200-v1"
}

variable "image_version" {
  type    = string
  default = "h200-v1-20260806"
}

source "nebius-image" "slurm_atf_h200" {
  communicator = "ssh"
  ssh_username = "ubuntu"
  token        = var.nebius_token

  parent_id = var.parent_id

  disk {
    size_gibibytes = 100
  }

  base_image {
    id = var.base_image_id
  }

  network {
    subnet_id                   = var.subnet_id
    associate_public_ip_address = true
  }

  instance {
    platform = "gpu-h200-sxm"
    preset   = "8gpu-128vcpu-1600gb"
  }

  image {
    name                        = var.image_name
    version                     = var.image_version
    image_family                = "slurm-atf-ubuntu2404-cuda130-h200-amd64"
    image_family_human_readable = "Slurm ATF Ubuntu 24.04 CUDA 13 H200"
    cpu_architecture            = "amd64"
    recommended_platforms       = ["gpu-h200-sxm"]
  }
}

build {
  sources = ["source.nebius-image.slurm_atf_h200"]

  provisioner "shell" {
    inline = ["mkdir -p /tmp/slurm-atf-infra/system"]
  }

  provisioner "file" {
    source      = "${path.root}/infra/"
    destination = "/tmp/slurm-atf-infra"
  }

  provisioner "shell" {
    script = "${path.root}/provision.sh"
    environment_vars = [
      "BUILD_JOBS=128",
      "SLURM_ATF_IMAGE_VERSION=${var.image_version}",
    ]
  }
}
