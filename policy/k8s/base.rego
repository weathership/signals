# Base Kubernetes environment policy
# Validates that required tools and configuration are present.

package signals.k8s.base

import rego.v1

# --- Deny rules ---

# kubectl must be available
deny contains msg if {
	not input.tools.kubectl
	msg := "kubectl not found in PATH"
}

# helm must be available
deny contains msg if {
	not input.tools.helm
	msg := "helm not found in PATH"
}

# kubeconfig must exist
deny contains msg if {
	not input.kubeconfig.exists
	msg := sprintf("KUBECONFIG not found at %s", [input.kubeconfig.path])
}

# Cluster must be reachable
deny contains msg if {
	input.kubeconfig.exists
	not input.cluster.reachable
	msg := "Kubernetes cluster is not reachable"
}

# --- Info rules ---

info contains msg if {
	input.cluster.reachable
	msg := sprintf("Connected to cluster: %s (%s nodes)", [
		input.cluster.context,
		input.cluster.node_count,
	])
}
