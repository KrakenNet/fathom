// Package fathom provides a Go client for the Fathom policy engine REST API.
package fathom

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// Client communicates with the Fathom REST API.
type Client struct {
	baseURL     string
	httpClient  *http.Client
	bearerToken string
}

// ClientOption mutates a Client during construction.
type ClientOption func(*Client)

// WithBearerToken configures the client to send "Authorization: Bearer <tok>"
// on every request.
func WithBearerToken(tok string) ClientOption {
	return func(c *Client) { c.bearerToken = tok }
}

// WithHTTPClient overrides the underlying *http.Client (useful for tests or
// custom transports).
func WithHTTPClient(hc *http.Client) ClientOption {
	return func(c *Client) { c.httpClient = hc }
}

// NewClient creates a new Fathom client pointing at the given base URL.
// Example:
//
//	client := NewClient("http://localhost:8000", WithBearerToken("secret"))
func NewClient(baseURL string, opts ...ClientOption) *Client {
	c := &Client{
		baseURL:    baseURL,
		httpClient: &http.Client{},
	}
	for _, opt := range opts {
		opt(c)
	}
	return c
}

// FactInput is a single fact assertion used inside EvaluateRequest.
type FactInput struct {
	Template string         `json:"template"`
	Data     map[string]any `json:"data"`
}

// EvaluateRequest is the payload for POST /v1/evaluate.
type EvaluateRequest struct {
	Facts     []FactInput `json:"facts"`
	Ruleset   string      `json:"ruleset"`
	SessionID string      `json:"session_id,omitempty"`
}

// EvaluateResponse is the response from POST /v1/evaluate.
type EvaluateResponse struct {
	Decision         string   `json:"decision"`
	Reason           string   `json:"reason"`
	RuleTrace        []string `json:"rule_trace"`
	ModuleTrace      []string `json:"module_trace"`
	DurationUS       int64    `json:"duration_us"`
	AttestationToken string   `json:"attestation_token,omitempty"`
}

// Evaluate sends facts to the engine and returns the policy decision.
func (c *Client) Evaluate(ctx context.Context, req *EvaluateRequest) (*EvaluateResponse, error) {
	var out EvaluateResponse
	if err := c.do(ctx, http.MethodPost, "/v1/evaluate", req, &out); err != nil {
		return nil, fmt.Errorf("fathom: evaluate: %w", err)
	}
	return &out, nil
}

// AssertFactRequest is the payload for POST /v1/facts.
type AssertFactRequest struct {
	SessionID string         `json:"session_id"`
	Template  string         `json:"template"`
	Data      map[string]any `json:"data"`
}

// AssertFactResponse is the response from POST /v1/facts.
type AssertFactResponse struct {
	Success bool `json:"success"`
}

// AssertFact asserts a single fact into the session's working memory.
func (c *Client) AssertFact(ctx context.Context, req *AssertFactRequest) (*AssertFactResponse, error) {
	var out AssertFactResponse
	if err := c.do(ctx, http.MethodPost, "/v1/facts", req, &out); err != nil {
		return nil, fmt.Errorf("fathom: assert fact: %w", err)
	}
	return &out, nil
}

// QueryRequest is the payload for POST /v1/query.
type QueryRequest struct {
	SessionID string         `json:"session_id"`
	Template  string         `json:"template"`
	Filter    map[string]any `json:"filter,omitempty"`
}

// QueryResponse is the response from POST /v1/query.
type QueryResponse struct {
	Facts []map[string]any `json:"facts"`
}

// Query retrieves facts from the session's working memory.
func (c *Client) Query(ctx context.Context, req *QueryRequest) (*QueryResponse, error) {
	var out QueryResponse
	if err := c.do(ctx, http.MethodPost, "/v1/query", req, &out); err != nil {
		return nil, fmt.Errorf("fathom: query: %w", err)
	}
	return &out, nil
}

// RetractRequest is the payload for DELETE /v1/facts.
type RetractRequest struct {
	SessionID string         `json:"session_id"`
	Template  string         `json:"template"`
	Filter    map[string]any `json:"filter,omitempty"`
}

// RetractResponse is the response from DELETE /v1/facts.
type RetractResponse struct {
	RetractedCount int `json:"retracted_count"`
}

// Retract removes facts matching the request's template + optional filter
// from the session's working memory and returns the number of retractions.
func (c *Client) Retract(ctx context.Context, req *RetractRequest) (*RetractResponse, error) {
	var out RetractResponse
	if err := c.do(ctx, http.MethodDelete, "/v1/facts", req, &out); err != nil {
		return nil, fmt.Errorf("fathom: retract: %w", err)
	}
	return &out, nil
}

// do executes an HTTP request with the given method/path, marshaling body as
// JSON and decoding the response into out.
func (c *Client) do(ctx context.Context, method, path string, body, out any) error {
	buf, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, bytes.NewReader(buf))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	if c.bearerToken != "" {
		httpReq.Header.Set("Authorization", "Bearer "+c.bearerToken)
	}

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("http: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("server returned %d: %s", resp.StatusCode, string(b))
	}

	if out != nil {
		if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
			return fmt.Errorf("decode response: %w", err)
		}
	}
	return nil
}
