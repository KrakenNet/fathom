[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / FathomClientOptions

# Interface: FathomClientOptions

Defined in: [client.ts:82](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L82)

Configuration for [FathomClient](../classes/FathomClient.md).

## Properties

### baseURL

> **baseURL**: `string`

Defined in: [client.ts:84](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L84)

Base URL of the Fathom API server (e.g. "http://localhost:8000").

***

### bearerToken?

> `optional` **bearerToken?**: `string`

Defined in: [client.ts:92](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L92)

Optional bearer token. When set, the client injects
`Authorization: Bearer <token>` on every request. Takes precedence
over any `Authorization` header supplied via [headers](#headers).

***

### headers?

> `optional` **headers?**: `Record`\<`string`, `string`\>

Defined in: [client.ts:86](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L86)

Optional headers sent with every request.
