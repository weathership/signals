# Policy (OPA)

Open Policy Agent (OPA) with Conftest provides guardrails for infrastructure provisioning and Kubernetes operations. Policies are written in Rego and live in `policy/`.

## Policy Structure

```
policy/
├── tofu/
│   ├── base.rego          # Common helpers
│   ├── provision.rego     # Create guardrails
│   └── destroy.rego       # Delete guardrails
└── k8s/
    └── base.rego          # Tool + cluster validation
```

## OpenTofu Policies

### Provision guardrails (`provision.rego`)

**Deny rules** (block apply):
- All resources must have an `Owner` tag matching the developer's email
- All named resources must include the developer prefix (when set)

**Warning rules** (advisory):
- Alerts on EC2 instance, VPC, S3 bucket, and security group creation

### Destroy guardrails (`destroy.rego`)

**Deny rules** (block destroy):
- Cannot destroy resources owned by a different developer (cross-developer isolation)

**Warning rules** (advisory):
- Lists all resources being destroyed
- Extra warning for S3 bucket deletion (data loss)

### Common helpers (`base.rego`)

Utility functions shared across policies:
- Resource change filtering (created, deleted, updated)
- Developer isolation helpers (Owner tag, prefix validation)
- Resource type filtering

## Kubernetes Policies

### Base validation (`k8s/base.rego`)

**Deny rules**:
- `kubectl` must be available in PATH
- `helm` must be available in PATH
- KUBECONFIG must exist
- Cluster must be reachable

**Info rules**:
- Reports connected cluster context and node count

## Usage

### Validate OpenTofu plans

```bash
cd infra/aws/tofu

# Generate plan
tofu plan -out=plan.tfplan
tofu show -json plan.tfplan > plan.json

# Validate against provision policies
conftest test plan.json -p ../../../policy/tofu/ --namespace signals.tofu.provision

# Validate destroy plans
conftest test plan.json -p ../../../policy/tofu/ --namespace signals.tofu.destroy
```

### Validate Kubernetes environment

```bash
# Generate environment snapshot
kubectl cluster-info dump --output-directory=/tmp/k8s-info
conftest test /tmp/k8s-info -p policy/k8s/
```

## Developer Isolation

The policy system enforces developer isolation in shared AWS accounts:

1. Set `developer_email` and `developer_prefix` in `terraform.tfvars`
2. All resources are tagged with `Owner = <developer_email>`
3. Provision policies enforce naming conventions
4. Destroy policies prevent cross-developer resource deletion
