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

# OPENAPI_SPEC must be generated first (e.g., from FastAPI's /openapi.json endpoint)
OPENAPI_SPEC ?= ../../openapi.json
PROTO_DIR    ?= ../../protos
OUT_DIR      ?= ./generated

.PHONY: generate generate-grpc generate-all clean

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

clean:
	rm -rf $(OUT_DIR)
