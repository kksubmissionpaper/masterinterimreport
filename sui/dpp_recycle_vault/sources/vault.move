/// Escrow vault keyed by the hash of the AP2 open Payment Mandate.
///
/// - The sponsor locks coins under `mandate_hash` (one escrow per hash).
/// - The off-chain verifier (holder of VerifierCap) has already checked the
///   AP2 mandate chain; it asks for payout with the verified recipient/amount.
/// - Move re-checks: escrow exists, not settled, not expired, passport is the
///   right DPP and is Recycled, recipient and amount match the escrow.
/// By K.Kamimura
module dpp_recycle_vault::vault;

use dpp_recycle_vault::passport::ProductPassport;
use sui::balance::Balance;
use sui::clock::Clock;
use sui::coin::{Self, Coin};
use sui::dynamic_object_field as dof;
use sui::event;

const EBadHashLength: u64 = 0;
const EZeroAmount: u64 = 1;
const EAlreadyExpired: u64 = 2;
const EDuplicateHash: u64 = 3;
const ENoEscrow: u64 = 4;
const EAlreadySettled: u64 = 5;
const EExpired: u64 = 6;
const EWrongPassport: u64 = 7;
const ENotRecycled: u64 = 8;
const EWrongRecipient: u64 = 9;
const EWrongAmount: u64 = 10;
const ENotSponsor: u64 = 11;
const ENotExpired: u64 = 12;

public struct Vault has key {
    id: UID,
}

/// Authority to trigger payouts after off-chain AP2 verification.
public struct VerifierCap has key, store {
    id: UID,
}

public struct Escrow<phantom T> has key, store {
    id: UID,
    sponsor: address,
    dpp_id: vector<u8>,
    recipient: address,
    amount: u64,
    expires_at_ms: u64,
    settled: bool,
    balance: Balance<T>,
}

public struct EscrowCreated has copy, drop {
    mandate_hash: vector<u8>,
    dpp_id: vector<u8>,
    recipient: address,
    amount: u64,
    expires_at_ms: u64,
}

public struct PayoutExecuted has copy, drop {
    mandate_hash: vector<u8>,
    dpp_id: vector<u8>,
    recipient: address,
    amount: u64,
}

public struct Refunded has copy, drop {
    mandate_hash: vector<u8>,
    sponsor: address,
    amount: u64,
}

fun init(ctx: &mut TxContext) {
    transfer::share_object(Vault { id: object::new(ctx) });
    transfer::transfer(VerifierCap { id: object::new(ctx) }, ctx.sender());
}

/// Sponsor locks `payment` under `mandate_hash` (32 bytes).
public fun deposit<T>(
    vault: &mut Vault,
    mandate_hash: vector<u8>,
    dpp_id: vector<u8>,
    recipient: address,
    payment: Coin<T>,
    expires_at_ms: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert!(mandate_hash.length() == 32, EBadHashLength);
    let amount = payment.value();
    assert!(amount > 0, EZeroAmount);
    assert!(expires_at_ms > clock.timestamp_ms(), EAlreadyExpired);
    assert!(!dof::exists(&vault.id, mandate_hash), EDuplicateHash);

    event::emit(EscrowCreated { mandate_hash, dpp_id, recipient, amount, expires_at_ms });

    let escrow = Escrow<T> {
        id: object::new(ctx),
        sponsor: ctx.sender(),
        dpp_id,
        recipient,
        amount,
        expires_at_ms,
        settled: false,
        balance: payment.into_balance(),
    };
    dof::add(&mut vault.id, mandate_hash, escrow);
}

/// Pay the recipient once the passport is Recycled. One payout per hash.
public fun payout<T>(
    vault: &mut Vault,
    _cap: &VerifierCap,
    passport: &ProductPassport,
    mandate_hash: vector<u8>,
    recipient: address,
    amount: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert!(dof::exists(&vault.id, mandate_hash), ENoEscrow);
    let escrow: &mut Escrow<T> = dof::borrow_mut(&mut vault.id, mandate_hash);

    assert!(!escrow.settled, EAlreadySettled);
    assert!(clock.timestamp_ms() <= escrow.expires_at_ms, EExpired);
    assert!(passport.dpp_id() == &escrow.dpp_id, EWrongPassport);
    assert!(passport.is_recycled(), ENotRecycled);
    assert!(recipient == escrow.recipient, EWrongRecipient);
    assert!(amount == escrow.amount, EWrongAmount);

    escrow.settled = true;
    let payment = coin::from_balance(escrow.balance.withdraw_all(), ctx);
    event::emit(PayoutExecuted { mandate_hash, dpp_id: escrow.dpp_id, recipient, amount });
    transfer::public_transfer(payment, recipient);
}

/// After expiry, the sponsor can take back an unsettled escrow.
public fun refund<T>(
    vault: &mut Vault,
    mandate_hash: vector<u8>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert!(dof::exists(&vault.id, mandate_hash), ENoEscrow);
    let escrow: &mut Escrow<T> = dof::borrow_mut(&mut vault.id, mandate_hash);

    assert!(ctx.sender() == escrow.sponsor, ENotSponsor);
    assert!(!escrow.settled, EAlreadySettled);
    assert!(clock.timestamp_ms() > escrow.expires_at_ms, ENotExpired);

    escrow.settled = true;
    let amount = escrow.amount;
    let sponsor = escrow.sponsor;
    let payment = coin::from_balance(escrow.balance.withdraw_all(), ctx);
    event::emit(Refunded { mandate_hash, sponsor, amount });
    transfer::public_transfer(payment, sponsor);
}

#[test_only]
public fun init_for_testing(ctx: &mut TxContext) {
    init(ctx)
}
