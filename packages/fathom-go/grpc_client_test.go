package fathom

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"strings"
	"testing"
	"time"

	pb "github.com/KrakenNet/fathom-go/proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
)

// ---------- Mock server ----------

// mockServer is a programmable FathomServiceServer for in-process tests. Each
// handler delegates to a function field so individual tests can script
// responses, errors, and metadata assertions. The last-seen authorization
// metadata is captured for bearer-token tests.
type mockServer struct {
	pb.UnimplementedFathomServiceServer

	lastAuth string

	evaluate   func(context.Context, *pb.EvaluateRequest) (*pb.EvaluateResponse, error)
	assertFact func(context.Context, *pb.AssertFactRequest) (*pb.AssertFactResponse, error)
	query      func(context.Context, *pb.QueryRequest) (*pb.QueryResponse, error)
	retract    func(context.Context, *pb.RetractRequest) (*pb.RetractResponse, error)
	reload     func(context.Context, *pb.ReloadRequest) (*pb.ReloadResponse, error)
	subscribe  func(*pb.SubscribeRequest, grpc.ServerStreamingServer[pb.FactChange]) error
}

func (m *mockServer) captureAuth(ctx context.Context) {
	if md, ok := metadata.FromIncomingContext(ctx); ok {
		if vals := md.Get("authorization"); len(vals) > 0 {
			m.lastAuth = vals[0]
		}
	}
}

func (m *mockServer) Evaluate(ctx context.Context, req *pb.EvaluateRequest) (*pb.EvaluateResponse, error) {
	m.captureAuth(ctx)
	if m.evaluate != nil {
		return m.evaluate(ctx, req)
	}
	return &pb.EvaluateResponse{}, nil
}

func (m *mockServer) AssertFact(ctx context.Context, req *pb.AssertFactRequest) (*pb.AssertFactResponse, error) {
	m.captureAuth(ctx)
	if m.assertFact != nil {
		return m.assertFact(ctx, req)
	}
	return &pb.AssertFactResponse{}, nil
}

func (m *mockServer) Query(ctx context.Context, req *pb.QueryRequest) (*pb.QueryResponse, error) {
	m.captureAuth(ctx)
	if m.query != nil {
		return m.query(ctx, req)
	}
	return &pb.QueryResponse{}, nil
}

func (m *mockServer) Retract(ctx context.Context, req *pb.RetractRequest) (*pb.RetractResponse, error) {
	m.captureAuth(ctx)
	if m.retract != nil {
		return m.retract(ctx, req)
	}
	return &pb.RetractResponse{}, nil
}

func (m *mockServer) Reload(ctx context.Context, req *pb.ReloadRequest) (*pb.ReloadResponse, error) {
	m.captureAuth(ctx)
	if m.reload != nil {
		return m.reload(ctx, req)
	}
	return &pb.ReloadResponse{}, nil
}

func (m *mockServer) SubscribeChanges(req *pb.SubscribeRequest, stream grpc.ServerStreamingServer[pb.FactChange]) error {
	m.captureAuth(stream.Context())
	if m.subscribe != nil {
		return m.subscribe(req, stream)
	}
	return nil
}

// newMockGRPC stands up the mock on a bufconn listener and returns a connected
// GRPCClient. Extra GRPCOptions (e.g. WithGRPCBearerToken) are threaded through;
// the bufconn dialer + insecure transport are always supplied.
func newMockGRPC(t *testing.T, mock *mockServer, opts ...GRPCOption) *GRPCClient {
	t.Helper()
	lis := bufconn.Listen(1 << 20)
	srv := grpc.NewServer()
	pb.RegisterFathomServiceServer(srv, mock)
	go func() { _ = srv.Serve(lis) }()

	dialer := grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
		return lis.DialContext(ctx)
	})
	allOpts := append([]GRPCOption{
		WithGRPCInsecure(),
		WithDialOptions(dialer, grpc.WithTransportCredentials(insecure.NewCredentials())),
	}, opts...)

	// passthrough:/// bypasses DNS so grpc.NewClient hands "bufnet" straight to
	// the bufconn context dialer instead of trying to resolve it.
	c, err := NewGRPCClient("passthrough:///bufnet", allOpts...)
	if err != nil {
		t.Fatalf("NewGRPCClient: %v", err)
	}
	t.Cleanup(func() {
		_ = c.Close()
		srv.Stop()
		_ = lis.Close()
	})
	return c
}

