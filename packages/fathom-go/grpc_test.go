//go:build integration

// Live-server gRPC integration test (T-3.18, design C1 / AC-1.4).
//
// Spawns the Python gRPC server as a subprocess on an OS-assigned port with
// FATHOM_GRPC_ALLOW_INSECURE=1 and dials it via the generated Go stubs.
//
// RPC chosen: Reload. The Python servicer's Evaluate/AssertFact/Query/Retract
// methods still return plain dicts pending the gRPC wiring covered by a later
// task (T-2.10 executor note); only Reload returns a real ReloadResponse pb2
// today, so calling Reload is what actually exercises a Python → Go SDK round
// trip over real gRPC. The integration invariant (proto codegen + cross-language
// stub compatibility + server boot + authenticated call) is identical either
// way; the spec's mention of Evaluate is documented in .progress.md as the
// adaptation reason.
//
// Run with:
//
//	cd packages/fathom-go && go test -tags integration ./...
//
// Requires `uv` on PATH with the fathom project's dev env already materialised
// (the subprocess invokes `uv run python -c '<server-bootstrap>'`).
package fathom

import (
	"context"
	"bytes"
	"fmt"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"testing"
	"time"

	pb "github.com/KrakenNet/fathom-go/proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
)

// pythonBootstrap starts a FathomServicer with require_signature=False on an
// OS-assigned port, pre-loading a minimal template + module pack so that
// Reload can recompile templates/modules against a fresh env. The servicer
// accepts bearer token "test-token" (via FATHOM_API_TOKEN env).
//
// Prints a single "LISTEN:<port>" line to stdout once the server is ready,
// then blocks until the parent closes stdin or sends SIGTERM.
const pythonBootstrap = `
import os, sys, tempfile, pathlib, threading
from concurrent import futures
import grpc
from fathom.engine import Engine
from fathom.attestation import AttestationService
from fathom.integrations.grpc_server import FathomServicer
from fathom.proto import fathom_pb2_grpc

d = pathlib.Path(tempfile.mkdtemp())
(d/'templates.yaml').write_text('templates:\n  - name: agent\n    slots:\n      - name: id\n        type: symbol\n')
(d/'modules.yaml').write_text('modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n')

eng = Engine()
eng.load_templates(str(d/'templates.yaml'))
eng.load_modules(str(d/'modules.yaml'))
att = AttestationService.generate_keypair()
svc = FathomServicer(default_engine=eng, attestation=att, require_signature=False)

srv = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
fathom_pb2_grpc.add_FathomServiceServicer_to_server(svc, srv)
port = srv.add_insecure_port('[::]:0')
srv.start()
sys.stdout.write(f'LISTEN:{port}\n')
sys.stdout.flush()

# Block forever; parent reaps on SIGTERM or stdin close.
try:
    sys.stdin.read()
finally:
    srv.stop(0)
`

// minimalRulesetYAML is a self-contained ruleset payload the Python
// reload_rules() can parse and compile against the pre-loaded 'gov' module.
// Mirrors tests/test_engine_reload.py::_ruleset_yaml.
const minimalRulesetYAML = `ruleset: rs-reload-a
module: gov
rules:
  - name: rule_a
    when:
      - template: agent
        conditions:
          - slot: id
            expression: equals(alice)
    then:
      action: allow
      reason: rule_a ok
`

// waitForListen reads the child's stdout line-by-line until it sees
// "LISTEN:<port>" or hits the deadline. Returns the port or errors with any
// captured stderr for debugging.
func waitForListen(stdout *bytes.Buffer, stderr *bytes.Buffer, deadline time.Time) (int, error) {
	for time.Now().Before(deadline) {
		s := stdout.String()
		if idx := strings.Index(s, "LISTEN:"); idx >= 0 {
			rest := s[idx+len("LISTEN:"):]
			nl := strings.IndexByte(rest, '\n')
			if nl < 0 {
				time.Sleep(25 * time.Millisecond)
				continue
			}
			port, err := strconv.Atoi(strings.TrimSpace(rest[:nl]))
			if err != nil {
				return 0, fmt.Errorf("parse LISTEN port: %w; stderr=%s", err, stderr.String())
			}
			return port, nil
		}
		time.Sleep(25 * time.Millisecond)
	}
	return 0, fmt.Errorf("server never announced LISTEN; stderr=%s", stderr.String())
}

