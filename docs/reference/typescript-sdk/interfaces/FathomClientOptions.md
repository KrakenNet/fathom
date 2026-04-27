[**@fathom-rules/sdk**](../index.md) • **Docs**

***

[@fathom-rules/sdk](../index.md) / FathomClientOptions

# Interface: FathomClientOptions

Configuration for [FathomClient](../classes/FathomClient.md).

## Properties

### baseURL

> **baseURL**: `string`

Base URL of the Fathom API server (e.g. "http://localhost:8000").

#### Defined in

[src/client.ts:84](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L84)

***

### bearerToken?

> `optional` **bearerToken**: `string`

Optional bearer token. When set, the client injects
`Authorization: Bearer <token>` on every request. Takes precedence
over any `Authorization` header supplied via [headers](FathomClientOptions.md#headers).

#### Defined in

[src/client.ts:92](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L92)

***

### headers?

> `optional` **headers**: `Record`\<`string`, `string`\>

Optional headers sent with every request.

#### Defined in

[src/client.ts:86](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/client.ts#L86)