// ---------- Constructor + options ----------

func TestNewGRPCClient_DefaultTLS(t *testing.T) {
	// No insecure opt: grpc.NewClient is lazy, so construction succeeds and
	// TLS creds are wired without a live dial.
	c, err := NewGRPCClient("localhost:50051")
	if err != nil {
		t.Fatalf("NewGRPCClient: %v", err)
	}
	defer c.Close()
	if c.stub == nil {
		t.Fatal("expected non-nil stub")
	}
}

func TestBearerPerRPC_RequiresSecurityByDefault(t *testing.T) {
	b := bearerPerRPC{token: "t", requireSecurity: true}
	if !b.RequireTransportSecurity() {
		t.Fatal("expected RequireTransportSecurity true when secure")
	}
	md, err := b.GetRequestMetadata(context.Background())
	if err != nil {
		t.Fatalf("GetRequestMetadata: %v", err)
	}
	if md["authorization"] != "Bearer t" {
		t.Fatalf("authorization metadata: got %q", md["authorization"])
	}
}

func TestBearerPerRPC_InsecureAllowed(t *testing.T) {
	b := bearerPerRPC{token: "t", requireSecurity: false}
	if b.RequireTransportSecurity() {
		t.Fatal("expected RequireTransportSecurity false when insecure opted in")
	}
}

// ---------- Bearer metadata attached ----------

func TestGRPC_BearerMetadataAttached(t *testing.T) {
	mock := &mockServer{}
	c := newMockGRPC(t, mock, WithGRPCBearerToken("super-secret"))

	_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if mock.lastAuth != "Bearer super-secret" {
		t.Fatalf("authorization metadata: got %q, want %q", mock.lastAuth, "Bearer super-secret")
	}
}

func TestGRPC_NoBearerWhenUnset(t *testing.T) {
	mock := &mockServer{}
	c := newMockGRPC(t, mock)

	_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if mock.lastAuth != "" {
		t.Fatalf("expected no authorization metadata, got %q", mock.lastAuth)
	}
}

// ---------- Evaluate ----------

func TestGRPC_Evaluate_HappyPath(t *testing.T) {
	mock := &mockServer{
		evaluate: func(_ context.Context, req *pb.EvaluateRequest) (*pb.EvaluateResponse, error) {
			// Assert fact data was JSON-encoded into data_json.
			if len(req.GetFacts()) != 1 {
				t.Errorf("facts: got %d, want 1", len(req.GetFacts()))
			} else {
				var data map[string]any
				if err := json.Unmarshal([]byte(req.GetFacts()[0].GetDataJson()), &data); err != nil {
					t.Errorf("data_json not valid json: %v", err)
				} else if data["role"] != "admin" {
					t.Errorf("data.role: got %v, want admin", data["role"])
				}
			}
			if req.GetRuleset() != "authz" {
				t.Errorf("ruleset: got %q, want authz", req.GetRuleset())
			}
			return &pb.EvaluateResponse{
				Decision:    "allow",
				Reason:      "ok",
				RuleTrace:   []string{"r1"},
				ModuleTrace: []string{"m1"},
				DurationUs:  42,
			}, nil
		},
	}
	c := newMockGRPC(t, mock)

	got, err := c.Evaluate(context.Background(), &EvaluateRequest{
		Facts:   []FactInput{{Template: "user", Data: map[string]any{"role": "admin"}}},
		Ruleset: "authz",
	})
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if got.Decision != "allow" || got.Reason != "ok" {
		t.Errorf("decision/reason: got %q/%q", got.Decision, got.Reason)
	}
	if len(got.RuleTrace) != 1 || len(got.ModuleTrace) != 1 || got.DurationUS != 42 {
		t.Errorf("traces/duration mismatch: %+v", got)
	}
}

func TestGRPC_Evaluate_StatusSurfaced(t *testing.T) {
	mock := &mockServer{
		evaluate: func(context.Context, *pb.EvaluateRequest) (*pb.EvaluateResponse, error) {
			return nil, status.Error(codes.Unauthenticated, "unauthorized")
		},
	}
	c := newMockGRPC(t, mock)

	_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
	if err == nil {
		t.Fatal("expected error")
	}
	if st, _ := status.FromError(errors.Unwrap(err)); st.Code() != codes.Unauthenticated {
		t.Errorf("code: got %v, want Unauthenticated", st.Code())
	}
	if !strings.Contains(err.Error(), "fathom: evaluate") {
		t.Errorf("error not wrapped: %v", err)
	}
}

