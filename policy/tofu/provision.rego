# Provision operation guardrails
# Validates Terraform apply plans for Signals 360 infrastructure.

package signals.tofu.provision

import rego.v1

import data.signals.tofu.base

# --- Deny rules (block apply) ---

# All resources must have an Owner tag
deny contains msg if {
	some rc in base.created_resources
	rc.change.after.tags != null
	not base.has_owner_tag(rc)
	msg := sprintf("Resource %s missing Owner tag (expected: %s)", [rc.address, base.developer_email])
}

# All named resources must include developer prefix when set
deny contains msg if {
	base.developer_prefix != ""
	some rc in base.created_resources
	rc.change.after.tags.Name != null
	not base.has_developer_prefix(rc)
	msg := sprintf("Resource %s name missing developer prefix '%s'", [rc.address, base.developer_prefix])
}

# --- Warning rules (advisory) ---

warn contains msg if {
	ec2 := base.resources_of_type("aws_instance")
	count(ec2) > 0
	some rc in ec2
	rc.change.actions[_] == "create"
	msg := sprintf("Creating EC2 instance: %s (%s)", [
		rc.change.after.tags.Name,
		rc.change.after.instance_type,
	])
}

warn contains msg if {
	vpcs := base.resources_of_type("aws_vpc")
	count(vpcs) > 0
	some rc in vpcs
	rc.change.actions[_] == "create"
	msg := sprintf("Creating VPC: %s (%s)", [
		rc.change.after.tags.Name,
		rc.change.after.cidr_block,
	])
}

warn contains msg if {
	buckets := base.resources_of_type("aws_s3_bucket")
	count(buckets) > 0
	some rc in buckets
	rc.change.actions[_] == "create"
	msg := sprintf("Creating S3 bucket: %s", [rc.change.after.bucket])
}

warn contains msg if {
	sgs := base.resources_of_type("aws_security_group")
	count(sgs) > 0
	some rc in sgs
	rc.change.actions[_] == "create"
	msg := sprintf("Creating security group: %s", [rc.change.after.name_prefix])
}
