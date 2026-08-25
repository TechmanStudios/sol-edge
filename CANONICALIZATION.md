# SOL-Edge Canonical JSON Profile 0.1

Foundation 0.1 uses a deliberately small canonical JSON profile rather than claiming full RFC 8785
conformance. The profile is deterministic across supported Python 3.11+ runtimes and is suitable
for contract and evidence identity.

## Semantic envelope

Every top-level contract includes `schema_name` and `schema_version`. Both fields are present in the
canonical bytes and therefore bound by its digest. The optional `annotations` envelope is explicitly
non-semantic and is the only top-level field omitted from semantic identity. Derived digest fields
(`decision_digest` and `reproducibility_digest`) are also omitted from the payload they identify to
avoid self-reference.

## Encoding rules

1. Encode as UTF-8 with no byte-order mark.
2. Sort object member names lexicographically by Unicode code point.
3. Preserve array order.
4. Emit no insignificant whitespace.
5. Encode strings with JSON escaping and reject non-string object keys.
6. Encode booleans and null with JSON literals.
7. Encode integers as base-10 JSON numbers with no leading zeros.
8. Encode every non-integer numeric measurement as a JSON string containing its normalized decimal
   form: no exponent, no trailing fractional zeroes, and negative zero becomes `"0"`.
9. Reject binary floating-point inputs, NaN, and infinity at validation and canonicalization
   boundaries.
10. Normalize timestamps to UTC RFC 3339 with `Z`; omit fractional seconds when zero and otherwise
    trim trailing fractional zeroes.

Digests use SHA-256 and the lowercase format `sha256:<64 hexadecimal characters>`. Python's
process-randomized `hash()` is never used. A digest is computed over the complete canonical semantic
envelope, so schema name, schema version, and semantic content are bound together.

