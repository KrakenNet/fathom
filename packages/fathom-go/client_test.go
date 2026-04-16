package fathom

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// ---------- Constructor + Options ----------

func TestNewClient_DefaultsBaseURL(t *testing.T) {
	c := NewClient("http://example.com")
	if c.baseURL != "http://example.com" {
		t.Fatalf("expected baseURL http://example.com, got %s", c.baseURL)
	}
}

func TestNewClient_DefaultHTTPClient(t *testing.T) {
	c := NewClient("http://example.com")
	if c.httpClient == nil {
		t.Fatal("expected non-nil default httpClient")
	}
}

func TestNewClient_DefaultBearerTokenEmpty(t *testing.T) {
	c := NewClient("http://example.com")
	if c.bearerToken != "" {
		t.Fatalf("expected empty bearerToken, got %q", c.bearerToken)
	}
}

func TestWithBearerToken(t *testing.T) {
	c := NewClient("http://example.com", WithBearerToken("my-secret"))
	if c.bearerToken != "my-secret" {
		t.Fatalf("expected bearerToken my-secret, got %q", c.bearerToken)
	}
}

func TestWithHTTPClient(t *testing.T) {
	custom := &http.Client{}
	c := NewClient("http://example.com", WithHTTPClient(custom))
	if c.httpClient != custom {
		t.Fatal("expected custom httpClient to be set")
	}
}

func TestNewClient_MultipleOptions(t *testing.T) {
	custom := &http.Client{}
	c := NewClient("http://example.com", WithBearerToken("tok"), WithHTTPClient(custom))
	if c.bearerToken != "tok" {
		t.Fatalf("expected bearerToken tok, got %q", c.bearerToken)
	}
	if c.httpClient != custom {
		t.Fatal("expected custom httpClient")
	}
}

// ---------- Helpers ----------

// newTestServer creates an httptest.Server that records the request and responds
// with the given status code and JSON body.
func newTestServer(t *testing.T, wantMethod, wantPath string, statusCode int, respBody any) (*httptest.Server, *recordedRequest) {
	t.Helper()
	rec := &recordedRequest{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rec.Method = r.Method
		rec.Path = r.URL.Path
		rec.ContentType = r.Header.Get("Content-Type")
		rec.Authorization = r.Header.Get("Authorization")
		body, _ := io.ReadAll(r.Body)
		rec.Body = body
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(statusCode)
		if respBody != nil {
			json.NewEncoder(w).Encode(respBody)
		}
	}))
	t.Cleanup(srv.Close)
	return srv, rec
}

type recordedRequest struct {
	Method        string
	Path          string
	ContentType   string
	Authorization string
	Body          []byte
}

// ---------- Evaluate ----------

