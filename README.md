There are some experimental. (preliminary research for my Master thesis)

A: This is a minimal experimental codebase connecting AP2 signed authorizations to a Sui Move escrow vault. 
It is a minimal implementation and is not intended for production use.

## Contents
ap2/ap2_fixed_case.py: Generation, signing, and verification of AP2 authorizations (open/closed mandates), along with negative test cases.

sui/dpp_recycle_vault/: Sui Move smart contracts (passport, vault) and unit tests (17 tests).

sui/dpp_recycle_vault/tools/auth_to_sui_args.py: Converts AP2 outputs into arguments which are compatible with functions in contracts with Sui Move.

sui/dpp_recycle_vault/sources/separation.move, tests/separation_tests.move, tools/gen_vectors.py, tools/run_report.py:
Two-key authority-separation check (experimental). Both the mandate issuer's and the evaluator's ES256 signatures must verify on-chain before a DPP status changes.

## Verified Environment
Windows, PowerShell 7.6.7

Python 3.13.2, AP2 Python SDK (Official repository google-agentic-commerce/AP2, commit <git rev-parse HEAD output>)

Sui CLI 1.82.1, Sui Testnet

## How we did
1. Cloned the official AP2 repository, installed it via `pip install -e .`, located ap2_fixed_case.py inside that folder, and executed it.

2. Run `sui move test` in sui/dpp_recycle_vault/ and verified that all 17 tests passed.

3. Published the contracts to Sui Testnet and verified deposits and withdrawals using AP2 outputs (such as open_payment_hash).

4. Generated test vectors with `python tools/gen_vectors.py`, ran `sui move test separation` in sui/dpp_recycle_vault/, and verified that all separation tests passed.

Also this is an another minimal check if a status change of any DPP cannot occur if only one of the two needed keys—constraint issuer’s key or evaluator’s key—is used when the two keys
differ from each other. 

## Contents

sui/dpp_recycle_vault/sources/separation.move: Implements the execution function that verifies both signatures before changing the state to Recycled.

sui/dpp_recycle_vault/tools/gen vectors.py: Generates two fresh keys and the corresponding signatures, then writes the test data.

sui/dpp_recycle_vault/tools/separation tests.template: Provides the test template, with signature values inserted during generation.

sui/dpp_recycle_vault/tests/separation tests.move: Automatically generated test data containing 14 tests.
sui/dpp_recycle_vault/tools/run report.py: Optionally displays test results in the PASS - REJECTED format.

## Verified Environment
Same as above.

## How we did

1. Created two keys and two test vectors in a Python script called `gen vectors.py` using the cryptography library. We saved the two keys and the two signatures to `tests/separation tests.move`.

2. Ran `separation.move` and could set the object state to `recycled` if both signatures were verified and valid. Also watched each test scenario if expected results showed.