// ---------- AssertFact ----------

func TestGRPC_AssertFact_HappyPath(t *testing.T) {
	mock := &mockServer{
		assertFact: func(_ context.Context, req *pb.AssertFactRequest) (*pb.AssertFactResponse, error) {
			if req.GetSessionId() != "s1" || req.GetTemplate() != "user" {
				t.Errorf("session/template mismatch: %+v", req)
			}
			var data map[string]any
			_ = json.Unmarshal([]byte(req.GetDataJson()), &data)
			if data["name"] != "bob" {
				t.Errorf("data.name: got %v", data["name"])
			}
			return &pb.AssertFactResponse{Success: true}, nil
		},
	}
	c := newMockGRPC(t, mock)

	got, err := c.AssertFact(context.Background(), &AssertFactRequest{
		SessionID: "s1", Template: "user", Data: map[string]any{"name": "bob"},
	})
	if err != nil {
		t.Fatalf("AssertFact: %v", err)
	}
	if !got.Success {
		t.Error("expected Success true")
	}
}

func TestGRPC_AssertFact_StatusSurfaced(t *testing.T) {
	mock := &mockServer{
		assertFact: func(context.Context, *pb.AssertFactRequest) (*pb.AssertFactResponse, error) {
			return nil, status.Error(codes.InvalidArgument, "bad fact")
		},
	}
	c := newMockGRPC(t, mock)

	_, err := c.AssertFact(context.Background(), &AssertFactRequest{})
	if err == nil || !strings.Contains(err.Error(), "fathom: assert fact") {
		t.Fatalf("expected wrapped assert-fact error, got %v", err)
	}
}

// ---------- Query ----------

func TestGRPC_Query_HappyPath(t *testing.T) {
	mock := &mockServer{
		query: func(_ context.Context, req *pb.QueryRequest) (*pb.QueryResponse, error) {
			// filter map round-trips into filter_json.
			var filter map[string]any
			_ = json.Unmarshal([]byte(req.GetFilterJson()), &filter)
			if filter["role"] != "admin" {
				t.Errorf("filter.role: got %v", filter["role"])
			}
			return &pb.QueryResponse{FactsJson: []string{
				`{"name":"alice","role":"admin"}`,
				`{"name":"bob","role":"admin"}`,
			}}, nil
		},
	}
	c := newMockGRPC(t, mock)

	got, err := c.Query(context.Background(), &QueryRequest{
		SessionID: "s1", Template: "user", Filter: map[string]any{"role": "admin"},
	})
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(got.Facts) != 2 {
		t.Fatalf("facts: got %d, want 2", len(got.Facts))
	}
	if got.Facts[0]["name"] != "alice" {
		t.Errorf("facts[0].name: got %v", got.Facts[0]["name"])
	}
}

func TestGRPC_Query_StatusSurfaced(t *testing.T) {
	mock := &mockServer{
		query: func(context.Context, *pb.QueryRequest) (*pb.QueryResponse, error) {
			return nil, status.Error(codes.Internal, "boom")
		},
	}
	c := newMockGRPC(t, mock)

	_, err := c.Query(context.Background(), &QueryRequest{})
	if err == nil || !strings.Contains(err.Error(), "fathom: query") {
		t.Fatalf("expected wrapped query error, got %v", err)
	}
}

// ---------- Retract ----------

func TestGRPC_Retract_HappyPath(t *testing.T) {
	mock := &mockServer{
		retract: func(_ context.Context, req *pb.RetractRequest) (*pb.RetractResponse, error) {
			if req.GetTemplate() != "user" {
				t.Errorf("template: got %q", req.GetTemplate())
			}
			return &pb.RetractResponse{RetractedCount: 3}, nil
		},
	}
	c := newMockGRPC(t, mock)

	got, err := c.Retract(context.Background(), &RetractRequest{
		SessionID: "s1", Template: "user", Filter: map[string]any{"role": "guest"},
	})
	if err != nil {
		t.Fatalf("Retract: %v", err)
	}
	if got.RetractedCount != 3 {
		t.Errorf("RetractedCount: got %d, want 3", got.RetractedCount)
	}
}

