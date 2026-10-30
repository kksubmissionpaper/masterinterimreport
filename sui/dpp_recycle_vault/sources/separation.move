/// Minimal authority-separation check (no vault, no payment).
///
/// A DPP can become Recycled only if TWO independent signatures are valid:
///   1. the mandate issuer signs the constraints (mandate id, DPP, recipient,
///      amount, expiry),
///   2. the evaluator signs a "Verified" attestation bound to that mandate,
///      that DPP and the evidence hash.
/// The evaluator cannot create or change constraints; the issuer cannot declare
/// evidence verified; nobody holds a Cap that can change the status directly.
/// `execute` rebuilds both messages from its own arguments, so changing any
/// field invalidates the signature.
///
/// Trust root (stated assumption): whoever calls `new_registry` chooses the two
/// public keys. Key custody (keeping the two keys in different hands) is an
/// organisational condition that code cannot enforce.
/// By K.Kamimura
module dpp_recycle_vault::separation;

use sui::address;
use sui::clock::Clock;
use sui::ecdsa_r1;
use sui::event;
use sui::table::{Self, Table};

const STATUS_REGISTERED: u8 = 0;
const STATUS_RECYCLED: u8 = 1;
const HASH_SHA256: u8 = 1; // secp256r1_verify: KECCAK256 = 0, SHA256 = 1

const EBadLength: u64 = 0;
const EWrongPassport: u64 = 1;
const EExpired: u64 = 2;
const EAlreadyUsed: u64 = 3;
const EBadState: u64 = 4;
const EBadMandateSig: u64 = 5;
const EBadAttestationSig: u64 = 6;
const ESameKey: u64 = 7;
const ERejectedVerdict: u64 = 8;

///const VERDICT_REJECTED: u8 = 0;
const VERDICT_VERIFIED: u8 = 1;

const MANDATE_TAG: vector<u8> = b"MANDATE\x00"; // 8 bytes
const ATTEST_TAG: vector<u8> = b"ATTEST\x00\x00"; // 8 bytes

public struct Registry has key {
    id: UID,
    evaluator_pk: vector<u8>, // 33-byte compressed P-256 key
    issuer_pk: vector<u8>,
    used: Table<vector<u8>, bool>, // consumed mandate ids
}

public struct DppState has key {
    id: UID,
    dpp_id: vector<u8>, // 32 bytes
    status: u8,
}

public struct Executed has copy, drop {
    mandate_id: vector<u8>,
    dpp_id: vector<u8>,
    recipient: address,
    amount: u64,
    evidence_hash: vector<u8>,
}

public fun new_registry(
    evaluator_pk: vector<u8>,
    issuer_pk: vector<u8>,
    ctx: &mut TxContext,
) {
    assert!(evaluator_pk != issuer_pk, ESameKey);
    transfer::share_object(Registry {
        id: object::new(ctx),
        evaluator_pk,
        issuer_pk,
        used: table::new(ctx),
    });
}

public fun new_dpp(dpp_id: vector<u8>, ctx: &mut TxContext): ID {
    assert!(dpp_id.length() == 32, EBadLength);
    let d = DppState { id: object::new(ctx), dpp_id, status: STATUS_REGISTERED };
    let id = object::id(&d);
    transfer::share_object(d);
    id
}

/// Anyone may submit; authority comes only from the two signatures.
public fun execute(
    reg: &mut Registry,
    dpp: &mut DppState,
    mandate_id: vector<u8>,
    dpp_id: vector<u8>,
    recipient: address,
    amount: u64,
    expires_ms: u64,
    evidence_hash: vector<u8>,
    verdict: u8,
    mandate_sig: vector<u8>,
    attestation_sig: vector<u8>,
    clock: &Clock,
) {
    assert!(
        mandate_id.length() == 32 && dpp_id.length() == 32 && evidence_hash.length() == 32,
        EBadLength,
    );
    assert!(dpp.dpp_id == dpp_id, EWrongPassport);
    assert!(clock.timestamp_ms() <= expires_ms, EExpired);
    assert!(!reg.used.contains(mandate_id), EAlreadyUsed);
    assert!(dpp.status == STATUS_REGISTERED, EBadState);

    let m = mandate_message(&mandate_id, &dpp_id, recipient, amount, expires_ms);
    assert!(
        ecdsa_r1::secp256r1_verify(&mandate_sig, &reg.issuer_pk, &m, HASH_SHA256),
        EBadMandateSig,
    );
    let a = attestation_message(&mandate_id, &dpp_id, &evidence_hash, verdict);
    assert!(
        ecdsa_r1::secp256r1_verify(&attestation_sig, &reg.evaluator_pk, &a, HASH_SHA256),
        EBadAttestationSig,
    );
    // Reached only if the evaluator really signed THIS verdict. A genuine
    // signed "Rejected" is refused here with its own error code.
    assert!(verdict == VERDICT_VERIFIED, ERejectedVerdict);

    // mark used only after both signatures are valid
    reg.used.add(mandate_id, true);
    dpp.status = STATUS_RECYCLED;
    event::emit(Executed { mandate_id, dpp_id, recipient, amount, evidence_hash });
}

public fun is_recycled(d: &DppState): bool {
    d.status == STATUS_RECYCLED
}

// ---- message construction (fixed-width fields, so no ambiguity) ----

fun mandate_message(
    mandate_id: &vector<u8>,
    dpp_id: &vector<u8>,
    recipient: address,
    amount: u64,
    expires_ms: u64,
): vector<u8> {
    let mut m = MANDATE_TAG;
    m.append(*mandate_id);
    m.append(*dpp_id);
    m.append(address::to_bytes(recipient));
    put_u64(&mut m, amount);
    put_u64(&mut m, expires_ms);
    m
}

/// The verdict byte is part of the signed message, so flipping it after
/// signing invalidates the signature (EBadAttestationSig).
fun attestation_message(
    mandate_id: &vector<u8>,
    dpp_id: &vector<u8>,
    evidence_hash: &vector<u8>,
    verdict: u8,
): vector<u8> {
    let mut m = ATTEST_TAG;
    m.append(*mandate_id);
    m.append(*dpp_id);
    m.append(*evidence_hash);
    m.push_back(verdict);
    m
}

/// big-endian u64
fun put_u64(out: &mut vector<u8>, v: u64) {
    let mut i = 8u8;
    while (i > 0) {
        i = i - 1;
        out.push_back((((v >> (i * 8)) & 0xff) as u8));
    };
}
