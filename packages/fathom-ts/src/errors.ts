/**
 * Fathom TypeScript SDK — typed error hierarchy.
 *
 * All errors thrown by {@link FathomClient} are instances of {@link FathomError}
 * or one of its typed subclasses. Callers can discriminate with `instanceof`:
 *
 * ```ts
 * try {
 *   await client.evaluate(req);
 * } catch (e) {
 *   if (e instanceof PolicyViolation) { ... } // HTTP 403
 *   if (e instanceof ValidationError)  { ... } // HTTP 400 / 422
 *   if (e instanceof ConnectionError)  { ... } // HTTP 5xx / network
 * }
 * ```
 *
 * @module
 */

// ---------------------------------------------------------------------------
// Base error
// ---------------------------------------------------------------------------

/**
 * Base error for all Fathom API failures.
 *
 * Contains the raw HTTP `status` code (0 for network/abort errors) and the
 * raw response `body` string for inspection.
 */
export class FathomError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: string,
  ) {
    super(`Fathom API error ${status}: ${body}`);
    this.name = "FathomError";
  }
}

// ---------------------------------------------------------------------------
// Typed subclasses
// ---------------------------------------------------------------------------

/**
 * HTTP 403 — the policy engine denied the request.
 * The caller is authenticated but not permitted to perform the action.
 */
export class PolicyViolation extends FathomError {
  constructor(status: number, body: string) {
    super(status, body);
    this.name = "PolicyViolation";
  }
}

/**
 * HTTP 400 or 422 — the request body failed validation.
 * The caller should inspect {@link FathomError.body} for details.
 */
export class ValidationError extends FathomError {
  constructor(status: number, body: string) {
    super(status, body);
    this.name = "ValidationError";
  }
}

/**
 * HTTP ≥500, HTTP 0, or fetch rejection (network error / DNS / abort).
 *
 * When constructed from a caught fetch rejection, `status` is set to 0 and
 * `body` contains the original error message.
 */
export class ConnectionError extends FathomError {
  constructor(status: number, body: string) {
    super(status, body);
    this.name = "ConnectionError";
  }
}
