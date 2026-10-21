# An `allow` that converts, and two `deny` bodies that do not. Dropping a
# deny takes a whole deny condition out of the policy, so the converter must
# refuse the policy rather than write one that allows what OPA denies.
package authz.dropped_deny

import rego.v1

default allow := false

allow if {
	input.user.role == "admin"
}

deny if {
	input.user.mfa_age >= 300
}

deny if {
	not input.user.mfa
}
