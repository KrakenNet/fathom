package authz.basic

import rego.v1

default allow := false

allow if {
	input.user.role == "admin"
	input.action != "delete"
}

deny if {
	input.user.suspended == true
}
