# Protocol Documentation
<a name="top"></a>

## Table of Contents

- [fathom.proto](#fathom-proto)
    - [AssertFactRequest](#fathom-v1-AssertFactRequest)
    - [AssertFactResponse](#fathom-v1-AssertFactResponse)
    - [EvaluateRequest](#fathom-v1-EvaluateRequest)
    - [EvaluateResponse](#fathom-v1-EvaluateResponse)
    - [FactChange](#fathom-v1-FactChange)
    - [FactInput](#fathom-v1-FactInput)
    - [QueryRequest](#fathom-v1-QueryRequest)
    - [QueryResponse](#fathom-v1-QueryResponse)
    - [RetractRequest](#fathom-v1-RetractRequest)
    - [RetractResponse](#fathom-v1-RetractResponse)
    - [SubscribeRequest](#fathom-v1-SubscribeRequest)
  
    - [ChangeType](#fathom-v1-ChangeType)
  
    - [FathomService](#fathom-v1-FathomService)
  
- [Scalar Value Types](#scalar-value-types)



<a name="fathom-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## fathom.proto



<a name="fathom-v1-AssertFactRequest"></a>

### AssertFactRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| session_id | [string](#string) |  |  |
| template | [string](#string) |  |  |
| data_json | [string](#string) |  | JSON-encoded slot data. |






<a name="fathom-v1-AssertFactResponse"></a>

### AssertFactResponse



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| success | [bool](#bool) |  |  |






<a name="fathom-v1-EvaluateRequest"></a>

### EvaluateRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| session_id | [string](#string) |  |  |
| ruleset | [string](#string) |  |  |
| facts | [FactInput](#fathom-v1-FactInput) | repeated |  |






<a name="fathom-v1-EvaluateResponse"></a>

### EvaluateResponse



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| decision | [string](#string) |  |  |
| reason | [string](#string) |  |  |
| rule_trace | [string](#string) | repeated |  |
| module_trace | [string](#string) | repeated |  |
| duration_us | [int64](#int64) |  |  |






<a name="fathom-v1-FactChange"></a>

### FactChange



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| change_type | [ChangeType](#fathom-v1-ChangeType) |  |  |
| template | [string](#string) |  |  |
| data_json | [string](#string) |  | JSON-encoded slot data of the changed fact. |






<a name="fathom-v1-FactInput"></a>

### FactInput



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| template | [string](#string) |  |  |
| data_json | [string](#string) |  | JSON-encoded slot data (e.g. {&#34;tool_name&#34;: &#34;bash&#34;, &#34;agent_id&#34;: &#34;a1&#34;}). |






<a name="fathom-v1-QueryRequest"></a>

### QueryRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| session_id | [string](#string) |  |  |
| template | [string](#string) |  |  |
| filter_json | [string](#string) |  | Optional JSON-encoded filter (e.g. {&#34;agent_id&#34;: &#34;a1&#34;}). |






<a name="fathom-v1-QueryResponse"></a>

### QueryResponse



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| facts_json | [string](#string) | repeated | Each entry is a JSON-encoded dict representing one fact. |






<a name="fathom-v1-RetractRequest"></a>

### RetractRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| session_id | [string](#string) |  |  |
| template | [string](#string) |  |  |
| filter_json | [string](#string) |  | Optional JSON-encoded filter. |






<a name="fathom-v1-RetractResponse"></a>

### RetractResponse



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| retracted_count | [int32](#int32) |  |  |






<a name="fathom-v1-SubscribeRequest"></a>

### SubscribeRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| session_id | [string](#string) |  |  |





 


<a name="fathom-v1-ChangeType"></a>

### ChangeType


| Name | Number | Description |
| ---- | ------ | ----------- |
| CHANGE_TYPE_UNSPECIFIED | 0 |  |
| ASSERT | 1 |  |
| RETRACT | 2 |  |


 

 


<a name="fathom-v1-FathomService"></a>

### FathomService


| Method Name | Request Type | Response Type | Description |
| ----------- | ------------ | ------------- | ------------|
| Evaluate | [EvaluateRequest](#fathom-v1-EvaluateRequest) | [EvaluateResponse](#fathom-v1-EvaluateResponse) | Evaluate asserted facts against loaded rules and return a decision. |
| AssertFact | [AssertFactRequest](#fathom-v1-AssertFactRequest) | [AssertFactResponse](#fathom-v1-AssertFactResponse) | Assert one or more facts into working memory. |
| Query | [QueryRequest](#fathom-v1-QueryRequest) | [QueryResponse](#fathom-v1-QueryResponse) | Query working memory for facts matching a template and optional filter. |
| Retract | [RetractRequest](#fathom-v1-RetractRequest) | [RetractResponse](#fathom-v1-RetractResponse) | Retract facts matching a template and optional filter. |
| SubscribeChanges | [SubscribeRequest](#fathom-v1-SubscribeRequest) | [FactChange](#fathom-v1-FactChange) stream | Stream working-memory changes as they occur during evaluation. |

 



## Scalar Value Types

| .proto Type | Notes | C++ | Java | Python | Go | C# | PHP | Ruby |
| ----------- | ----- | --- | ---- | ------ | -- | -- | --- | ---- |
| <a name="double" /> double |  | double | double | float | float64 | double | float | Float |
| <a name="float" /> float |  | float | float | float | float32 | float | float | Float |
| <a name="int32" /> int32 | Uses variable-length encoding. Inefficient for encoding negative numbers – if your field is likely to have negative values, use sint32 instead. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="int64" /> int64 | Uses variable-length encoding. Inefficient for encoding negative numbers – if your field is likely to have negative values, use sint64 instead. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="uint32" /> uint32 | Uses variable-length encoding. | uint32 | int | int/long | uint32 | uint | integer | Bignum or Fixnum (as required) |
| <a name="uint64" /> uint64 | Uses variable-length encoding. | uint64 | long | int/long | uint64 | ulong | integer/string | Bignum or Fixnum (as required) |
| <a name="sint32" /> sint32 | Uses variable-length encoding. Signed int value. These more efficiently encode negative numbers than regular int32s. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="sint64" /> sint64 | Uses variable-length encoding. Signed int value. These more efficiently encode negative numbers than regular int64s. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="fixed32" /> fixed32 | Always four bytes. More efficient than uint32 if values are often greater than 2^28. | uint32 | int | int | uint32 | uint | integer | Bignum or Fixnum (as required) |
| <a name="fixed64" /> fixed64 | Always eight bytes. More efficient than uint64 if values are often greater than 2^56. | uint64 | long | int/long | uint64 | ulong | integer/string | Bignum |
| <a name="sfixed32" /> sfixed32 | Always four bytes. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="sfixed64" /> sfixed64 | Always eight bytes. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="bool" /> bool |  | bool | boolean | boolean | bool | bool | boolean | TrueClass/FalseClass |
| <a name="string" /> string | A string must always contain UTF-8 encoded or 7-bit ASCII text. | string | String | str/unicode | string | string | string | String (UTF-8) |
| <a name="bytes" /> bytes | May contain any arbitrary sequence of bytes. | string | ByteString | str | []byte | ByteString | string | String (ASCII-8BIT) |

