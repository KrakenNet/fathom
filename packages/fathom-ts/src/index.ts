/**
 * Fathom TypeScript SDK — public API barrel export.
 *
 * @module @fathom-rules/sdk
 */

export {
  FathomClient,
  type FathomClientOptions,
  type FactInput,
  type EvaluateRequest,
  type EvaluateResponse,
  type AssertFactRequest,
  type AssertFactResponse,
  type QueryRequest,
  type QueryResponse,
  type RetractRequest,
  type RetractResponse,
} from "./client";

export {
  FathomError,
  PolicyViolation,
  ValidationError,
  ConnectionError,
} from "./errors";
