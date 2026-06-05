[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / FathomClient

# Class: FathomClient

Defined in: [src/client.ts:145](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L145)

Promise-based client for the Fathom policy engine.

## Example

```ts
const client = new FathomClient({
  baseURL: "http://localhost:8000",
  bearerToken: "my-token",
});
const result = await client.evaluate({
  ruleset: "",
  facts: [{ template: "agent", data: { id: "a1", clearance: "secret" } }],
});
console.log(result.decision); // "allow" | "deny" | "escalate" | null
```

## Constructors

### Constructor

> **new FathomClient**(`options`): `FathomClient`

Defined in: [src/client.ts:149](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L149)

#### Parameters

##### options

[`FathomClientOptions`](../interfaces/FathomClientOptions.md)

#### Returns

`FathomClient`

## Methods

### assertFact()

> **assertFact**(`req`): `Promise`\<[`AssertFactResponse`](../interfaces/AssertFactResponse.md)\>

Defined in: [src/client.ts:171](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L171)

Assert a single fact into the session's working memory.

#### Parameters

##### req

[`AssertFactRequest`](../interfaces/AssertFactRequest.md)

#### Returns

`Promise`\<[`AssertFactResponse`](../interfaces/AssertFactResponse.md)\>

***

### evaluate()

> **evaluate**(`req`): `Promise`\<[`EvaluateResponse`](../interfaces/EvaluateResponse.md)\>

Defined in: [src/client.ts:166](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L166)

Send facts to the engine and return the policy decision.

#### Parameters

##### req

[`EvaluateRequest`](../interfaces/EvaluateRequest.md)

#### Returns

`Promise`\<[`EvaluateResponse`](../interfaces/EvaluateResponse.md)\>

***

### query()

> **query**(`req`): `Promise`\<[`QueryResponse`](../interfaces/QueryResponse.md)\>

Defined in: [src/client.ts:176](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L176)

Retrieve facts from the session's working memory.

#### Parameters

##### req

[`QueryRequest`](../interfaces/QueryRequest.md)

#### Returns

`Promise`\<[`QueryResponse`](../interfaces/QueryResponse.md)\>

***

### retract()

> **retract**(`req`): `Promise`\<[`RetractResponse`](../interfaces/RetractResponse.md)\>

Defined in: [src/client.ts:184](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L184)

Retract facts matching the request's template + optional filter from
the session's working memory. Returns the number of facts removed.

#### Parameters

##### req

[`RetractRequest`](../interfaces/RetractRequest.md)

#### Returns

`Promise`\<[`RetractResponse`](../interfaces/RetractResponse.md)\>
