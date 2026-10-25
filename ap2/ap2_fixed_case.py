"""AP2 fixed-case check: one recycling application, no LLM, no UI, no chain.

Flow
  1. Sponsor signs open Checkout + open Payment mandates (AP2 v0.2 SDK).
  2. Recycler (merchant) signs a checkout_jwt for ONE product (DPP id).
  3. Agent (an agent for a sponsor) signs closed Checkout + closed Payment mandates.
  4. A verifier (the future "Sui side") verifies the chain and emits a
     normalized authorization for the Sui Vault.
  5. Negative tests: tamper payee / amount / expiry / reuse / etc.

Run (from the AP2 repo root, venv with `pip install -e .`):
    python ap2_fixed_case.py

Output files go to ./out_fixed_case/ . All output text is ASCII on purpose
(Windows consoles with cp932 break on some Unicode).
"""

from __future__ import annotations

import json
import sys
import time

from pathlib import Path

from ap2.sdk.checkout_mandate_chain import CheckoutMandateChain
from ap2.sdk.generated.checkout_mandate import CheckoutMandate
from ap2.sdk.generated.open_checkout_mandate import (
    AllowedMerchants,
    LineItemRequirements,
    LineItems,
    OpenCheckoutMandate,
)
from ap2.sdk.generated.open_checkout_mandate import Item as MandateItem
from ap2.sdk.generated.open_payment_mandate import (
    AllowedPayees,
    AllowedPaymentInstruments,
    AmountRange,
    OpenPaymentMandate,
    PaymentReference,
)
from ap2.sdk.generated.payment_mandate import PaymentMandate
from ap2.sdk.generated.types.amount import Amount
from ap2.sdk.generated.types.checkout import Checkout, Status
from ap2.sdk.generated.types.item import Item
from ap2.sdk.generated.types.line_item import LineItem
from ap2.sdk.generated.types.link import Link
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument
from ap2.sdk.generated.types.total import Total
from ap2.sdk.mandate import MandateClient
from ap2.sdk.payment_mandate_chain import PaymentMandateChain
from ap2.sdk.sdjwt.common import compute_sd_hash, parse_token
from ap2.sdk.utils import compute_sha256_b64url
from cryptography.hazmat.primitives.asymmetric import ec
from jwcrypto import jws
from jwcrypto.jwk import JWK


try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:  # noqa: BLE001
    pass

OUT = Path('out_fixed_case')
OUT.mkdir(exist_ok=True)

# --------------------------------------------------------------------------
# Fixed application data  (edit here)
# --------------------------------------------------------------------------
DPP_ID = 'dpp_0001'
DPP_TITLE = 'Recycling of product dpp_0001'
AMOUNT_MINOR = 2000            # USD cents -> 20.00 USD
# Note: authorize in USD minor units (cents, ISO 4217) and settle
# in Sui USDC at a fixed 1:1 (see USDC_BASE_UNITS_PER_MINOR below).
# The settlement asset is declared in RAIL (type='sui-usdc'), not in CURRENCY.
# The SDK also accepts CURRENCY='USDC' (tested), but it is not an ISO 4217 code.
CURRENCY = 'USD'
TTL_SECONDS = 24 * 3600
SPONSOR_ID = 'sponsor_001'

RECYCLER = Merchant(
    id='recycler_001',
    name='Demo Recycler',
    website='https://recycler.example',
)
# Sui address is NOT carried by the AP2 mandate (the SDK model has no field
# for it). It is resolved from a trusted registry keyed by merchant id.
RECYCLER_REGISTRY = {'recycler_001': '0x45fd4e4ad964cf405581b62f71cd537c715eb2f75548d30e94f8bdff029fa09b'}
USDC_BASE_UNITS_PER_MINOR = 10_000   # cents -> 6-decimal USDC (1 USD = 1 USDC)

RAIL = PaymentInstrument(
    id='sui-testnet-usdc',
    type='sui-usdc',
    description='Sui testnet USDC vault',
)

