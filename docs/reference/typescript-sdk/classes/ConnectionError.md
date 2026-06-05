[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / ConnectionError

# Class: ConnectionError

Defined in: [errors.ts:72](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L72)

HTTP ≥500, HTTP 0, or fetch rejection (network error / DNS / abort).

When constructed from a caught fetch rejection, `status` is set to 0 and
`body` contains the original error message.

## Extends

- [`FathomError`](FathomError.md)

## Constructors

### Constructor

> **new ConnectionError**(`status`, `body`): `ConnectionError`

Defined in: [errors.ts:73](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L73)

#### Parameters

##### status

`number`

##### body

`string`

#### Returns

`ConnectionError`

#### Overrides

[`FathomError`](FathomError.md).[`constructor`](FathomError.md#constructor)

## Properties

### body

> `readonly` **body**: `string`

Defined in: [errors.ts:33](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L33)

#### Inherited from

[`FathomError`](FathomError.md).[`body`](FathomError.md#body)

***

### status

> `readonly` **status**: `number`

Defined in: [errors.ts:32](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L32)

#### Inherited from

[`FathomError`](FathomError.md).[`status`](FathomError.md#status)
