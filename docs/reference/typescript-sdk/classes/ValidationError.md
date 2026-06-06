[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / ValidationError

# Class: ValidationError

Defined in: [errors.ts:59](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L59)

HTTP 400 or 422 — the request body failed validation.
The caller should inspect [FathomError.body](FathomError.md#body) for details.

## Extends

- [`FathomError`](FathomError.md)

## Constructors

### Constructor

> **new ValidationError**(`status`, `body`): `ValidationError`

Defined in: [errors.ts:60](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L60)

#### Parameters

##### status

`number`

##### body

`string`

#### Returns

`ValidationError`

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
