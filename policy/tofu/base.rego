# Base policy helpers for OpenTofu/Terraform plan validation
# Provides common accessors and utility functions for evaluating Terraform plans
# with developer isolation support.

package signals.tofu.base

import rego.v1

# --- Input accessors ---

# All planned resource changes
resource_changes := input.resource_changes

# Resources being created
created_resources := [rc |
	some rc in resource_changes
	rc.change.actions[_] == "create"
]

# Resources being deleted
deleted_resources := [rc |
	some rc in resource_changes
	rc.change.actions[_] == "delete"
]

# Resources being updated
updated_resources := [rc |
	some rc in resource_changes
	rc.change.actions[_] == "update"
]

# --- Developer isolation helpers ---

# Current developer prefix from plan variables
developer_prefix := input.variables.developer_prefix.value

# Current developer email from plan variables
developer_email := input.variables.developer_email.value

# Project name from plan variables
project_name := input.variables.project.value

# Check if a resource has the correct Owner tag
has_owner_tag(resource) if {
	resource.change.after.tags.Owner == developer_email
}

# Check if resource name contains developer prefix
has_developer_prefix(resource) if {
	developer_prefix != ""
	contains(resource.change.after.tags.Name, developer_prefix)
}

# --- Region helpers ---

# Configured AWS region
aws_region := input.variables.aws_region.value

# Filter resources by type
resources_of_type(type) := [rc |
	some rc in resource_changes
	rc.type == type
]
