# dpp_recycle_vault (Sui Move, MVP)

Escrow vault keyed by the hash of an AP2 open Payment Mandate.
Payout to the recycler happens only when the ProductPassport is `Recycled`.

## Modules
- `passport`: `ProductPassport` (Registered -> Recycled). Only `OracleCap` holder can register / change status.
- `vault`: `Vault` (shared), `Escrow<T>` (stored under the 32-byte mandate hash), `VerifierCap`.
  - `deposit<T>`: sponsor locks coins under the hash (one escrow per hash).
  - `payout<T>`: needs `VerifierCap`. Re-checks: escrow exists, not settled, not expired,
    passport has the same dpp_id and is Recycled, recipient and amount equal the escrow.
  - `refund<T>`: sponsor can reclaim an unsettled escrow after expiry.
  - `separation`: authority-separation check (experimental, not yet connected to `vault`).
  A DPP becomes `Recycled` only if two independent ES256 (ECDSA P-256 / SHA-256) signatures verify on-chain:
  the mandate issuer signs the constraints (mandate id, DPP, recipient, amount, expiry), and the evaluator signs
  a `Verified` attestation bound to that mandate, that DPP and the evidence hash. `execute` rebuilds both
  signed messages from its own arguments, so changing any field invalidates the signature.
  Anyone may submit; authority comes only from the two signatures (no capability object).

## Trust assumptions (read this)
- AP2 mandate verification (signatures, constraints) is OFF-chain. `VerifierCap` holder is trusted
  to call `payout` only for authorizations that passed `ap2_fixed_case.py` style verification.
- `OracleCap` holder is trusted to mark products as recycled.
- Escrow expiry is chosen by the sponsor at deposit time; the verifier must check that it matches
  the mandate `exp` (seconds * 1000) before calling payout.
- Both caps are sent to the publisher address at publish time (MVP).
- `separation`: whoever calls `new_registry` chooses the two public keys (trust root). The code rejects an
  identical key in both roles, but cannot ensure that the two keys are held by different parties; that is an
  organisational condition. The package upgrade authority (`UpgradeCap`) can replace the verification logic.
- `separation` signs a fixed-format digest, not the AP2 SD-JWT itself. `dpp_id` uniqueness is not enforced.
  `Pending Review` (human review) is not modelled; only `Verified` / `Rejected`.

## Test (no network needed beyond dependency fetch)
    sui move build
    sui move test        # 31 tests (17 vault/passport + 14 separation)

### Authority-separation check
Test vectors (fresh keys and signatures) are generated into `tests/separation_tests.move`:

    python tools/gen_vectors.py      # needs: pip install cryptography
    sui move test separation         # 14 tests
    python tools/run_report.py       # prints PASS - ACCEPTED / PASS - REJECTED (error code) per test

A `PASS` on a test marked `expected_failure` means the call was rejected with the expected abort code.

## Publish to testnet
    sui client switch --env testnet
    sui client publish --gas-budget 200000000
Note the package id, the shared `Vault` object id, and the `OracleCap` / `VerifierCap` object ids.

## From AP2 output to Move arguments
    python tools/auth_to_sui_args.py inputs/authorization_for_sui.json
The recipient in the sample JSON is a dummy address. Put a real testnet address of a second
account in RECYCLER_REGISTRY inside ap2_fixed_case.py, re-run it, and copy the new JSON.