AUD_CHECKOUT = 'merchant'
AUD_PAYMENT = 'credential-provider'
NONCE_CHECKOUT = 'nonce-checkout-0001'
NONCE_PAYMENT = 'nonce-payment-0001'


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def new_key(kid: str) -> JWK:
    key = JWK.from_pyca(ec.generate_private_key(ec.SECP256R1()))
    d = json.loads(key.export())
    d['kid'] = kid
    return JWK.from_json(json.dumps(d))


def pub(key: JWK) -> JWK:
    return JWK.from_json(key.export_public())


def cnf_of(key: JWK) -> dict:
    return {'jwk': json.loads(key.export_public())}


def sign_checkout_jwt(merchant_key: JWK, checkout: Checkout) -> str:
    payload = checkout.model_dump_json(exclude_none=True)
    token = jws.JWS(payload.encode())
    token.add_signature(
        merchant_key,
        alg='ES256',
        protected=json.dumps({'alg': 'ES256', 'kid': merchant_key.get('kid')}),
    )
    return token.serialize(compact=True)


def verify_merchant_signature(checkout_jwt: str, merchant_pub: JWK) -> None:
    token = jws.JWS()
    token.deserialize(checkout_jwt)
    token.verify(merchant_pub, alg='ES256')


def make_checkout(dpp_id: str, amount_minor: int, merchant: Merchant) -> Checkout:
    li = LineItem(
        id=f'li_{dpp_id}',
        item=Item(id=dpp_id, title=DPP_TITLE, price=amount_minor),
        quantity=1,
        totals=[
            Total(type='subtotal', amount=amount_minor),
            Total(type='total', amount=amount_minor),
        ],
    )
    return Checkout(
        id='chk_' + dpp_id,
        merchant=merchant,
        line_items=[li],
        status=Status.incomplete,
        currency=CURRENCY,
        totals=[
            Total(type='subtotal', amount=amount_minor),
            Total(type='total', amount=amount_minor),
        ],
        links=[
            Link(type='privacy_policy', url='https://recycler.example/privacy'),
            Link(type='terms_of_service', url='https://recycler.example/tos'),
        ],
    )


# --------------------------------------------------------------------------
# Issuing side
# --------------------------------------------------------------------------
class Actors:
    def __init__(self) -> None:
        self.sponsor = new_key('sponsor-1')
        self.agent = new_key('agent-1')
        self.recycler = new_key('recycler-1')
        self.client = MandateClient()


def issue_open_mandates(a: Actors, now: int) -> dict:
    open_checkout = a.client.create(
        payloads=[
            OpenCheckoutMandate(
                constraints=[
                    LineItems(
                        items=[
                            LineItemRequirements(
                                id='req-1',
                                acceptable_items=[
                                    MandateItem(id=DPP_ID, title=DPP_TITLE)
                                ],
                                quantity=1,
                            )
                        ]
                    ),
                    AllowedMerchants(allowed=[RECYCLER]),
                ],
                cnf=cnf_of(a.agent),
                iat=now,
                exp=now + TTL_SECONDS,
            )
        ],
        issuer_key=a.sponsor,
    )
    open_checkout_hash = compute_sd_hash(parse_token(open_checkout))
    open_payment = a.client.create(
        payloads=[
            OpenPaymentMandate(
                constraints=[
                    AmountRange(
                        currency=CURRENCY, min=AMOUNT_MINOR, max=AMOUNT_MINOR
                    ),
                    AllowedPayees(allowed=[RECYCLER]),
                    AllowedPaymentInstruments(allowed=[RAIL]),
                    PaymentReference(conditional_transaction_id=open_checkout_hash),
                ],
                cnf=cnf_of(a.agent),
                iat=now,
                exp=now + TTL_SECONDS,
            )
        ],
        issuer_key=a.sponsor,
    )
    return {
        'open_checkout': open_checkout,
        'open_payment': open_payment,
        'open_checkout_hash': open_checkout_hash,
        'open_payment_hash': compute_sd_hash(parse_token(open_payment)),
    }


