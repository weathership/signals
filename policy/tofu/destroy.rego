# Destroy operation guardrails
# Validates Terraform destroy plans to prevent accidental cross-developer deletion.

package signals.tofu.destroy

import rego.v1

import data.signals.tofu.base

# --- Deny rules ---

# Only allow destroying resources owned by current developer
deny contains msg if {
	base.developer_prefix != ""
	some rc in base.deleted_resources
	rc.change.before.tags != null
	rc.change.before.tags.Owner != null
	rc.change.before.tags.Owner != base.developer_email
	msg := sprintf("Cannot destroy resource %s owned by %s (you are %s)", [
		rc.address,
		rc.change.before.tags.Owner,
		base.developer_email,
	])
}

# Warn about all resources being destroyed
warn contains msg if {
	some rc in base.deleted_resources
	msg := sprintf("Destroying: %s (%s)", [rc.address, rc.type])
}

# Extra warning for S3 buckets
warn contains msg if {
	some rc in base.deleted_resources
	rc.type == "aws_s3_bucket"
	msg := sprintf("WARNING: Destroying S3 bucket %s - data will be lost!", [
		rc.change.before.bucket,
	])
}
