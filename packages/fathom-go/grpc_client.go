package fathom

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"

	pb "github.com/KrakenNet/fathom-go/proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
)

// ErrRulesetReloaded is returned by the SubscribeChanges stream when the server
// aborts it because the engine's ruleset was hot-reloaded (ADR-0002, option a —
// cancel on swap). It is errors.Is-able: callers should treat it as a normal
// lifecycle event, re-subscribe to bind to the new ruleset, then re-Query to
// re-synchronize.
var ErrRulesetReloaded = errors.New("fathom: ruleset reloaded; re-subscribe to bind to the new ruleset")

// GRPCClient is an idiomatic wrapper around the generated FathomService gRPC
// stub. It mirrors the REST Client's request/response shapes (map[string]any
// fact data) while transparently handling the proto's JSON-encoded string
// fields, bearer-token metadata, and the SubscribeChanges reload contract.
type GRPCClient struct {
	conn   *grpc.ClientConn
	stub   pb.FathomServiceClient
	target string
}

// grpcConfig accumulates GRPCOption mutations before the client is built.
type grpcConfig struct {
	bearerToken   string
	allowInsecure bool
	dialOpts      []grpc.DialOption
}

// GRPCOption configures a GRPCClient during construction.
type GRPCOption func(*grpcConfig)

// WithGRPCBearerToken attaches "authorization: Bearer <tok>" metadata to every
// RPC via per-RPC credentials (mirroring the server's bearer-auth contract).
//
// gRPC refuses to send per-RPC credentials over an insecure transport unless
// the caller has explicitly opted in via WithGRPCInsecure (mirroring the
// server's FATHOM_GRPC_ALLOW_INSECURE posture). With a secure transport this
// restriction does not apply.
func WithGRPCBearerToken(tok string) GRPCOption {
	return func(c *grpcConfig) { c.bearerToken = tok }
}

// WithGRPCInsecure permits an insecure (plaintext) transport and allows bearer
// credentials to be sent over it. This mirrors the server's
// FATHOM_GRPC_ALLOW_INSECURE=1 escape hatch and should only be used for local
// development or trusted networks.
//
// When not set, NewGRPCClient defaults to TLS transport credentials.
func WithGRPCInsecure() GRPCOption {
	return func(c *grpcConfig) { c.allowInsecure = true }
}

// WithDialOptions appends raw grpc.DialOption values, an escape hatch for
// transport credentials, interceptors, keepalive, etc. These are applied after
// the wrapper's own defaults, so they win on conflict.
func WithDialOptions(opts ...grpc.DialOption) GRPCOption {
	return func(c *grpcConfig) { c.dialOpts = append(c.dialOpts, opts...) }
}

// NewGRPCClient dials target and returns a ready-to-use GRPCClient. The caller
// owns the connection and must Close it when done.
//
// Example:
//
//	c, err := NewGRPCClient("localhost:50051",
//	    WithGRPCBearerToken("secret"), WithGRPCInsecure())
//	if err != nil { ... }
//	defer c.Close()
func NewGRPCClient(target string, opts ...GRPCOption) (*GRPCClient, error) {
	cfg := &grpcConfig{}
	for _, opt := range opts {
		opt(cfg)
	}

	dialOpts := make([]grpc.DialOption, 0, len(cfg.dialOpts)+2)
	if cfg.allowInsecure {
		dialOpts = append(dialOpts, grpc.WithTransportCredentials(insecure.NewCredentials()))
	} else {
		dialOpts = append(dialOpts, grpc.WithTransportCredentials(credentials.NewTLS(nil)))
	}
	if cfg.bearerToken != "" {
		dialOpts = append(dialOpts, grpc.WithPerRPCCredentials(bearerPerRPC{
			token:           cfg.bearerToken,
			requireSecurity: !cfg.allowInsecure,
		}))
	}
	// User dial options come last so they can override the defaults above.
	dialOpts = append(dialOpts, cfg.dialOpts...)

	conn, err := grpc.NewClient(target, dialOpts...)
	if err != nil {
		return nil, fmt.Errorf("fathom: grpc dial %q: %w", target, err)
	}
	return &GRPCClient{
		conn:   conn,
		stub:   pb.NewFathomServiceClient(conn),
		target: target,
	}, nil
}

// Close releases the underlying gRPC connection.
func (c *GRPCClient) Close() error {
	return c.conn.Close()
}

// bearerPerRPC implements credentials.PerRPCCredentials, attaching the bearer
// token as "authorization: Bearer <tok>" metadata on every call.
type bearerPerRPC struct {
	token           string
	requireSecurity bool
}

func (b bearerPerRPC) GetRequestMetadata(_ context.Context, _ ...string) (map[string]string, error) {
	return map[string]string{"authorization": "Bearer " + b.token}, nil
}

