import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { FathomClient, type FathomClientOptions } from "../src/client";
import {
  PolicyViolation,
  ValidationError,
  ConnectionError,
  FathomError,
} from "../src/errors";

// ---------------------------------------------------------------------------
// Fetch mocking helpers
// ---------------------------------------------------------------------------

interface CapturedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

function mockFetchOnce(
  status: number,
  body: unknown,
  calls: CapturedCall[],
): void {
  const impl = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    const payload =
      typeof body === "string" ? body : JSON.stringify(body);
    return new Response(payload, {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  vi.stubGlobal("fetch", vi.fn(impl));
}

function makeClient(overrides: Partial<FathomClientOptions> = {}): FathomClient {
  return new FathomClient({
    baseURL: "http://localhost:8000",
    ...overrides,
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// evaluate()
// ---------------------------------------------------------------------------

describe("FathomClient.evaluate", () => {
  it("sends the canonical EvaluateRequest shape", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(
      200,
      {
        decision: "allow",
        reason: null,
        rule_trace: ["r1"],
        module_trace: ["MAIN"],
        duration_us: 42,
        attestation_token: null,
      },
      calls,
    );

    const client = makeClient();
    const result = await client.evaluate({
      ruleset: "",
      facts: [{ template: "agent", data: { id: "a1", clearance: "secret" } }],
      session_id: "s1",
    });

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("http://localhost:8000/v1/evaluate");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toEqual({
      ruleset: "",
      facts: [{ template: "agent", data: { id: "a1", clearance: "secret" } }],
      session_id: "s1",
    });
    expect(result.decision).toBe("allow");
    expect(result.module_trace).toEqual(["MAIN"]);
  });

  it("injects Authorization header when bearerToken is set", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(
      200,
      {
        decision: null,
        reason: null,
        rule_trace: [],
        module_trace: [],
        duration_us: 0,
      },
      calls,
    );

    const client = makeClient({ bearerToken: "secret-token" });
    await client.evaluate({ ruleset: "", facts: [] });

    expect(calls[0].headers["Authorization"]).toBe("Bearer secret-token");
  });

  it("does not set Authorization when bearerToken is absent", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(
      200,
      {
        decision: null,
        reason: null,
        rule_trace: [],
        module_trace: [],
        duration_us: 0,
      },
      calls,
    );

    const client = makeClient();
    await client.evaluate({ ruleset: "", facts: [] });

    expect(calls[0].headers["Authorization"]).toBeUndefined();
  });

  it("maps 403 to PolicyViolation", async () => {
    mockFetchOnce(403, "forbidden", []);
    const client = makeClient();
    await expect(
      client.evaluate({ ruleset: "", facts: [] }),
    ).rejects.toBeInstanceOf(PolicyViolation);
  });

  it("maps 422 to ValidationError", async () => {
    mockFetchOnce(422, "bad input", []);
    const client = makeClient();
    await expect(
      client.evaluate({ ruleset: "", facts: [] }),
    ).rejects.toBeInstanceOf(ValidationError);
  });

  it("wraps network errors as ConnectionError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    const client = makeClient();
    await expect(
      client.evaluate({ ruleset: "", facts: [] }),
    ).rejects.toBeInstanceOf(ConnectionError);
  });
});

// ---------------------------------------------------------------------------
// assertFact()
// ---------------------------------------------------------------------------

describe("FathomClient.assertFact", () => {
  it("POSTs to /v1/facts with {session_id, template, data}", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(200, { success: true }, calls);

    const client = makeClient({ bearerToken: "t" });
    const result = await client.assertFact({
      session_id: "s1",
      template: "agent",
      data: { id: "a1", clearance: "secret" },
    });

    expect(calls[0].url).toBe("http://localhost:8000/v1/facts");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toEqual({
      session_id: "s1",
      template: "agent",
      data: { id: "a1", clearance: "secret" },
    });
    expect(result.success).toBe(true);
  });

  it("maps 404 to FathomError", async () => {
    mockFetchOnce(404, "session not found", []);
    const client = makeClient();
    await expect(
      client.assertFact({ session_id: "x", template: "agent", data: {} }),
    ).rejects.toBeInstanceOf(FathomError);
  });
});

// ---------------------------------------------------------------------------
// query()
// ---------------------------------------------------------------------------

describe("FathomClient.query", () => {
  it("POSTs to /v1/query and returns facts", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(
      200,
      { facts: [{ id: "a1", clearance: "secret" }] },
      calls,
    );

    const client = makeClient();
    const result = await client.query({
      session_id: "s1",
      template: "agent",
      filter: { id: "a1" },
    });

    expect(calls[0].url).toBe("http://localhost:8000/v1/query");
    expect(calls[0].body).toEqual({
      session_id: "s1",
      template: "agent",
      filter: { id: "a1" },
    });
    expect(result.facts).toHaveLength(1);
  });

  it("omits filter when not provided", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(200, { facts: [] }, calls);

    const client = makeClient();
    await client.query({ session_id: "s1", template: "agent" });

    expect(calls[0].body).toEqual({ session_id: "s1", template: "agent" });
  });
});

// ---------------------------------------------------------------------------
// retract()
// ---------------------------------------------------------------------------

describe("FathomClient.retract", () => {
  it("sends DELETE /v1/facts with {session_id, template, filter?} and returns count", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(200, { retracted_count: 2 }, calls);

    const client = makeClient();
    const result = await client.retract({
      session_id: "s1",
      template: "agent",
    });

    expect(calls[0].method).toBe("DELETE");
    expect(calls[0].url).toBe("http://localhost:8000/v1/facts");
    expect(calls[0].body).toEqual({ session_id: "s1", template: "agent" });
    expect(result.retracted_count).toBe(2);
  });

  it("passes filter through when provided", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(200, { retracted_count: 1 }, calls);

    const client = makeClient();
    await client.retract({
      session_id: "s1",
      template: "agent",
      filter: { id: "a1" },
    });

    expect(calls[0].body).toEqual({
      session_id: "s1",
      template: "agent",
      filter: { id: "a1" },
    });
  });
});

// ---------------------------------------------------------------------------
// URL / header handling
// ---------------------------------------------------------------------------

describe("FathomClient construction", () => {
  it("strips trailing slashes on baseURL", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(200, { facts: [] }, calls);

    const client = new FathomClient({
      baseURL: "http://localhost:8000///",
    });
    await client.query({ session_id: "s", template: "t" });

    expect(calls[0].url).toBe("http://localhost:8000/v1/query");
  });

  it("merges custom headers with defaults", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(200, { facts: [] }, calls);

    const client = new FathomClient({
      baseURL: "http://localhost:8000",
      headers: { "X-Trace-Id": "abc" },
    });
    await client.query({ session_id: "s", template: "t" });

    expect(calls[0].headers["X-Trace-Id"]).toBe("abc");
    expect(calls[0].headers["Content-Type"]).toBe("application/json");
  });

  it("bearerToken overrides Authorization header from options.headers", async () => {
    const calls: CapturedCall[] = [];
    mockFetchOnce(200, { facts: [] }, calls);

    const client = new FathomClient({
      baseURL: "http://localhost:8000",
      headers: { Authorization: "Bearer old" },
      bearerToken: "new",
    });
    await client.query({ session_id: "s", template: "t" });

    expect(calls[0].headers["Authorization"]).toBe("Bearer new");
  });
});
