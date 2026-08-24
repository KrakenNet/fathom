package authz.strings

import rego.v1

allow if {
	input.action in {"read", "list"}
	startswith(input.path, "/public")
}

deny if {
	endswith(input.path, ".key")
}

deny if {
	contains(input.query, "DROP TABLE")
}

deny if {
	re_match("^tmp-[0-9]+$", input.bucket)
}