func TestEvaluate_Success(t *testing.T) {
	want := EvaluateResponse{
		Decision:         "allow",
		Reason:           "all rules passed",
		RuleTrace:        []string{"rule-1", "rule-2"},
		ModuleTrace:      []string{"mod-a"},
		DurationUS:       42,
		AttestationToken: "att-tok-123",
	}
	srv, rec := newTestServer(t, http.MethodPost, "/v1/evaluate", 200, want)

	c := NewClient(srv.URL)
	req := &EvaluateRequest{
		Facts: []FactInput{
			{Template: "user", Data: map[string]any{"role": "admin"}},
		},
		Ruleset:   "authz",
		SessionID: "sess-1",
	}
	got, err := c.Evaluate(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify response fields
	if got.Decision != want.Decision {
		t.Errorf("Decision: got %q, want %q", got.Decision, want.Decision)
	}
	if got.Reason != want.Reason {
		t.Errorf("Reason: got %q, want %q", got.Reason, want.Reason)
	}
	if len(got.RuleTrace) != len(want.RuleTrace) {
		t.Errorf("RuleTrace length: got %d, want %d", len(got.RuleTrace), len(want.RuleTrace))
	}
	if len(got.ModuleTrace) != len(want.ModuleTrace) {
		t.Errorf("ModuleTrace length: got %d, want %d", len(got.ModuleTrace), len(want.ModuleTrace))
	}
	if got.DurationUS != want.DurationUS {
		t.Errorf("DurationUS: got %d, want %d", got.DurationUS, want.DurationUS)
	}
	if got.AttestationToken != want.AttestationToken {
		t.Errorf("AttestationToken: got %q, want %q", got.AttestationToken, want.AttestationToken)
	}

	// Verify request method and path
	if rec.Method != http.MethodPost {
		t.Errorf("Method: got %q, want POST", rec.Method)
	}
	if rec.Path != "/v1/evaluate" {
		t.Errorf("Path: got %q, want /v1/evaluate", rec.Path)
	}
}

func TestEvaluate_RequestBodyMarshaling(t *testing.T) {
	srv, rec := newTestServer(t, http.MethodPost, "/v1/evaluate", 200, EvaluateResponse{})

	c := NewClient(srv.URL)
	req := &EvaluateRequest{
		Facts: []FactInput{
			{Template: "resource", Data: map[string]any{"type": "file", "owner": "alice"}},
		},
		Ruleset:   "access-control",
		SessionID: "s-99",
	}
	_, err := c.Evaluate(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var sent EvaluateRequest
	if err := json.Unmarshal(rec.Body, &sent); err != nil {
		t.Fatalf("failed to unmarshal request body: %v", err)
	}
	if sent.Ruleset != "access-control" {
		t.Errorf("Ruleset: got %q, want access-control", sent.Ruleset)
	}
	if sent.SessionID != "s-99" {
		t.Errorf("SessionID: got %q, want s-99", sent.SessionID)
	}
	if len(sent.Facts) != 1 || sent.Facts[0].Template != "resource" {
		t.Errorf("Facts not marshaled correctly: %+v", sent.Facts)
	}
}

func TestEvaluate_ContentTypeHeader(t *testing.T) {
	srv, rec := newTestServer(t, http.MethodPost, "/v1/evaluate", 200, EvaluateResponse{})

	c := NewClient(srv.URL)
	_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rec.ContentType != "application/json" {
		t.Errorf("Content-Type: got %q, want application/json", rec.ContentType)
	}
}

// ---------- AssertFact ----------

func TestAssertFact_Success(t *testing.T) {
	want := AssertFactResponse{Success: true}
	srv, rec := newTestServer(t, http.MethodPost, "/v1/facts", 200, want)

	c := NewClient(srv.URL)
	req := &AssertFactRequest{
		SessionID: "sess-1",
		Template:  "user",
		Data:      map[string]any{"name": "bob"},
	}
	got, err := c.AssertFact(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !got.Success {
		t.Error("expected Success to be true")
	}
	if rec.Method != http.MethodPost {
		t.Errorf("Method: got %q, want POST", rec.Method)
	}
	if rec.Path != "/v1/facts" {
		t.Errorf("Path: got %q, want /v1/facts", rec.Path)
	}
}

func TestAssertFact_RequestBody(t *testing.T) {
	srv, rec := newTestServer(t, http.MethodPost, "/v1/facts", 200, AssertFactResponse{Success: true})

	c := NewClient(srv.URL)
	req := &AssertFactRequest{
		SessionID: "sess-42",
		Template:  "order",
		Data:      map[string]any{"amount": float64(100)},
	}
	_, err := c.AssertFact(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var sent AssertFactRequest
	if err := json.Unmarshal(rec.Body, &sent); err != nil {
		t.Fatalf("failed to unmarshal body: %v", err)
	}
	if sent.SessionID != "sess-42" {
		t.Errorf("SessionID: got %q, want sess-42", sent.SessionID)
	}
	if sent.Template != "order" {
		t.Errorf("Template: got %q, want order", sent.Template)
	}
}

// ---------- Query ----------

func TestQuery_SuccessWithFacts(t *testing.T) {
	want := QueryResponse{
		Facts: []map[string]any{
			{"name": "alice", "role": "admin"},
			{"name": "bob", "role": "viewer"},
		},
	}
	srv, rec := newTestServer(t, http.MethodPost, "/v1/query", 200, want)

	c := NewClient(srv.URL)
	req := &QueryRequest{
		SessionID: "sess-1",
		Template:  "user",
		Filter:    map[string]any{"role": "admin"},
	}
	got, err := c.Query(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got.Facts) != 2 {
		t.Fatalf("expected 2 facts, got %d", len(got.Facts))
	}
	if rec.Method != http.MethodPost {
		t.Errorf("Method: got %q, want POST", rec.Method)
	}
	if rec.Path != "/v1/query" {
		t.Errorf("Path: got %q, want /v1/query", rec.Path)
	}
}

func TestQuery_EmptyFacts(t *testing.T) {
	want := QueryResponse{Facts: []map[string]any{}}
	srv, _ := newTestServer(t, http.MethodPost, "/v1/query", 200, want)

	c := NewClient(srv.URL)
	got, err := c.Query(context.Background(), &QueryRequest{
		SessionID: "sess-1",
		Template:  "nonexistent",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got.Facts) != 0 {
		t.Errorf("expected 0 facts, got %d", len(got.Facts))
	}
}

func TestQuery_RequestBody(t *testing.T) {
	srv, rec := newTestServer(t, http.MethodPost, "/v1/query", 200, QueryResponse{})

	c := NewClient(srv.URL)
	_, err := c.Query(context.Background(), &QueryRequest{
		SessionID: "sess-7",
		Template:  "event",
		Filter:    map[string]any{"severity": "high"},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var sent QueryRequest
	if err := json.Unmarshal(rec.Body, &sent); err != nil {
		t.Fatalf("failed to unmarshal body: %v", err)
	}
	if sent.SessionID != "sess-7" {
		t.Errorf("SessionID: got %q, want sess-7", sent.SessionID)
	}
	if sent.Template != "event" {
		t.Errorf("Template: got %q, want event", sent.Template)
	}
}

// ---------- Retract ----------

func TestRetract_Success(t *testing.T) {
	want := RetractResponse{RetractedCount: 3}
	srv, rec := newTestServer(t, http.MethodDelete, "/v1/facts", 200, want)

	c := NewClient(srv.URL)
	req := &RetractRequest{
		SessionID: "sess-1",
		Template:  "user",
		Filter:    map[string]any{"role": "guest"},
	}
	got, err := c.Retract(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.RetractedCount != 3 {
		t.Errorf("RetractedCount: got %d, want 3", got.RetractedCount)
	}
	if rec.Method != http.MethodDelete {
		t.Errorf("Method: got %q, want DELETE", rec.Method)
	}
	if rec.Path != "/v1/facts" {
		t.Errorf("Path: got %q, want /v1/facts", rec.Path)
	}
}

// ---------- Bearer Token ----------

func TestBearerToken_SentWhenSet(t *testing.T) {
	srv, rec := newTestServer(t, http.MethodPost, "/v1/evaluate", 200, EvaluateResponse{})

	c := NewClient(srv.URL, WithBearerToken("super-secret-token"))
	_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "Bearer super-secret-token"
	if rec.Authorization != want {
		t.Errorf("Authorization: got %q, want %q", rec.Authorization, want)
	}
}

func TestBearerToken_NotSentWhenEmpty(t *testing.T) {
	srv, rec := newTestServer(t, http.MethodPost, "/v1/evaluate", 200, EvaluateResponse{})

	c := NewClient(srv.URL) // no WithBearerToken
	_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rec.Authorization != "" {
		t.Errorf("expected empty Authorization header, got %q", rec.Authorization)
	}
}

// ---------- Error Handling ----------

func TestError_Non2xxStatusCode(t *testing.T) {
	tests := []struct {
		name       string
		statusCode int
		body       string
	}{
		{"400 Bad Request", 400, `{"error":"bad request"}`},
		{"401 Unauthorized", 401, `{"error":"unauthorized"}`},
		{"403 Forbidden", 403, `{"error":"forbidden"}`},
		{"404 Not Found", 404, `{"error":"not found"}`},
		{"500 Internal Server Error", 500, `{"error":"internal"}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tt.statusCode)
				w.Write([]byte(tt.body))
			}))
			t.Cleanup(srv.Close)

			c := NewClient(srv.URL)
			_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
			if err == nil {
				t.Fatal("expected error for non-2xx status")
			}
			// Error should contain the status code
			if !strings.Contains(err.Error(), fmt.Sprintf("%d", tt.statusCode)) {
				t.Errorf("error should contain status code %d: %v", tt.statusCode, err)
			}
			// Error should contain the body
			if !strings.Contains(err.Error(), tt.body) {
				t.Errorf("error should contain body %q: %v", tt.body, err)
			}
		})
	}
}

func TestError_JSONDecodeError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		w.Write([]byte("not valid json{{{"))
	}))
	t.Cleanup(srv.Close)

	c := NewClient(srv.URL)
	_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
	if err == nil {
		t.Fatal("expected error for invalid JSON response")
	}
	if !strings.Contains(err.Error(), "decode response") {
		t.Errorf("error should mention decode response: %v", err)
	}
}

func TestError_JSONMarshalError(t *testing.T) {
	// json.Marshal fails on channels
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Fatal("server should not be called when marshal fails")
	}))
	t.Cleanup(srv.Close)

	c := NewClient(srv.URL)
	// Pass an unmarshalable body through the internal do() method.
	// We use a struct with a channel field which json.Marshal cannot handle.
	type badBody struct {
		Ch chan int `json:"ch"`
	}
	var out EvaluateResponse
	err := c.do(context.Background(), http.MethodPost, "/v1/evaluate", &badBody{Ch: make(chan int)}, &out)
	if err == nil {
		t.Fatal("expected error for unmarshalable body")
	}
	if !strings.Contains(err.Error(), "marshal request") {
		t.Errorf("error should mention marshal request: %v", err)
	}
}

// ---------- HTTP Methods (table-driven) ----------

func TestHTTPMethods(t *testing.T) {
	tests := []struct {
		name       string
		call       func(c *Client) error
		wantMethod string
		wantPath   string
	}{
		{
			name: "Evaluate uses POST",
			call: func(c *Client) error {
				_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
				return err
			},
			wantMethod: http.MethodPost,
			wantPath:   "/v1/evaluate",
		},
		{
			name: "AssertFact uses POST",
			call: func(c *Client) error {
				_, err := c.AssertFact(context.Background(), &AssertFactRequest{})
				return err
			},
			wantMethod: http.MethodPost,
			wantPath:   "/v1/facts",
		},
		{
			name: "Query uses POST",
			call: func(c *Client) error {
				_, err := c.Query(context.Background(), &QueryRequest{})
				return err
			},
			wantMethod: http.MethodPost,
			wantPath:   "/v1/query",
		},
		{
			name: "Retract uses DELETE",
			call: func(c *Client) error {
				_, err := c.Retract(context.Background(), &RetractRequest{})
				return err
			},
			wantMethod: http.MethodDelete,
			wantPath:   "/v1/facts",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var gotMethod, gotPath string
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotMethod = r.Method
				gotPath = r.URL.Path
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(200)
				w.Write([]byte("{}"))
			}))
			t.Cleanup(srv.Close)

			c := NewClient(srv.URL)
			err := tt.call(c)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if gotMethod != tt.wantMethod {
				t.Errorf("Method: got %q, want %q", gotMethod, tt.wantMethod)
			}
			if gotPath != tt.wantPath {
				t.Errorf("Path: got %q, want %q", gotPath, tt.wantPath)
			}
		})
	}
}

// ---------- Context cancellation ----------

func TestContextCancellation(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Block until context is done - this simulates a slow server
		<-r.Context().Done()
	}))
	t.Cleanup(srv.Close)

	c := NewClient(srv.URL)
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately

	_, err := c.Evaluate(ctx, &EvaluateRequest{})
	if err == nil {
		t.Fatal("expected error for cancelled context")
	}
}

// ---------- Content-Type on all methods ----------

func TestContentType_AllMethods(t *testing.T) {
	tests := []struct {
		name string
		call func(c *Client) error
	}{
		{
			name: "Evaluate",
			call: func(c *Client) error {
				_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
				return err
			},
		},
		{
			name: "AssertFact",
			call: func(c *Client) error {
				_, err := c.AssertFact(context.Background(), &AssertFactRequest{})
				return err
			},
		},
		{
			name: "Query",
			call: func(c *Client) error {
				_, err := c.Query(context.Background(), &QueryRequest{})
				return err
			},
		},
		{
			name: "Retract",
			call: func(c *Client) error {
				_, err := c.Retract(context.Background(), &RetractRequest{})
				return err
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var gotCT string
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotCT = r.Header.Get("Content-Type")
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(200)
				w.Write([]byte("{}"))
			}))
			t.Cleanup(srv.Close)

			c := NewClient(srv.URL)
			_ = tt.call(c)
			if gotCT != "application/json" {
				t.Errorf("Content-Type: got %q, want application/json", gotCT)
			}
		})
	}
}

// ---------- Bearer token across all methods ----------

func TestBearerToken_AllMethods(t *testing.T) {
	tests := []struct {
		name string
		call func(c *Client) error
	}{
		{
			name: "Evaluate",
			call: func(c *Client) error {
				_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
				return err
			},
		},
		{
			name: "AssertFact",
			call: func(c *Client) error {
				_, err := c.AssertFact(context.Background(), &AssertFactRequest{})
				return err
			},
		},
		{
			name: "Query",
			call: func(c *Client) error {
				_, err := c.Query(context.Background(), &QueryRequest{})
				return err
			},
		},
		{
			name: "Retract",
			call: func(c *Client) error {
				_, err := c.Retract(context.Background(), &RetractRequest{})
				return err
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var gotAuth string
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotAuth = r.Header.Get("Authorization")
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(200)
				w.Write([]byte("{}"))
			}))
			t.Cleanup(srv.Close)

			c := NewClient(srv.URL, WithBearerToken("all-methods-tok"))
			_ = tt.call(c)
			want := "Bearer all-methods-tok"
			if gotAuth != want {
				t.Errorf("Authorization: got %q, want %q", gotAuth, want)
			}
		})
	}
}

// ---------- Edge: 2xx boundary ----------

func TestStatusCodeBoundary(t *testing.T) {
	tests := []struct {
		name      string
		status    int
		wantError bool
	}{
		{"200 is OK", 200, false},
		{"201 is OK", 201, false},
		{"299 is OK", 299, false},
		{"400 is error", 400, true},
		{"500 is error", 500, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(tt.status)
				w.Write([]byte("{}"))
			}))
			t.Cleanup(srv.Close)

			c := NewClient(srv.URL)
			_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
			if tt.wantError && err == nil {
				t.Errorf("expected error for status %d", tt.status)
			}
			if !tt.wantError && err != nil {
				t.Errorf("unexpected error for status %d: %v", tt.status, err)
			}
		})
	}
}

// ---------- Error wrapping ----------

func TestEvaluate_ErrorWrapping(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(403)
		w.Write([]byte("forbidden"))
	}))
	t.Cleanup(srv.Close)

	c := NewClient(srv.URL)
	_, err := c.Evaluate(context.Background(), &EvaluateRequest{})
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "fathom: evaluate") {
		t.Errorf("error should be wrapped with 'fathom: evaluate': %v", err)
	}
}

func TestAssertFact_ErrorWrapping(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
		w.Write([]byte("internal error"))
	}))
	t.Cleanup(srv.Close)

	c := NewClient(srv.URL)
	_, err := c.AssertFact(context.Background(), &AssertFactRequest{})
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "fathom: assert fact") {
		t.Errorf("error should be wrapped with 'fathom: assert fact': %v", err)
	}
}

func TestQuery_ErrorWrapping(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
		w.Write([]byte("error"))
	}))
	t.Cleanup(srv.Close)

	c := NewClient(srv.URL)
	_, err := c.Query(context.Background(), &QueryRequest{})
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "fathom: query") {
		t.Errorf("error should be wrapped with 'fathom: query': %v", err)
	}
}

func TestRetract_ErrorWrapping(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
		w.Write([]byte("error"))
	}))
	t.Cleanup(srv.Close)

	c := NewClient(srv.URL)
	_, err := c.Retract(context.Background(), &RetractRequest{})
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "fathom: retract") {
		t.Errorf("error should be wrapped with 'fathom: retract': %v", err)
	}
}

// ---------- SessionID omitempty for Evaluate ----------

func TestEvaluate_SessionIDOmittedWhenEmpty(t *testing.T) {
	srv, rec := newTestServer(t, http.MethodPost, "/v1/evaluate", 200, EvaluateResponse{})

	c := NewClient(srv.URL)
	_, err := c.Evaluate(context.Background(), &EvaluateRequest{
		Facts:   []FactInput{{Template: "t", Data: map[string]any{}}},
		Ruleset: "rs",
		// SessionID intentionally left empty
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var raw map[string]any
	if err := json.Unmarshal(rec.Body, &raw); err != nil {
		t.Fatalf("failed to unmarshal body: %v", err)
	}
	if _, exists := raw["session_id"]; exists {
		t.Error("expected session_id to be omitted from JSON when empty")
	}
}

// ---------- Query filter omitempty ----------

func TestQuery_FilterOmittedWhenNil(t *testing.T) {
	srv, rec := newTestServer(t, http.MethodPost, "/v1/query", 200, QueryResponse{})

	c := NewClient(srv.URL)
	_, err := c.Query(context.Background(), &QueryRequest{
		SessionID: "s",
		Template:  "t",
		// Filter intentionally left nil
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var raw map[string]any
	if err := json.Unmarshal(rec.Body, &raw); err != nil {
		t.Fatalf("failed to unmarshal body: %v", err)
	}
	if _, exists := raw["filter"]; exists {
		t.Error("expected filter to be omitted from JSON when nil")
	}
}
