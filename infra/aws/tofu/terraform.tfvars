# Shared configuration — override in local.auto.tfvars for per-developer settings
environment             = "dev"
project                 = "signals-360"
vpc_cidr                = "10.100.0.0/16"
control_plane_count     = 1
worker_count            = 4
worker_instance_type    = "r6i.xlarge"
root_volume_size        = 50
data_volume_size        = 100
allowed_ssh_cidrs       = ["100.96.0.0/12"]
airgap_mode             = false