func (b bearerPerRPC) RequireTransportSecurity() bool { return b.requireSecurity }

// ---------- Unary RPCs ----------

// Evaluate sends facts to the engine and returns the policy decision. The
// EvaluateRequest/EvaluateResponse types are the REST client's shapes; fact
// Data maps are JSON-encoded into the proto's data_json fields internally.
//
// Note: unlike the REST EvaluateResponse, the gRPC EvaluateResponse carries no
// attestation_token (the proto omits it), so that field is always empty here.
func (c *GRPCClient) Evaluate(ctx context.Context, req *EvaluateRequest) (*EvaluateResponse, error) {
	facts, err := factsToProto(req.Facts)
	if err != nil {
		return nil, fmt.Errorf("fathom: evaluate: %w", err)
	}
	resp, err := c.stub.Evaluate(ctx, &pb.EvaluateRequest{
		SessionId: req.SessionID,
		Ruleset:   req.Ruleset,
		Facts:     facts,
	})
	if err != nil {
		return nil, fmt.Errorf("fathom: evaluate: %w", err)
	}
	return &EvaluateResponse{
		Decision:    resp.GetDecision(),
		Reason:      resp.GetReason(),
		RuleTrace:   resp.GetRuleTrace(),
		ModuleTrace: resp.GetModuleTrace(),
		DurationUS:  resp.GetDurationUs(),
	}, nil
}

// AssertFact asserts a single fact into the session's working memory.
func (c *GRPCClient) AssertFact(ctx context.Context, req *AssertFactRequest) (*AssertFactResponse, error) {
	dataJSON, err := marshalMap(req.Data)
	if err != nil {
		return nil, fmt.Errorf("fathom: assert fact: %w", err)
	}
	resp, err := c.stub.AssertFact(ctx, &pb.AssertFactRequest{
		SessionId: req.SessionID,
		Template:  req.Template,
		DataJson:  dataJSON,
	})
	if err != nil {
		return nil, fmt.Errorf("fathom: assert fact: %w", err)
	}
	return &AssertFactResponse{Success: resp.GetSuccess()}, nil
}

// Query retrieves facts from the session's working memory.
func (c *GRPCClient) Query(ctx context.Context, req *QueryRequest) (*QueryResponse, error) {
	filterJSON, err := marshalMap(req.Filter)
	if err != nil {
		return nil, fmt.Errorf("fathom: query: %w", err)
	}
	resp, err := c.stub.Query(ctx, &pb.QueryRequest{
		SessionId:  req.SessionID,
		Template:   req.Template,
		FilterJson: filterJSON,
	})
	if err != nil {
		return nil, fmt.Errorf("fathom: query: %w", err)
	}
	facts := make([]map[string]any, 0, len(resp.GetFactsJson()))
	for _, fj := range resp.GetFactsJson() {
		m, err := unmarshalMap(fj)
		if err != nil {
			return nil, fmt.Errorf("fathom: query: decode fact: %w", err)
		}
		facts = append(facts, m)
	}
	return &QueryResponse{Facts: facts}, nil
}

// Retract removes facts matching the request's template + optional filter and
// returns the number of retractions.
func (c *GRPCClient) Retract(ctx context.Context, req *RetractRequest) (*RetractResponse, error) {
	filterJSON, err := marshalMap(req.Filter)
	if err != nil {
		return nil, fmt.Errorf("fathom: retract: %w", err)
	}
	resp, err := c.stub.Retract(ctx, &pb.RetractRequest{
		SessionId:  req.SessionID,
		Template:   req.Template,
		FilterJson: filterJSON,
	})
	if err != nil {
		return nil, fmt.Errorf("fathom: retract: %w", err)
	}
	return &RetractResponse{RetractedCount: int(resp.GetRetractedCount())}, nil
}

// ReloadRequest is the payload for the Reload RPC. Exactly one of RulesetPath
// or RulesetYAML should be set (mirroring the proto's oneof source). Signature
// is the optional detached signature bytes for the ruleset.
type ReloadRequest struct {
	RulesetPath string
	RulesetYAML string
	Signature   []byte
}

// ReloadResponse is the response from the Reload RPC.
type ReloadResponse struct {
	RulesetHashBefore string
	RulesetHashAfter  string
	AttestationToken  string
}

