"""Generate fresh P-256 keys + signatures and write tests/separation_tests.move.

Message layout must match sources/separation.move exactly:
  mandate = b"MANDATE\\x00" + mandate_id(32) + dpp_id(32) + recipient(32)
            + amount(u64 BE) + expires_ms(u64 BE)
  attest  = b"ATTEST\\x00\\x00" + mandate_id(32) + dpp_id(32) + evidence_hash(32)
            + verdict(1 byte; 0x01 = Verified)
Signatures: ECDSA P-256 / SHA-256, raw r||s (64 bytes), low-S.

Run:  python3 tools/gen_vectors.py
Needs: pip install cryptography
"""
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature, encode_dss_signature)

N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def new_key():
    return ec.generate_private_key(ec.SECP256R1())


def pk_bytes(k):
    return k.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)


def sign(k, msg: bytes) -> bytes:
    r, s = decode_dss_signature(k.sign(msg, ec.ECDSA(hashes.SHA256())))
    if s > N // 2:
        s = N - s
    sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    # sanity: verify in Python
    k.public_key().verify(encode_dss_signature(r, s), msg, ec.ECDSA(hashes.SHA256()))
    return sig


def h(s: str) -> bytes:
    return hashlib.sha256(s.encode()).digest()


def mandate_msg(mid, dpp, recipient, amount, expires):
    return (b"MANDATE\x00" + mid + dpp + recipient
            + amount.to_bytes(8, 'big') + expires.to_bytes(8, 'big'))


def attest_msg(mid, dpp, evidence, verdict=1):
    return b"ATTEST\x00\x00" + mid + dpp + evidence + bytes([verdict])


def addr(n: int) -> bytes:           # Sui address @0xN as 32 bytes
    return n.to_bytes(32, 'big')


evaluator, issuer = new_key(), new_key()
DPP, MID, EVID = h('dpp_0001'), h('mandate-0001'), h('evidence-photo-001')
RECIPIENT, AMOUNT, EXPIRES = addr(0xC), 20_000_000, 100_000

vec = {
    'EVAL_PK': pk_bytes(evaluator),
    'ISSUER_PK': pk_bytes(issuer),
    'DPP_ID': DPP,
    'MANDATE_ID': MID,
    'EVIDENCE': EVID,
    'OTHER_EVIDENCE': h('evidence-photo-002'),
    'MANDATE_SIG_OK': sign(issuer, mandate_msg(MID, DPP, RECIPIENT, AMOUNT, EXPIRES)),
    'ATTEST_SIG_OK': sign(evaluator, attest_msg(MID, DPP, EVID)),
    # role swaps: the wrong key signs the other party's message
    'MANDATE_SIG_BY_EVALUATOR': sign(evaluator, mandate_msg(MID, DPP, RECIPIENT, AMOUNT, EXPIRES)),
    'ATTEST_SIG_BY_ISSUER': sign(issuer, attest_msg(MID, DPP, EVID)),
    # evaluator signs a Rejected verdict (0x00) for the same claim
    'ATTEST_SIG_REJECTED': sign(evaluator, attest_msg(MID, DPP, EVID, verdict=0)),
}

TEMPLATE = Path(__file__).with_name('separation_tests.template').read_text()
out = TEMPLATE
for k, v in vec.items():
    out = out.replace(f'@@{k}@@', v.hex())
Path(__file__).parent.parent.joinpath('tests', 'separation_tests.move').write_text(out)
print('wrote tests/separation_tests.move')
