import pytest

from research.nonpine_round5_pendle import INTEREST_INDEX, SWAP, cashflows, market_swap


def receipt(sy_out=-900, fee=50, index_order=2):
    return {
        "status": "0x1",
        "logs": [
            {
                "address": "yield",
                "topics": [INTEREST_INDEX, hex(10**18)],
                "logIndex": hex(index_order),
                "data": "0x",
            },
            {
                "address": "market",
                "topics": [SWAP, "0x1", "0x2"],
                "logIndex": "0x3",
                "data": "0x"
                + b"".join(
                    number.to_bytes(32, "big", signed=True)
                    for number in (1_000, sy_out, fee, 10)
                ).hex(),
            },
        ],
    }


def test_swap_matches_exact_pt_quantity_and_preceding_index():
    assert market_swap(receipt(), "market", "yield", 10**3, 1) == (
        1_000,
        900,
        50,
        10**18,
    )
    assert market_swap(receipt(), "market", "yield", 10**3, 1.001) is None
    assert market_swap(receipt(index_order=4), "market", "yield", 10**3, 1) is None
    assert market_swap(receipt(sy_out=900), "market", "yield", 10**3, 1) is None


def test_fees_are_included_in_swap_input_and_not_double_counted():
    gross, swap_fee, purchase_gas, redemption_gas, entry_cost = cashflows(
        (1_000, 900, 50, 10**18), 10**3, 100, 1_000, 100_000, 10**9
    )
    assert gross == pytest.approx(15)
    assert swap_fee == pytest.approx(5)
    assert purchase_gas == pytest.approx(0.1)
    assert redemption_gas == pytest.approx(0.2)
    assert entry_cost == pytest.approx(90)
    assert gross - swap_fee == pytest.approx(100 - entry_cost)
