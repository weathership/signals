# OpenTofu (AWS)

AWS infrastructure is provisioned with OpenTofu (open-source Terraform fork) in `infra/aws/tofu/`.

## Resources

| File | Resources |
|------|-----------|
| `vpc.tf` | VPC, public/private subnets, IGW, conditional NAT, S3 VPC endpoint |
| `security.tf` | Bastion SG (SSH from WARP CGNAT), RKE2 cluster SG |
| `ec2.tf` | Ubuntu 24.04 AMI, SSH key pair, bastion, control plane, workers |
| `s3.tf` | Encrypted data bucket with public access blocked |
| `outputs.tf` | Bastion IP, node IPs, SSH key path, S3 bucket name |

## Network Architecture

```
Internet
    │
    ▼
┌─── Internet Gateway ───┐
│   Public Subnet         │
│   ┌─────────────────┐   │
│   │ Bastion (t3.sm) │   │
│   └────────┬────────┘   │
│            │ SSH proxy   │
├────────────┼────────────┤
│   Private Subnet         │
│   ┌──────────────────┐   │
│   │ Control Plane    │   │
│   │ (m6i.xlarge)     │   │
│   ├──────────────────┤   │
│   │ Workers ×4       │   │
│   │ (r6i.xlarge)     │   │
│   │ + data volumes   │   │
│   └──────────────────┘   │
└──────────────────────────┘
        │
        ▼ (VPC Endpoint)
      [ S3 ]
```

## Air-Gap Mode

Setting `airgap_mode = true` in `terraform.tfvars`:

- Removes the NAT gateway (no outbound internet from private subnet)
- S3 access preserved via VPC gateway endpoint
- All software must be pre-staged via Zarf packages

## Variables

Key variables in `variables.tf`:

| Variable | Default | Description |
|----------|---------|-------------|
| `project` | `signals-360` | Resource naming prefix |
| `aws_region` | `us-east-1` | AWS region |
| `control_plane_count` | `1` | Number of control plane nodes |
| `worker_count` | `4` | Number of worker nodes |
| `worker_instance_type` | `r6i.xlarge` | Worker EC2 instance type |
| `data_volume_size` | `100` | Worker data volume (GB) |
| `allowed_ssh_cidrs` | `100.96.0.0/12` | WARP CGNAT range for SSH |
| `airgap_mode` | `false` | Enable air-gap (no NAT) |

## Usage

```bash
cd infra/aws/tofu

# Initialize
tofu init

# Plan with policy check
tofu plan -out=plan.tfplan
conftest test plan.tfplan -p ../../policy/tofu/

# Apply
tofu apply plan.tfplan

# Outputs for Ansible inventory
tofu output -json
```
