/// Minimal Digital Product Passport (DPP) object.
/// Only the holder of an OracleCap can register it or change its status.
/// By K.Kamimura
module dpp_recycle_vault::passport;

const STATUS_REGISTERED: u8 = 0;
const STATUS_RECYCLED: u8 = 1;

const EBadTransition: u64 = 0;

public struct ProductPassport has key {
    id: UID,
    dpp_id: vector<u8>,
    status: u8,
}

/// Authority to register passports and mark them as recycled
/// (MVP stand-in for an oracle / certified recycler).
public struct OracleCap has key, store {
    id: UID,
}

fun init(ctx: &mut TxContext) {
    transfer::transfer(OracleCap { id: object::new(ctx) }, ctx.sender());
}

public fun register(_: &OracleCap, dpp_id: vector<u8>, ctx: &mut TxContext): ID {
    let passport = ProductPassport {
        id: object::new(ctx),
        dpp_id,
        status: STATUS_REGISTERED,
    };
    let passport_id = object::id(&passport);
    transfer::share_object(passport);
    passport_id
}

/// Registered -> Recycled. Any other transition aborts.
public fun mark_recycled(_: &OracleCap, passport: &mut ProductPassport) {
    assert!(passport.status == STATUS_REGISTERED, EBadTransition);
    passport.status = STATUS_RECYCLED;
}

public fun is_recycled(passport: &ProductPassport): bool {
    passport.status == STATUS_RECYCLED
}

public fun dpp_id(passport: &ProductPassport): &vector<u8> {
    &passport.dpp_id
}

#[test_only]
public fun init_for_testing(ctx: &mut TxContext) {
    init(ctx)
}
