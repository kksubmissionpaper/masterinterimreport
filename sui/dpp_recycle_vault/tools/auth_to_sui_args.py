"""Convert AP2 authorization_for_sui.json into the argument values the Move
functions need (vault::deposit / vault::payout).

Usage:  python tools/auth_to_sui_args.py inputs/authorization_for_sui.json
Output is ASCII only.
"""
import base64
import json
import sys


def b64url_to_bytes(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def as_vector_u8(b: bytes) -> str:
    return 'vector[' + ','.join(f'{x}u8' for x in b) + ']'


def main(path: str) -> None:
    a = json.load(open(path, encoding='utf-8'))
    h = b64url_to_bytes(a['open_payment_hash'])
    if len(h) != 32:
        raise SystemExit(f'hash must be 32 bytes, got {len(h)}')
    dpp = a['dpp_id'].encode('ascii')
    out = {
        'mandate_hash_hex': '0x' + h.hex(),
        'mandate_hash_vector_u8': as_vector_u8(h),
        'dpp_id_vector_u8': as_vector_u8(dpp),
        'recipient': a['recipient_sui_address'],
        'amount_usdc_base_units': a['amount_usdc_base_units'],
        'expires_at_ms': a['expires_at'] * 1000,
    }
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'inputs/authorization_for_sui.json')
