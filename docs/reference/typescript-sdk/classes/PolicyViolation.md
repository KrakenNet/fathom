[**@fathom-rules/sdk**](../index.md)

***

[@fathom-rules/sdk](../index.md) / PolicyViolation

# Class: PolicyViolation

Defined in: [errors.ts:48](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L48)

HTTP 403 — the policy engine denied the request.
The caller is authenticated but not permitted to perform the action.

## Extends

- [`FathomError`](FathomError.md)

## Constructors

### Constructor

> **new PolicyViolation**(`status`, `body`): `PolicyViolation`

Defined in: [errors.ts:49](https://github.com/KrakenNet/fathom/blob/master/packages/fathom-ts/src/errors.ts#L49)

#### Parameters

##### status

`number`

##### body

`string`

#### Returns

`PolicyViolation`

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
