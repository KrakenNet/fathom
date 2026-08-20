[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / FathomClient

# Class: FathomClient

Defined in: [client.ts:147](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L147)

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

Defined in: [client.ts:151](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L151)

#### Parameters

##### options

[`FathomClientOptions`](../interfaces/FathomClientOptions.md)

#### Returns

`FathomClient`

## Methods

### assertFact()

> **assertFact**(`req`): `Promise`\<[`AssertFactResponse`](../interfaces/AssertFactResponse.md)\>

Defined in: [client.ts:179](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L179)

Assert a single fact into the session's working memory.

#### Parameters

##### req

[`AssertFactRequest`](../interfaces/AssertFactRequest.md)

#### Returns

`Promise`\<[`AssertFactResponse`](../interfaces/AssertFactResponse.md)\>

***

### evaluate()

> **evaluate**(`req`): `Promise`\<[`EvaluateResponse`](../interfaces/EvaluateResponse.md)\>

Defined in: [client.ts:174](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L174)

Send facts to the engine and return the policy decision.

#### Parameters

##### req

[`EvaluateRequest`](../interfaces/EvaluateRequest.md)

#### Returns

`Promise`\<[`EvaluateResponse`](../interfaces/EvaluateResponse.md)\>

***

### query()

> **query**(`req`): `Promise`\<[`QueryResponse`](../interfaces/QueryResponse.md)\>

Defined in: [client.ts:184](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L184)

Retrieve facts from the session's working memory.

#### Parameters

##### req

[`QueryRequest`](../interfaces/QueryRequest.md)

#### Returns

`Promise`\<[`QueryResponse`](../interfaces/QueryResponse.md)\>

***

### retract()

> **retract**(`req`): `Promise`\<[`RetractResponse`](../interfaces/RetractResponse.md)\>

Defined in: [client.ts:192](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L192)

Retract facts matching the request's template + optional filter from
the session's working memory. Returns the number of facts removed.

#### Parameters

##### req

[`RetractRequest`](../interfaces/RetractRequest.md)

#### Returns

`Promise`\<[`RetractResponse`](../interfaces/RetractResponse.md)\>
