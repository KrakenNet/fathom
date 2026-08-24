package authz.numeric

import rego.v1

deny if {
	input.resource.level > 5
}

allow if {
	input.score < 0.5
}

allow if {
	3 < input.attempts
}
