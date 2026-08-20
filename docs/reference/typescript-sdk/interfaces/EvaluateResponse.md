[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / EvaluateResponse

# Interface: EvaluateResponse

Defined in: [client.ts:32](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L32)

Response from POST /v1/evaluate.

## Properties

### attestation\_token?

> `optional` **attestation\_token?**: `string` \| `null`

Defined in: [client.ts:40](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L40)

***

### decision

> **decision**: `string` \| `null`

Defined in: [client.ts:33](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L33)

***

### duration\_us

> **duration\_us**: `number`

Defined in: [client.ts:37](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L37)

***

### metadata

> **metadata**: `Record`\<`string`, `string`\>

Defined in: [client.ts:39](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L39)

`then.metadata` of the rule that decided; `{}` when it wrote none.

***

### module\_trace

> **module\_trace**: `string`[]

Defined in: [client.ts:36](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L36)

***

### reason

> **reason**: `string` \| `null`

Defined in: [client.ts:34](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L34)

***

### rule\_trace

> **rule\_trace**: `string`[]

Defined in: [client.ts:35](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L35)