func TestGRPC_Retract_StatusSurfaced(t *testing.T) {
	mock := &mockServer{
		retract: func(context.Context, *pb.RetractRequest) (*pb.RetractResponse, error) {
			return nil, status.Error(codes.PermissionDenied, "nope")
		},
	}
	c := newMockGRPC(t, mock)

	_, err := c.Retract(context.Background(), &RetractRequest{})
	if err == nil || !strings.Contains(err.Error(), "fathom: retract") {
		t.Fatalf("expected wrapped retract error, got %v", err)
	}
}

// ---------- Reload ----------

func TestGRPC_Reload_HappyPath_YAML(t *testing.T) {
	mock := &mockServer{
		reload: func(_ context.Context, req *pb.ReloadRequest) (*pb.ReloadResponse, error) {
			if req.GetRulesetYaml() != "ruleset: rs" {
				t.Errorf("ruleset_yaml: got %q", req.GetRulesetYaml())
			}
			return &pb.ReloadResponse{
				RulesetHashBefore: "sha256:aaa",
				RulesetHashAfter:  "sha256:bbb",
				AttestationToken:  "att-1",
			}, nil
		},
	}
	c := newMockGRPC(t, mock)

	got, err := c.Reload(context.Background(), &ReloadRequest{RulesetYAML: "ruleset: rs"})
	if err != nil {
		t.Fatalf("Reload: %v", err)
	}
	if got.RulesetHashAfter != "sha256:bbb" || got.AttestationToken != "att-1" {
		t.Errorf("reload response mismatch: %+v", got)
	}
}

func TestGRPC_Reload_PathOneof(t *testing.T) {
	mock := &mockServer{
		reload: func(_ context.Context, req *pb.ReloadRequest) (*pb.ReloadResponse, error) {
			if req.GetRulesetPath() != "/rules/a.yaml" {
				t.Errorf("ruleset_path: got %q", req.GetRulesetPath())
			}
			return &pb.ReloadResponse{}, nil
		},
	}
	c := newMockGRPC(t, mock)

	_, err := c.Reload(context.Background(), &ReloadRequest{RulesetPath: "/rules/a.yaml"})
	if err != nil {
		t.Fatalf("Reload: %v", err)
	}
}

func TestGRPC_Reload_StatusSurfaced(t *testing.T) {
	mock := &mockServer{
		reload: func(context.Context, *pb.ReloadRequest) (*pb.ReloadResponse, error) {
			return nil, status.Error(codes.FailedPrecondition, "no root")
		},
	}
	c := newMockGRPC(t, mock)

	_, err := c.Reload(context.Background(), &ReloadRequest{})
	if err == nil || !strings.Contains(err.Error(), "fathom: reload") {
		t.Fatalf("expected wrapped reload error, got %v", err)
	}
}

// ---------- SubscribeChanges ----------

func TestGRPC_Subscribe_YieldsEventsThenReloadSentinel(t *testing.T) {
	mock := &mockServer{
		subscribe: func(req *pb.SubscribeRequest, stream grpc.ServerStreamingServer[pb.FactChange]) error {
			if req.GetSessionId() != "sess-1" {
				t.Errorf("session_id: got %q", req.GetSessionId())
			}
			_ = stream.Send(&pb.FactChange{
				ChangeType: pb.ChangeType_ASSERT,
				Template:   "user",
				DataJson:   `{"name":"alice"}`,
			})
			_ = stream.Send(&pb.FactChange{
				ChangeType: pb.ChangeType_RETRACT,
				Template:   "user",
				DataJson:   `{"name":"bob"}`,
			})
			// Reload abort: code Aborted + ruleset_reloaded in message.
			return status.Error(codes.Aborted,
				"ruleset_reloaded: re-subscribe to bind to the new ruleset")
		},
	}
	c := newMockGRPC(t, mock)

	var events []FactChangeEvent
	err := c.SubscribeChanges(context.Background(), "sess-1", func(e FactChangeEvent) error {
		events = append(events, e)
		return nil
	})

	if !errors.Is(err, ErrRulesetReloaded) {
		t.Fatalf("expected ErrRulesetReloaded, got %v", err)
	}
	if len(events) != 2 {
		t.Fatalf("events: got %d, want 2", len(events))
	}
	if events[0].ChangeType != ChangeTypeAssert || events[0].Template != "user" || events[0].Data["name"] != "alice" {
		t.Errorf("event[0] mismatch: %+v", events[0])
	}
	if events[1].ChangeType != ChangeTypeRetract || events[1].Data["name"] != "bob" {
		t.Errorf("event[1] mismatch: %+v", events[1])
	}
}

