# SOL-Edge Foundation 0.1

SOL-Edge Foundation 0.1 defines versioned, immutable contracts and deterministic evidence identity
for human-governed edge experiments. It stops at the eligibility boundary: it does not operate a
device, call a model, issue approval credentials, sign decisions, or maintain a durable ledger.

## Authority boundaries

- A proposer (human, AI system, or deterministic system) may produce an `ActionProposal`.
- Policy evaluates declared facts and evidence and produces a `PolicyDecision`.
- `ELIGIBLE` means only that a proposal may advance to release review.
- A separate, named operator or release authority must approve consequential physical execution.
- No policy result in this package is an operator approval, authorization token, or signature.

The five policy outcomes are `ELIGIBLE`, `REQUIRE_HUMAN_APPROVAL`, `DEFER`, `QUARANTINE`, and
`REJECT`. There is intentionally no `AUTHORIZED` outcome.

An LLM is optional and untrusted. Human-readable rationale is evidence-bearing proposal content, but
policy must evaluate typed fields and observable evidence rather than hidden chain-of-thought. Profit
Router integration is outside this kernel.

## Contracts

- `CapabilityManifest`: device capabilities, units, ranges, fail-safe behavior, readback, timing, and
  approval requirements.
- `ExperimentPlan`: ordered steps, preconditions, observations, invariants, timeouts, compensation,
  and evidence requirements.
- `ActionProposal`: proposed command, typed actor, bound plan/manifest/input state, validated
  parameters, execution window, rationale, and readback expectations.
- `EvidencePacket`: bound inputs, simulation or dry-run provenance, observations, invariant results,
  artifacts, and reproducibility identity.
- `PolicyDecision`: one of the five non-authorizing statuses, reasons, unmet requirements, and a
  constrained next transition.

All contracts reject unknown fields, normalize UTC timestamps, reject binary floats, and are frozen
after validation. Pydantic `ValidationError` values can be projected through `structured_errors()`
to stable path/code/message records without leaking raw model-like input. See
[CANONICALIZATION.md](CANONICALIZATION.md) for the semantic identity rules.

## Development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy src
.venv\Scripts\python -m sol_edge eligible
```

The last command prints the canonical semantic representation and SHA-256 digest of the deterministic
eligible fixture. No command in Foundation 0.1 performs physical action.