def issue_checkout_jwt(a: Actors, dpp_id: str = DPP_ID,
                       amount_minor: int = AMOUNT_MINOR) -> tuple[str, str]:
    jwt_ = sign_checkout_jwt(a.recycler, make_checkout(dpp_id, amount_minor, RECYCLER))
    return jwt_, compute_sha256_b64url(jwt_)


def agent_present(a: Actors, opens: dict, checkout_jwt: str, checkout_hash: str,
                  *, agent_key: JWK | None = None,
                  payee: Merchant = RECYCLER,
                  amount_minor: int = AMOUNT_MINOR,
                  transaction_id: str | None = None,
                  aud_checkout: str = AUD_CHECKOUT,
                  aud_payment: str = AUD_PAYMENT,
                  nonce_checkout: str = NONCE_CHECKOUT,
                  nonce_payment: str = NONCE_PAYMENT) -> dict:
    holder = agent_key or a.agent
    chk_chain = a.client.present(
        holder_key=holder,
        mandate_token=opens['open_checkout'],
        payloads=[CheckoutMandate(checkout_jwt=checkout_jwt,
                                  checkout_hash=checkout_hash)],
        aud=aud_checkout,
        nonce=nonce_checkout,
    )
    pay_chain = a.client.present(
        holder_key=holder,
        mandate_token=opens['open_payment'],
        payloads=[PaymentMandate(
            transaction_id=transaction_id or checkout_hash,
            payee=payee,
            payment_amount=Amount(amount=amount_minor, currency=CURRENCY),
            payment_instrument=RAIL,
        )],
        aud=aud_payment,
        nonce=nonce_payment,
    )
    return {
        'checkout_chain': chk_chain,
        'payment_chain': pay_chain,
        'checkout_jwt': checkout_jwt,
        'checkout_hash': checkout_hash,
        'open_checkout_hash': opens['open_checkout_hash'],
        'open_payment_hash': opens['open_payment_hash'],
    }


# --------------------------------------------------------------------------
# Verifier (the future Sui-side service)
# --------------------------------------------------------------------------
class Rejected(Exception):
    pass


