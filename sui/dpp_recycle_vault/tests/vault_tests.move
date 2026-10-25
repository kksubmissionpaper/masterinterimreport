#[test_only]
module dpp_recycle_vault::vault_tests;

use dpp_recycle_vault::passport::{Self, OracleCap, ProductPassport};
use dpp_recycle_vault::vault::{Self, Vault, VerifierCap};
use sui::clock::{Self, Clock};
use sui::coin::{Self, Coin};
use sui::test_scenario::{Self as ts, Scenario};

public struct MOCK_USDC has drop {}

const ADMIN: address = @0xA;
const SPONSOR: address = @0xB;
const RECYCLER: address = @0xC;
const STRANGER: address = @0xD;

const AMOUNT: u64 = 20_000_000; // 20 USDC (6 decimals)
const EXPIRES: u64 = 100_000;   // ms
const DPP: vector<u8> = b"dpp_0001";
const HASH: vector<u8> = x"1111111111111111111111111111111111111111111111111111111111111111";
const OTHER_HASH: vector<u8> = x"2222222222222222222222222222222222222222222222222222222222222222";

// ---------- helpers ----------

fun clock_at(s: &mut Scenario, ms: u64): Clock {
    let mut c = clock::create_for_testing(s.ctx());
    c.set_for_testing(ms);
    c
}

fun setup(): (Scenario, ID) {
    let mut s = ts::begin(ADMIN);
    passport::init_for_testing(s.ctx());
    vault::init_for_testing(s.ctx());
    s.next_tx(ADMIN);
    let oracle = s.take_from_sender<OracleCap>();
    let pid = passport::register(&oracle, DPP, s.ctx());
    s.return_to_sender(oracle);
    (s, pid)
}

fun deposit(s: &mut Scenario, hash: vector<u8>, amount: u64, expires: u64) {
    s.next_tx(SPONSOR);
    let mut v = s.take_shared<Vault>();
    let c = clock_at(s, 1_000);
    let payment = coin::mint_for_testing<MOCK_USDC>(amount, s.ctx());
    vault::deposit<MOCK_USDC>(&mut v, hash, DPP, RECYCLER, payment, expires, &c, s.ctx());
    c.destroy_for_testing();
    ts::return_shared(v);
}

fun recycle(s: &mut Scenario, pid: ID) {
    s.next_tx(ADMIN);
    let oracle = s.take_from_sender<OracleCap>();
    let mut p = s.take_shared_by_id<ProductPassport>(pid);
    passport::mark_recycled(&oracle, &mut p);
    ts::return_shared(p);
    s.return_to_sender(oracle);
}

fun payout(
    s: &mut Scenario,
    pid: ID,
    hash: vector<u8>,
    recipient: address,
    amount: u64,
    now_ms: u64,
) {
    s.next_tx(ADMIN);
    let cap = s.take_from_sender<VerifierCap>();
    let mut v = s.take_shared<Vault>();
    let p = s.take_shared_by_id<ProductPassport>(pid);
    let c = clock_at(s, now_ms);
    vault::payout<MOCK_USDC>(&mut v, &cap, &p, hash, recipient, amount, &c, s.ctx());
    c.destroy_for_testing();
    ts::return_shared(p);
    ts::return_shared(v);
    s.return_to_sender(cap);
}

fun refund_as(s: &mut Scenario, who: address, hash: vector<u8>, now_ms: u64) {
    s.next_tx(who);
    let mut v = s.take_shared<Vault>();
    let c = clock_at(s, now_ms);
    vault::refund<MOCK_USDC>(&mut v, hash, &c, s.ctx());
    c.destroy_for_testing();
    ts::return_shared(v);
}

// ---------- positive ----------