// dialReady polls the TCP port until the gRPC server accepts a connection.
// gRPC's Dial is non-blocking by default; doing a raw TCP probe first avoids
// racing with the server's listen() call.
func dialReady(port int, deadline time.Time) error {
	addr := fmt.Sprintf("localhost:%d", port)
	for time.Now().Before(deadline) {
		c, err := net.DialTimeout("tcp", addr, 200*time.Millisecond)
		if err == nil {
			_ = c.Close()
			return nil
		}
		time.Sleep(50 * time.Millisecond)
	}
	return fmt.Errorf("TCP port %d never became ready", port)
}

func TestLiveReloadRoundTrip(t *testing.T) {
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv not on PATH; skipping live Python server integration test")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "uv", "run", "python", "-c", pythonBootstrap)
	// Run from repo root so `uv run` finds the fathom project.
	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	// packages/fathom-go → ../../  is repo root.
	cmd.Dir = wd + "/../.."
	cmd.Env = append(os.Environ(),
		"FATHOM_GRPC_ALLOW_INSECURE=1",
		"FATHOM_API_TOKEN=test-token",
	)

	var outBuf, errBuf bytes.Buffer
	cmd.Stdout = &outBuf
	cmd.Stderr = &errBuf

	stdin, err := cmd.StdinPipe()
	if err != nil {
		t.Fatalf("stdin pipe: %v", err)
	}

	if err := cmd.Start(); err != nil {
		t.Fatalf("start python server: %v", err)
	}
	t.Cleanup(func() {
		_ = stdin.Close()
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		if t.Failed() {
			t.Logf("python server stderr:\n%s", errBuf.String())
			t.Logf("python server stdout:\n%s", outBuf.String())
		}
	})

	deadline := time.Now().Add(20 * time.Second)
	port, err := waitForListen(&outBuf, &errBuf, deadline)
	if err != nil {
		t.Fatalf("wait for LISTEN: %v", err)
	}
	if err := dialReady(port, deadline); err != nil {
		t.Fatalf("dial ready: %v", err)
	}

	conn, err := grpc.NewClient(
		fmt.Sprintf("localhost:%d", port),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		t.Fatalf("grpc.NewClient: %v", err)
	}
	defer func() { _ = conn.Close() }()

	client := pb.NewFathomServiceClient(conn)

	callCtx, callCancel := context.WithTimeout(ctx, 10*time.Second)
	defer callCancel()
	callCtx = metadata.AppendToOutgoingContext(callCtx, "authorization", "Bearer test-token")

	req := &pb.ReloadRequest{
		Source: &pb.ReloadRequest_RulesetYaml{RulesetYaml: minimalRulesetYAML},
	}
	resp, err := client.Reload(callCtx, req)
	if err != nil {
		t.Fatalf("Reload RPC failed: %v", err)
	}
	if resp == nil {
		t.Fatal("Reload returned nil response")
	}
	if resp.GetRulesetHashAfter() == "" {
		t.Fatalf("ruleset_hash_after was empty; resp=%+v", resp)
	}
	if !strings.HasPrefix(resp.GetRulesetHashAfter(), "sha256:") {
		t.Errorf("expected sha256: prefix on ruleset_hash_after, got %q", resp.GetRulesetHashAfter())
	}
	if resp.GetRulesetHashBefore() == resp.GetRulesetHashAfter() {
		t.Errorf("hash_before == hash_after; expected swap (before=%q after=%q)",
			resp.GetRulesetHashBefore(), resp.GetRulesetHashAfter())
	}
	if resp.GetAttestationToken() == "" {
		t.Error("attestation_token was empty; expected signed event")
	}
}
