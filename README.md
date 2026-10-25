This is a minimal experimental codebase connecting AP2 signed authorizations to a Sui Move escrow vault. (preliminary research for my Master thesis)
It is a minimal implementation and is not intended for production use.

## Contents
ap2/ap2_fixed_case.py: Generation, signing, and verification of AP2 authorizations (open/closed mandates), along with negative test cases.

sui/dpp_recycle_vault/: Sui Move smart contracts (passport, vault) and unit tests (17 tests).

sui/dpp_recycle_vault/tools/auth_to_sui_args.py: Converts AP2 outputs into arguments which are compatible with functions in contracts with Sui Move.

## Verified Environment
Windows, PowerShell 7.6.7

Python 3.13.2, AP2 Python SDK (Official repository google-agentic-commerce/AP2, commit <git rev-parse HEAD output>)

Sui CLI 1.82.1, Sui Testnet

## How we did
1. Cloned the official AP2 repository, installed it via `pip install -e .`, located ap2_fixed_case.py inside that folder, and executed it.

2. Run `sui move test` in sui/dpp_recycle_vault/ and verified that all 17 tests passed.

3. Published the contracts to Sui Testnet and verified deposits and withdrawals using AP2 outputs (such as open_payment_hash).
