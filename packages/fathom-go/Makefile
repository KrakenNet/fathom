# Fathom Go SDK — Code Generation
#
# Prerequisites:
#   - openapi-generator-cli (https://openapi-generator.tech)
#   - protoc + protoc-gen-go + protoc-gen-go-grpc (for gRPC stubs)
#
# Usage:
#   make generate          — regenerate REST client from OpenAPI spec
#   make generate-grpc     — regenerate gRPC stubs from proto definitions
#   make generate-all      — regenerate both REST and gRPC
#   make verify-grpc       — check committed stubs match proto (CI drift check)

# OPENAPI_SPEC must be generated first (e.g., from FastAPI's /openapi.json endpoint)
OPENAPI_SPEC ?= ../../openapi.json
PROTO_DIR    ?= ../../protos
OUT_DIR      ?= ./generated

.PHONY: generate generate-grpc generate-all verify-grpc clean

generate:
	@echo "Generating Go REST client from OpenAPI spec..."
	openapi-generator-cli generate \
		-i $(OPENAPI_SPEC) \
		-g go \
		-o $(OUT_DIR)/rest \
		--additional-properties=packageName=fathom,isGoSubmodule=true
	@echo "Done. Generated client in $(OUT_DIR)/rest"

generate-grpc:
	@echo "Generating Go gRPC stubs from proto definitions..."
	mkdir -p ./proto
	protoc \
		--proto_path=$(PROTO_DIR) \
		--go_out=./proto \
		--go_opt=paths=source_relative \
		--go-grpc_out=./proto \
		--go-grpc_opt=paths=source_relative \
		$(PROTO_DIR)/*.proto
	@echo "Done. Generated gRPC stubs in ./proto"

generate-all: generate generate-grpc

verify-grpc:
	@echo "Verifying committed gRPC stubs match proto definitions..."
	@TMPDIR=$$(mktemp -d) && \
		trap "rm -rf $$TMPDIR" EXIT && \
		protoc \
			--proto_path=$(PROTO_DIR) \
			--go_out=$$TMPDIR \
			--go_opt=paths=source_relative \
			--go-grpc_out=$$TMPDIR \
			--go-grpc_opt=paths=source_relative \
			$(PROTO_DIR)/*.proto && \
		diff -r $$TMPDIR ./proto && \
		echo "OK: committed stubs match regenerated output"

clean:
	rm -rf $(OUT_DIR)
