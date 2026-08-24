# A realistic policy: mostly inside the convertible subset, with one rule
# that is not. The converter has to keep the first and report the second.
package authz.mixed

import rego.v1

allow if {
	input.tenant == "acme"
}

allow if {
	input.role == "auditor"
	input.method == "GET"
}

deny if {
	not input.authenticated
}
