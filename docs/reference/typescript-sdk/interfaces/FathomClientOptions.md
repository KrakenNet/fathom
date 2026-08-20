[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / FathomClientOptions

# Interface: FathomClientOptions

Defined in: [client.ts:84](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L84)

Configuration for [FathomClient](../classes/FathomClient.md).

## Properties

### baseURL

> **baseURL**: `string`

Defined in: [client.ts:86](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L86)

Base URL of the Fathom API server (e.g. "http://localhost:8000").

***

### bearerToken?

> `optional` **bearerToken?**: `string`

Defined in: [client.ts:94](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L94)

Optional bearer token. When set, the client injects
`Authorization: Bearer <token>` on every request. Takes precedence
over any `Authorization` header supplied via [headers](#headers).

***

### headers?

> `optional` **headers?**: `Record`\<`string`, `string`\>

Defined in: [client.ts:88](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L88)

Optional headers sent with every request.
