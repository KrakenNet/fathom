package authz.refusals

import rego.v1

allow if {
	not input.suspended
}

allow if {
	input.clearance >= 3
}

allow if {
	input.level <= 2
}

allow if {
	input.a == input.b
}

allow if {
	data.roles.admin == input.user
}

allow if {
	input.flag
}

score := 42

allow if {
	count(input.tags) > 2
}