#[test]
fun payout_succeeds_when_recycled() {
    let (mut s, pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    recycle(&mut s, pid);
    payout(&mut s, pid, HASH, RECYCLER, AMOUNT, 5_000);

    s.next_tx(RECYCLER);
    let received = s.take_from_sender<Coin<MOCK_USDC>>();
    assert!(received.value() == AMOUNT);
    s.return_to_sender(received);
    s.end();
}

// ---------- negative: payout ----------

#[test, expected_failure(abort_code = vault::ENotRecycled)]
fun payout_fails_when_not_recycled() {
    let (mut s, pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    payout(&mut s, pid, HASH, RECYCLER, AMOUNT, 5_000);
    s.end();
}

#[test, expected_failure(abort_code = vault::EWrongRecipient)]
fun payout_fails_for_wrong_recipient() {
    let (mut s, pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    recycle(&mut s, pid);
    payout(&mut s, pid, HASH, STRANGER, AMOUNT, 5_000);
    s.end();
}

#[test, expected_failure(abort_code = vault::EWrongAmount)]
fun payout_fails_for_wrong_amount() {
    let (mut s, pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    recycle(&mut s, pid);
    payout(&mut s, pid, HASH, RECYCLER, AMOUNT + 1, 5_000);
    s.end();
}

#[test, expected_failure(abort_code = vault::EAlreadySettled)]
fun payout_fails_on_second_use() {
    let (mut s, pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    recycle(&mut s, pid);
    payout(&mut s, pid, HASH, RECYCLER, AMOUNT, 5_000);
    payout(&mut s, pid, HASH, RECYCLER, AMOUNT, 6_000);
    s.end();
}

#[test, expected_failure(abort_code = vault::EExpired)]
fun payout_fails_after_expiry() {
    let (mut s, pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    recycle(&mut s, pid);
    payout(&mut s, pid, HASH, RECYCLER, AMOUNT, EXPIRES + 1);
    s.end();
}

#[test, expected_failure(abort_code = vault::ENoEscrow)]
fun payout_fails_for_unknown_hash() {
    let (mut s, pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    recycle(&mut s, pid);
    payout(&mut s, pid, OTHER_HASH, RECYCLER, AMOUNT, 5_000);
    s.end();
}

#[test, expected_failure(abort_code = vault::EWrongPassport)]
fun payout_fails_for_other_product_passport() {
    let (mut s, _pid) = setup();
    // a second passport for a different product, already recycled
    s.next_tx(ADMIN);
    let oracle = s.take_from_sender<OracleCap>();
    let other = passport::register(&oracle, b"dpp_9999", s.ctx());
    s.return_to_sender(oracle);
    recycle(&mut s, other);

    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    payout(&mut s, other, HASH, RECYCLER, AMOUNT, 5_000);
    s.end();
}

// ---------- negative: deposit ----------

#[test, expected_failure(abort_code = vault::EDuplicateHash)]
fun deposit_fails_for_duplicate_hash() {
    let (mut s, _pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    s.end();
}

#[test, expected_failure(abort_code = vault::EBadHashLength)]
fun deposit_fails_for_bad_hash_length() {
    let (mut s, _pid) = setup();
    deposit(&mut s, x"1234", AMOUNT, EXPIRES);
    s.end();
}

#[test, expected_failure(abort_code = vault::EZeroAmount)]
fun deposit_fails_for_zero_amount() {
    let (mut s, _pid) = setup();
    deposit(&mut s, HASH, 0, EXPIRES);
    s.end();
}

#[test, expected_failure(abort_code = vault::EAlreadyExpired)]
fun deposit_fails_if_already_expired() {
    let (mut s, _pid) = setup();
    deposit(&mut s, HASH, AMOUNT, 500); // clock is at 1_000
    s.end();
}

// ---------- passport ----------

#[test, expected_failure(abort_code = passport::EBadTransition)]
fun passport_cannot_be_recycled_twice() {
    let (mut s, pid) = setup();
    recycle(&mut s, pid);
    recycle(&mut s, pid);
    s.end();
}

// ---------- refund ----------

#[test]
fun sponsor_can_refund_after_expiry() {
    let (mut s, _pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    refund_as(&mut s, SPONSOR, HASH, EXPIRES + 1);

    s.next_tx(SPONSOR);
    let back = s.take_from_sender<Coin<MOCK_USDC>>();
    assert!(back.value() == AMOUNT);
    s.return_to_sender(back);
    s.end();
}

#[test, expected_failure(abort_code = vault::ENotExpired)]
fun refund_fails_before_expiry() {
    let (mut s, _pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    refund_as(&mut s, SPONSOR, HASH, 5_000);
    s.end();
}

#[test, expected_failure(abort_code = vault::ENotSponsor)]
fun refund_fails_for_non_sponsor() {
    let (mut s, _pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    refund_as(&mut s, STRANGER, HASH, EXPIRES + 1);
    s.end();
}

#[test, expected_failure(abort_code = vault::EAlreadySettled)]
fun refund_fails_after_payout() {
    let (mut s, pid) = setup();
    deposit(&mut s, HASH, AMOUNT, EXPIRES);
    recycle(&mut s, pid);
    payout(&mut s, pid, HASH, RECYCLER, AMOUNT, 5_000);
    refund_as(&mut s, SPONSOR, HASH, EXPIRES + 1);
    s.end();
}