class Verifier:
    def __init__(self, sponsor_pub: JWK, merchant_pubs: dict[str, JWK]) -> None:
        self.sponsor_pub = sponsor_pub
        self.merchant_pubs = merchant_pubs
        self.consumed: set[str] = set()   # stand-in for the on-chain marker
        self.client = MandateClient()

    def verify(self, b: dict, now: int | None = None) -> dict:
        t = now if now is not None else int(time.time())
        provider = lambda _tok: self.sponsor_pub  # noqa: E731

        try:
            chk_payloads = self.client.verify(
                token=b['checkout_chain'], key_or_provider=provider,
                expected_aud=AUD_CHECKOUT, expected_nonce=NONCE_CHECKOUT,
                current_time=t)
            pay_payloads = self.client.verify(
                token=b['payment_chain'], key_or_provider=provider,
                expected_aud=AUD_PAYMENT, expected_nonce=NONCE_PAYMENT,
                current_time=t)
        except Exception as e:  # noqa: BLE001
            raise Rejected(f'chain verification: {type(e).__name__}: {e}') from e

        chk = CheckoutMandateChain.parse(chk_payloads)
        pay = PaymentMandateChain.parse(pay_payloads)

        problems: list[str] = []
        problems += chk.verify(
            expected_checkout_hash=b['checkout_hash'],
            checkout_jwt=b['checkout_jwt'])
        problems += pay.verify(
            expected_transaction_id=b['checkout_hash'],
            expected_open_checkout_hash=b['open_checkout_hash'])

        # checkout_jwt integrity + merchant signature + hash binding
        if compute_sha256_b64url(b['checkout_jwt']) != b['checkout_hash']:
            problems.append('checkout_jwt does not match checkout_hash')
        checkout = chk.extract_parsed_checkout_object(b['checkout_jwt'])
        mid = checkout.merchant.id if checkout.merchant else None
        mpub = self.merchant_pubs.get(mid or '')
        if mpub is None:
            problems.append(f'unknown merchant {mid}')
        else:
            try:
                verify_merchant_signature(b['checkout_jwt'], mpub)
            except Exception as e:  # noqa: BLE001
                problems.append(f'merchant signature invalid: {type(e).__name__}')

        # cross-checks between payment and checkout
        total = next((x.amount for x in checkout.totals if x.type == 'total'), None)
        if pay.closed_mandate.payment_amount.amount != total:
            problems.append(
                f'payment amount {pay.closed_mandate.payment_amount.amount}'
                f' != checkout total {total}')
        if pay.closed_mandate.payee.id != mid:
            problems.append(
                f'payee {pay.closed_mandate.payee.id} != checkout merchant {mid}')

        address = RECYCLER_REGISTRY.get(pay.closed_mandate.payee.id)
        if not address:
            problems.append('payee has no registered Sui address')

        if problems:
            raise Rejected('; '.join(problems))

        # single-use: one open payment mandate = one payout
        key = b['open_payment_hash']
        if key in self.consumed:
            raise Rejected('already consumed (double use)')

        item_id = checkout.line_items[0].item.id
        amt = pay.closed_mandate.payment_amount.amount
        auth = {
            'dpp_id': item_id,
            'recipient_sui_address': address,
            'amount_minor_usd': amt,
            'amount_usdc_base_units': amt * USDC_BASE_UNITS_PER_MINOR,
            'open_payment_hash': b['open_payment_hash'],
            'open_checkout_hash': b['open_checkout_hash'],
            'transaction_id': pay.closed_mandate.transaction_id,
            'mandate_chain_sha256': compute_sha256_b64url(b['payment_chain']),
            'expires_at': pay.open_mandate.exp,
        }
        self._pending = (key, auth)
        return auth

    def commit(self) -> None:
        """Mark the last verified authorization as used (after payout)."""
        self.consumed.add(self._pending[0])


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
results: list[tuple[str, bool, str]] = []


def expect_reject(name: str, fn) -> None:
    try:
        fn()
    except Rejected as e:
        results.append((name, True, str(e)[:150]))
    except Exception as e:  # noqa: BLE001
        results.append((name, True, f'{type(e).__name__}: {str(e)[:130]}'))
    else:
        results.append((name, False, 'ACCEPTED (should have been rejected)'))


