[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / FathomError

# Class: FathomError

Defined in: [errors.ts:30](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L30)

Base error for all Fathom API failures.

Contains the raw HTTP `status` code (0 for network/abort errors) and the
raw response `body` string for inspection.

## Extends

- `Error`

## Extended by

- [`PolicyViolation`](PolicyViolation.md)
- [`ValidationError`](ValidationError.md)
- [`ConnectionError`](ConnectionError.md)

## Constructors

### Constructor

> **new FathomError**(`status`, `body`): `FathomError`

Defined in: [errors.ts:31](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L31)

#### Parameters

##### status

`number`

##### body

`string`

#### Returns

`FathomError`

#### Overrides

`Error.constructor`

## Properties

### body

> `readonly` **body**: `string`

Defined in: [errors.ts:33](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L33)

***

### status

> `readonly` **status**: `number`

Defined in: [errors.ts:32](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L32)
