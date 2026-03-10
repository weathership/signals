# ── Project ───────────────────────────────────────────────────────────────────

variable "project" {
  description = "Project name for resource tagging"
  type        = string
  default     = "signals-360"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "developer_email" {
  description = "Developer email for resource tagging and Cloudflare access"
  type        = string
}

variable "developer_prefix" {
  description = "Short prefix for resource naming to avoid collisions"
  type        = string
  default     = ""
}

# ── AWS ──────────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.100.0.0/16"
}

# ── EC2 Instances ────────────────────────────────────────────────────────────

variable "control_plane_count" {
  description = "Number of RKE2 control plane nodes"
  type        = number
  default     = 1
}

variable "control_plane_instance_type" {
  description = "EC2 instance type for control plane"
  type        = string
  default     = "m6i.xlarge"
}

variable "worker_count" {
  description = "Number of RKE2 worker nodes"
  type        = number
  default     = 4
}

variable "worker_instance_type" {
  description = "EC2 instance type for workers"
  type        = string
  default     = "r6i.xlarge"
}

variable "root_volume_size" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 50
}

variable "data_volume_size" {
  description = "Data EBS volume size in GB"
  type        = number
  default     = 100
}

# ── RKE2 ─────────────────────────────────────────────────────────────────────

variable "rke2_version" {
  description = "RKE2 Kubernetes version"
  type        = string
  default     = "v1.34.3+rke2r1"
}

# ── Access ───────────────────────────────────────────────────────────────────

variable "allowed_ssh_cidrs" {
  description = "CIDR blocks allowed SSH access (e.g. WARP CGNAT)"
  type        = list(string)
  default     = ["100.96.0.0/12"]
}

variable "airgap_mode" {
  description = "Enable air-gap mode (no NAT gateway, no outbound internet)"
  type        = bool
  default     = false
}

# ── Cloudflare ───────────────────────────────────────────────────────────────

variable "cloudflare_zone_id" {
  description = "Cloudflare DNS zone ID"
  type        = string
  default     = ""
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID for Zero Trust"
  type        = string
  default     = ""
}