def main() -> int:
    now = int(time.time())
    a = Actors()
    opens = issue_open_mandates(a, now)
    checkout_jwt, checkout_hash = issue_checkout_jwt(a)
    good = agent_present(a, opens, checkout_jwt, checkout_hash)

    v = Verifier(pub(a.sponsor), {RECYCLER.id: pub(a.recycler)})

    # --- positive case -----------------------------------------------------
    try:
        auth = v.verify(good, now=now)
        results.append(('POSITIVE: valid chain accepted', True, ''))
    except Rejected as e:
        results.append(('POSITIVE: valid chain accepted', False, str(e)))
        auth = None

    if auth:
        (OUT / 'authorization_for_sui.json').write_text(
            json.dumps(auth, indent=2), encoding='utf-8')
        for name, tok in [
            ('open_checkout.sdjwt', opens['open_checkout']),
            ('open_payment.sdjwt', opens['open_payment']),
            ('closed_checkout_chain.sdjwt', good['checkout_chain']),
            ('closed_payment_chain.sdjwt', good['payment_chain']),
            ('checkout.jwt', checkout_jwt),
        ]:
            (OUT / name).write_text(tok, encoding='ascii')
        payloads = {
            'checkout_chain': v.client.verify(
                token=good['checkout_chain'],
                key_or_provider=lambda _t: pub(a.sponsor),
                expected_aud=AUD_CHECKOUT, expected_nonce=NONCE_CHECKOUT),
            'payment_chain': v.client.verify(
                token=good['payment_chain'],
                key_or_provider=lambda _t: pub(a.sponsor),
                expected_aud=AUD_PAYMENT, expected_nonce=NONCE_PAYMENT),
        }
        (OUT / 'verified_payloads.json').write_text(
            json.dumps(payloads, indent=2, default=str), encoding='utf-8')

        # --- double use ---------------------------------------------------
        v.commit()
        expect_reject('NEG: double use of the same authorization',
                      lambda: v.verify(good, now=now))

    # fresh verifier so earlier commit does not mask other cases
    def fresh() -> Verifier:
        return Verifier(pub(a.sponsor), {RECYCLER.id: pub(a.recycler)})

    evil = Merchant(id='evil_001', name='Evil Recycler', website='https://evil.example')

    expect_reject('NEG: payee swapped in closed payment mandate',
                  lambda: fresh().verify(agent_present(
                      a, opens, checkout_jwt, checkout_hash, payee=evil), now=now))

    expect_reject('NEG: amount increased above authorized max',
                  lambda: fresh().verify(agent_present(
                      a, opens, checkout_jwt, checkout_hash,
                      amount_minor=AMOUNT_MINOR + 1), now=now))

    expect_reject('NEG: expired mandate (now = exp + 1h)',
                  lambda: fresh().verify(good, now=now + TTL_SECONDS + 3600))

    # bytes tampering: flip one character inside the payment chain
    def tampered_bytes():
        chain = good['payment_chain']
        i = len(chain) // 3
        flipped = chain[:i] + ('A' if chain[i] != 'A' else 'B') + chain[i + 1:]
        fresh().verify({**good, 'payment_chain': flipped}, now=now)
    expect_reject('NEG: payment chain bytes tampered', tampered_bytes)

    expect_reject('NEG: closed mandate signed by a different agent key',
                  lambda: fresh().verify(agent_present(
                      a, opens, checkout_jwt, checkout_hash,
                      agent_key=new_key('rogue-agent')), now=now))

    other_jwt, other_hash = issue_checkout_jwt(a, dpp_id='dpp_9999')
    expect_reject('NEG: checkout is for a different product (DPP id)',
                  lambda: fresh().verify(agent_present(
                      a, opens, other_jwt, other_hash), now=now))

    expect_reject('NEG: payment bound to a different checkout (transaction_id)',
                  lambda: fresh().verify(agent_present(
                      a, opens, checkout_jwt, checkout_hash,
                      transaction_id='some-other-hash'), now=now))

    expect_reject('NEG: checkout_jwt altered after hashing',
                  lambda: fresh().verify(
                      {**good, 'checkout_jwt': checkout_jwt[:-4] + 'AAAA'}, now=now))

    expect_reject('NEG: wrong audience for payment mandate',
                  lambda: fresh().verify(agent_present(
                      a, opens, checkout_jwt, checkout_hash,
                      aud_payment='merchant'), now=now))

    expect_reject('NEG: wrong nonce for payment mandate',
                  lambda: fresh().verify(agent_present(
                      a, opens, checkout_jwt, checkout_hash,
                      nonce_payment='replayed-nonce'), now=now))

    # --- report ------------------------------------------------------------
    print('=' * 72)
    ok_all = True
    for name, ok, detail in results:
        ok_all &= ok
        print(('PASS ' if ok else 'FAIL ') + name)
        if detail:
            print('       -> ' + detail)
    print('=' * 72)
    print('ALL AS EXPECTED' if ok_all else 'SOME CASES BEHAVED UNEXPECTEDLY')
    if auth:
        print('\nNormalized authorization for the Sui side:')
        print(json.dumps(auth, indent=2))
    print(f'\nFiles written to: {OUT.resolve()}')
    return 0 if ok_all else 1


if __name__ == '__main__':
    raise SystemExit(main())
