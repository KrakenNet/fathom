/** Fathom REST API client */

const BASE = "/v1";

// --- Types ---

export interface Template {
  name: string;
  slots: Record<string, string>;
  module?: string;
  ttl_seconds?: number;
}

export interface Rule {
  name: string;
  module?: string;
  conditions: string[];
  action: string;
  salience?: number;
}

export interface Module {
  name: string;
  imports?: string[];
  exports?: string[];
}

export interface EvaluateRequest {
  facts: Record<string, unknown>[];
  rulesets?: string[];
}

export interface EvaluateResponse {
  results: Record<string, unknown>[];
  audit_log: Record<string, unknown>[];
}

export interface CompileRequest {
  yaml_content: string;
}

export interface CompileResponse {
  clips_code: string;
  constructs: string[];
}

// --- API functions ---

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    throw new Error(`API error: ${resp.status} ${resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

/** List all registered templates */
export async function listTemplates(): Promise<Template[]> {
  return fetchJSON<Template[]>(`${BASE}/templates`);
}

/** List all registered rules */
export async function listRules(): Promise<Rule[]> {
  return fetchJSON<Rule[]>(`${BASE}/rules`);
}

/** List all registered modules */
export async function listModules(): Promise<Module[]> {
  return fetchJSON<Module[]>(`${BASE}/modules`);
}

/** Evaluate facts against loaded rules */
export async function evaluate(
  request: EvaluateRequest
): Promise<EvaluateResponse> {
  return fetchJSON<EvaluateResponse>(`${BASE}/evaluate`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/** Compile YAML to CLIPS code */
export async function compile(
  request: CompileRequest
): Promise<CompileResponse> {
  return fetchJSON<CompileResponse>(`${BASE}/compile`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}
