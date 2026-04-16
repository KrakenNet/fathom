/**
 * Fathom TypeScript SDK — high-level client for the Fathom policy engine REST API.
 *
 * @module @fathom-rules/sdk
 */

import {
  FathomError,
  PolicyViolation,
  ValidationError,
  ConnectionError,
} from "./errors";

// ---------------------------------------------------------------------------
// Request / Response types
// ---------------------------------------------------------------------------

/** A single fact assertion used inside {@link EvaluateRequest}. */
export interface FactInput {
  template: string;
  data: Record<string, unknown>;
}

/** Payload for POST /v1/evaluate. */
export interface EvaluateRequest {
  facts: FactInput[];
  ruleset: string;
  session_id?: string;
}

/** Response from POST /v1/evaluate. */
export interface EvaluateResponse {
  decision: string | null;
  reason: string | null;
  rule_trace: string[];
  module_trace: string[];
  duration_us: number;
  attestation_token?: string | null;
}

/** Payload for POST /v1/facts. */
export interface AssertFactRequest {
  session_id: string;
  template: string;
  data: Record<string, unknown>;
}

/** Response from POST /v1/facts. */
export interface AssertFactResponse {
  success: boolean;
}

/** Payload for POST /v1/query. */
export interface QueryRequest {
  session_id: string;
  template: string;
  filter?: Record<string, unknown>;
}

/** Response from POST /v1/query. */
export interface QueryResponse {
  facts: Record<string, unknown>[];
}

/** Payload for DELETE /v1/facts. */
export interface RetractRequest {
  session_id: string;
  template: string;
  filter?: Record<string, unknown>;
}

/** Response from DELETE /v1/facts. */
export interface RetractResponse {
  retracted_count: number;
}

// ---------------------------------------------------------------------------
// Client options
// ---------------------------------------------------------------------------

/** Configuration for {@link FathomClient}. */
export interface FathomClientOptions {
  /** Base URL of the Fathom API server (e.g. "http://localhost:8000"). */
  baseURL: string;
  /** Optional headers sent with every request. */
  headers?: Record<string, string>;
  /**
   * Optional bearer token. When set, the client injects
   * `Authorization: Bearer <token>` on every request. Takes precedence
   * over any `Authorization` header supplied via {@link headers}.
   */
  bearerToken?: string;
}

// ---------------------------------------------------------------------------
// Error mapper
// ---------------------------------------------------------------------------

/**
 * Map an HTTP status code and response body to the appropriate {@link FathomError}
 * subclass.
 *
 * | Status        | Class              |
 * |---------------|--------------------|
 * | 403           | PolicyViolation    |
 * | 400, 422      | ValidationError    |
 * | ≥500 or 0     | ConnectionError    |
 * | anything else | FathomError (base) |
 *
 * Exported so that unit tests can exercise the mapping directly.
 */
export function mapErrorFromResponse(status: number, body: string): FathomError {
  if (status === 403) {
    return new PolicyViolation(status, body);
  }
  if (status === 400 || status === 422) {
    return new ValidationError(status, body);
  }
  if (status === 0 || status >= 500) {
    return new ConnectionError(status, body);
  }
  return new FathomError(status, body);
}

// ---------------------------------------------------------------------------
// FathomClient
// ---------------------------------------------------------------------------

/**
 * Promise-based client for the Fathom policy engine.
 *
 * @example
 * ```ts
 * const client = new FathomClient({
 *   baseURL: "http://localhost:8000",
 *   bearerToken: "my-token",
 * });
 * const result = await client.evaluate({
 *   ruleset: "",
 *   facts: [{ template: "agent", data: { id: "a1", clearance: "secret" } }],
 * });
 * console.log(result.decision); // "allow" | "deny" | "escalate" | null
 * ```
 */
export class FathomClient {
  private readonly baseURL: string;
  private readonly headers: Record<string, string>;

  constructor(options: FathomClientOptions) {
    // Strip trailing slash for consistent URL construction.
    this.baseURL = options.baseURL.replace(/\/+$/, "");
    this.headers = {
      "Content-Type": "application/json",
      ...options.headers,
    };
    if (options.bearerToken) {
      this.headers["Authorization"] = `Bearer ${options.bearerToken}`;
    }
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  /** Send facts to the engine and return the policy decision. */
  async evaluate(req: EvaluateRequest): Promise<EvaluateResponse> {
    return this.request<EvaluateResponse>("POST", "/v1/evaluate", req);
  }

  /** Assert a single fact into the session's working memory. */
  async assertFact(req: AssertFactRequest): Promise<AssertFactResponse> {
    return this.request<AssertFactResponse>("POST", "/v1/facts", req);
  }

  /** Retrieve facts from the session's working memory. */
  async query(req: QueryRequest): Promise<QueryResponse> {
    return this.request<QueryResponse>("POST", "/v1/query", req);
  }

  /**
   * Retract facts matching the request's template + optional filter from
   * the session's working memory. Returns the number of facts removed.
   */
  async retract(req: RetractRequest): Promise<RetractResponse> {
    return this.request<RetractResponse>("DELETE", "/v1/facts", req);
  }

  // -----------------------------------------------------------------------
  // Internal helpers
  // -----------------------------------------------------------------------

  private async request<T>(
    method: string,
    path: string,
    body: unknown,
  ): Promise<T> {
    const url = `${this.baseURL}${path}`;
    let resp: Response;
    try {
      resp = await fetch(url, {
        method,
        headers: this.headers,
        body: JSON.stringify(body),
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new ConnectionError(0, msg);
    }
    if (!resp.ok) {
      const text = await resp.text();
      throw mapErrorFromResponse(resp.status, text);
    }
    return (await resp.json()) as T;
  }
}