// Reload hot-reloads the engine's ruleset from an inline YAML body or a
// server-side path. A successful reload aborts every in-flight SubscribeChanges
// stream with ErrRulesetReloaded (ADR-0002).
func (c *GRPCClient) Reload(ctx context.Context, req *ReloadRequest) (*ReloadResponse, error) {
	pbReq := &pb.ReloadRequest{Signature: req.Signature}
	switch {
	case req.RulesetYAML != "":
		pbReq.Source = &pb.ReloadRequest_RulesetYaml{RulesetYaml: req.RulesetYAML}
	case req.RulesetPath != "":
		pbReq.Source = &pb.ReloadRequest_RulesetPath{RulesetPath: req.RulesetPath}
	}
	resp, err := c.stub.Reload(ctx, pbReq)
	if err != nil {
		return nil, fmt.Errorf("fathom: reload: %w", err)
	}
	return &ReloadResponse{
		RulesetHashBefore: resp.GetRulesetHashBefore(),
		RulesetHashAfter:  resp.GetRulesetHashAfter(),
		AttestationToken:  resp.GetAttestationToken(),
	}, nil
}

// ---------- SubscribeChanges ----------

// ChangeType mirrors the proto's fact-change kinds.
type ChangeType int32

const (
	ChangeTypeUnspecified ChangeType = iota
	ChangeTypeAssert
	ChangeTypeRetract
)

// FactChangeEvent is a single working-memory change yielded by SubscribeChanges.
// DataJSON's slot data is decoded into Data for convenience.
type FactChangeEvent struct {
	ChangeType ChangeType
	Template   string
	Data       map[string]any
}

// SubscribeChanges opens a server stream of working-memory changes for the
// given session and invokes fn for each event. It blocks until one of:
//
//   - fn returns a non-nil error (returned as-is),
//   - the server aborts the stream because the ruleset was reloaded
//     (returns ErrRulesetReloaded; re-subscribe + re-Query),
//   - the stream ends cleanly (server EOF or ctx cancellation; returns nil),
//   - any other gRPC error (returned wrapped).
//
// Plain client-side cancellation (ctx cancel / deadline) and a clean server
// close both return nil — they are not surfaced as ErrRulesetReloaded.
func (c *GRPCClient) SubscribeChanges(ctx context.Context, sessionID string, fn func(FactChangeEvent) error) error {
	stream, err := c.stub.SubscribeChanges(ctx, &pb.SubscribeRequest{SessionId: sessionID})
	if err != nil {
		return mapStreamErr(err)
	}
	for {
		msg, err := stream.Recv()
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return mapStreamErr(err)
		}
		data, derr := unmarshalMap(msg.GetDataJson())
		if derr != nil {
			return fmt.Errorf("fathom: subscribe: decode change: %w", derr)
		}
		if ferr := fn(FactChangeEvent{
			ChangeType: ChangeType(msg.GetChangeType()),
			Template:   msg.GetTemplate(),
			Data:       data,
		}); ferr != nil {
			return ferr
		}
	}
}

// mapStreamErr translates a SubscribeChanges stream error: a clean client-side
// cancellation is squashed to nil, the reload-abort contract maps to
// ErrRulesetReloaded, and everything else is returned wrapped.
func mapStreamErr(err error) error {
	wrapped := fmt.Errorf("fathom: subscribe: %w", err)
	st, ok := status.FromError(err)
	if !ok {
		return wrapped
	}
	switch st.Code() {
	case codes.Aborted:
		if strings.Contains(st.Message(), "ruleset_reloaded") {
			return ErrRulesetReloaded
		}
		return wrapped
	case codes.Canceled:
		// Caller-initiated cancellation/deadline; a clean shutdown, not an error.
		return nil
	default:
		return wrapped
	}
}

// ---------- JSON helpers ----------

// factsToProto converts REST-shaped FactInput values into proto FactInput
// values, JSON-encoding each Data map into data_json.
func factsToProto(facts []FactInput) ([]*pb.FactInput, error) {
	out := make([]*pb.FactInput, 0, len(facts))
	for _, f := range facts {
		dataJSON, err := marshalMap(f.Data)
		if err != nil {
			return nil, fmt.Errorf("encode fact %q: %w", f.Template, err)
		}
		out = append(out, &pb.FactInput{Template: f.Template, DataJson: dataJSON})
	}
	return out, nil
}

// marshalMap JSON-encodes a map for a proto *_json field. A nil map yields an
// empty string so the field is omitted on the wire.
func marshalMap(m map[string]any) (string, error) {
	if m == nil {
		return "", nil
	}
	b, err := json.Marshal(m)
	if err != nil {
		return "", fmt.Errorf("marshal json: %w", err)
	}
	return string(b), nil
}

// unmarshalMap decodes a proto *_json field into a map. An empty string yields
// a nil map (no data).
func unmarshalMap(s string) (map[string]any, error) {
	if s == "" {
		return nil, nil
	}
	var m map[string]any
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		return nil, fmt.Errorf("unmarshal json: %w", err)
	}
	return m, nil
}