func TestGRPC_Subscribe_CleanEOF(t *testing.T) {
	mock := &mockServer{
		subscribe: func(_ *pb.SubscribeRequest, stream grpc.ServerStreamingServer[pb.FactChange]) error {
			_ = stream.Send(&pb.FactChange{ChangeType: pb.ChangeType_ASSERT, Template: "t"})
			return nil // clean server close → EOF on client
		},
	}
	c := newMockGRPC(t, mock)

	var n int
	err := c.SubscribeChanges(context.Background(), "s", func(FactChangeEvent) error {
		n++
		return nil
	})
	if err != nil {
		t.Fatalf("expected nil on clean EOF, got %v", err)
	}
	if n != 1 {
		t.Errorf("events: got %d, want 1", n)
	}
}

func TestGRPC_Subscribe_PlainCancelNoSentinel(t *testing.T) {
	// Server blocks until its context is cancelled; client cancels → Canceled.
	mock := &mockServer{
		subscribe: func(_ *pb.SubscribeRequest, stream grpc.ServerStreamingServer[pb.FactChange]) error {
			<-stream.Context().Done()
			return stream.Context().Err()
		},
	}
	c := newMockGRPC(t, mock)

	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()

	err := c.SubscribeChanges(ctx, "s", func(FactChangeEvent) error { return nil })
	if err != nil {
		t.Fatalf("plain cancel should return nil, got %v", err)
	}
	if errors.Is(err, ErrRulesetReloaded) {
		t.Fatal("plain cancel must not map to ErrRulesetReloaded")
	}
}

func TestGRPC_Subscribe_AbortWithoutReloadSurfaced(t *testing.T) {
	// Aborted but NOT a ruleset reload → must surface as a real error.
	mock := &mockServer{
		subscribe: func(_ *pb.SubscribeRequest, _ grpc.ServerStreamingServer[pb.FactChange]) error {
			return status.Error(codes.Aborted, "some other abort")
		},
	}
	c := newMockGRPC(t, mock)

	err := c.SubscribeChanges(context.Background(), "s", func(FactChangeEvent) error { return nil })
	if err == nil {
		t.Fatal("expected error for non-reload abort")
	}
	if errors.Is(err, ErrRulesetReloaded) {
		t.Fatal("non-reload abort must not map to ErrRulesetReloaded")
	}
	if !strings.Contains(err.Error(), "fathom: subscribe") {
		t.Errorf("error not wrapped: %v", err)
	}
}

func TestGRPC_Subscribe_CallbackErrorPropagates(t *testing.T) {
	sentinel := errors.New("stop now")
	mock := &mockServer{
		subscribe: func(_ *pb.SubscribeRequest, stream grpc.ServerStreamingServer[pb.FactChange]) error {
			for i := 0; i < 10; i++ {
				if err := stream.Send(&pb.FactChange{Template: "t"}); err != nil {
					return err
				}
			}
			return nil
		},
	}
	c := newMockGRPC(t, mock)

	err := c.SubscribeChanges(context.Background(), "s", func(FactChangeEvent) error {
		return sentinel
	})
	if !errors.Is(err, sentinel) {
		t.Fatalf("expected callback error to propagate, got %v", err)
	}
}

// ---------- JSON helper edge cases ----------

func TestMarshalMap_NilYieldsEmpty(t *testing.T) {
	s, err := marshalMap(nil)
	if err != nil || s != "" {
		t.Fatalf("nil map: got %q, %v", s, err)
	}
}

func TestUnmarshalMap_EmptyYieldsNil(t *testing.T) {
	m, err := unmarshalMap("")
	if err != nil || m != nil {
		t.Fatalf("empty string: got %v, %v", m, err)
	}
}

func TestUnmarshalMap_Invalid(t *testing.T) {
	_, err := unmarshalMap("{not json")
	if err == nil {
		t.Fatal("expected error for invalid json")
	}
}
