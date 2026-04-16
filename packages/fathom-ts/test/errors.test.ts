import { describe, it, expect } from "vitest";
import {
  FathomError,
  PolicyViolation,
  ValidationError,
  ConnectionError,
} from "../src/errors";
import { mapErrorFromResponse } from "../src/client";

// ---------------------------------------------------------------------------
// Hierarchy assertions
// ---------------------------------------------------------------------------

describe("error class hierarchy", () => {
  it("PolicyViolation is instanceof FathomError", () => {
    const err = new PolicyViolation(403, "forbidden");
    expect(err).toBeInstanceOf(FathomError);
    expect(err).toBeInstanceOf(PolicyViolation);
  });

  it("ValidationError is instanceof FathomError", () => {
    const err = new ValidationError(400, "bad input");
    expect(err).toBeInstanceOf(FathomError);
    expect(err).toBeInstanceOf(ValidationError);
  });

  it("ConnectionError is instanceof FathomError", () => {
    const err = new ConnectionError(500, "server error");
    expect(err).toBeInstanceOf(FathomError);
    expect(err).toBeInstanceOf(ConnectionError);
  });

  it("PolicyViolation has correct .name", () => {
    const err = new PolicyViolation(403, "forbidden");
    expect(err.name).toBe("PolicyViolation");
  });

  it("ValidationError has correct .name", () => {
    const err = new ValidationError(400, "bad input");
    expect(err.name).toBe("ValidationError");
  });

  it("ConnectionError has correct .name", () => {
    const err = new ConnectionError(500, "server error");
    expect(err.name).toBe("ConnectionError");
  });

  it("FathomError has correct .name", () => {
    const err = new FathomError(404, "not found");
    expect(err.name).toBe("FathomError");
  });

  it("PolicyViolation preserves message", () => {
    const err = new PolicyViolation(403, "access denied to resource");
    expect(err.message).toContain("403");
    expect(err.message).toContain("access denied to resource");
  });

  it("ValidationError preserves message", () => {
    const err = new ValidationError(422, "invalid field");
    expect(err.message).toContain("422");
    expect(err.message).toContain("invalid field");
  });

  it("ConnectionError preserves message when constructed with a plain string", () => {
    const err = new ConnectionError(0, "fetch failed");
    expect(err.message).toContain("fetch failed");
  });

  it("errors have a .stack trace", () => {
    const err = new PolicyViolation(403, "denied");
    expect(err.stack).toBeDefined();
    expect(typeof err.stack).toBe("string");
  });
});

// ---------------------------------------------------------------------------
// mapErrorFromResponse — status → class mapping
// ---------------------------------------------------------------------------

describe("mapErrorFromResponse", () => {
  it("maps 403 → PolicyViolation", () => {
    const err = mapErrorFromResponse(403, "forbidden");
    expect(err).toBeInstanceOf(PolicyViolation);
    expect(err.status).toBe(403);
  });

  it("maps 400 → ValidationError", () => {
    const err = mapErrorFromResponse(400, "bad request");
    expect(err).toBeInstanceOf(ValidationError);
    expect(err.status).toBe(400);
  });

  it("maps 422 → ValidationError", () => {
    const err = mapErrorFromResponse(422, "unprocessable");
    expect(err).toBeInstanceOf(ValidationError);
    expect(err.status).toBe(422);
  });

  it("maps 500 → ConnectionError", () => {
    const err = mapErrorFromResponse(500, "internal server error");
    expect(err).toBeInstanceOf(ConnectionError);
    expect(err.status).toBe(500);
  });

  it("maps 0 → ConnectionError", () => {
    const err = mapErrorFromResponse(0, "network error");
    expect(err).toBeInstanceOf(ConnectionError);
    expect(err.status).toBe(0);
  });

  it("maps 404 → generic FathomError (not a subclass)", () => {
    const err = mapErrorFromResponse(404, "not found");
    expect(err).toBeInstanceOf(FathomError);
    expect(err).not.toBeInstanceOf(PolicyViolation);
    expect(err).not.toBeInstanceOf(ValidationError);
    expect(err).not.toBeInstanceOf(ConnectionError);
    expect(err.status).toBe(404);
  });

  it("maps 502 → ConnectionError (5xx family)", () => {
    const err = mapErrorFromResponse(502, "bad gateway");
    expect(err).toBeInstanceOf(ConnectionError);
  });

  it("FathomError.body exposes the raw response body", () => {
    const err = mapErrorFromResponse(403, "{\"detail\":\"forbidden\"}");
    expect(err.body).toBe("{\"detail\":\"forbidden\"}");
  });
});
