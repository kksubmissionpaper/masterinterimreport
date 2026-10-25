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

## Trust assumptions (read this)
- AP2 mandate verification (signatures, constraints) is OFF-chain. `VerifierCap` holder is trusted
  to call `payout` only for authorizations that passed `ap2_fixed_case.py` style verification.
- `OracleCap` holder is trusted to mark products as recycled.
- Escrow expiry is chosen by the sponsor at deposit time; the verifier must check that it matches
  the mandate `exp` (seconds * 1000) before calling payout.
- Both caps are sent to the publisher address at publish time (MVP).

## Test (no network needed beyond dependency fetch)
    sui move build
    sui move test        # 17 tests

## Publish to testnet
    sui client switch --env testnet
    sui client publish --gas-budget 200000000
Note the package id, the shared `Vault` object id, and the `OracleCap` / `VerifierCap` object ids.

## From AP2 output to Move arguments
    python tools/auth_to_sui_args.py inputs/authorization_for_sui.json
The recipient in the sample JSON is a dummy address. Put a real testnet address of a second
account in RECYCLER_REGISTRY inside ap2_fixed_case.py, re-run it, and copy the new JSON.
