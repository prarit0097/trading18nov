import pytest

from research.nonpine_round6_protocol import (
    liquidation_lot,
    redemption_return,
    ribbon_return,
)


def test_ribbon_round_removes_only_observed_fee_per_eligible_share():
    gross, fees, gas = ribbon_return(
        starting_pps=1_000_000,
        ending_pps=1_100_000,
        vault_fee=30_000_000,
        eligible_shares=1_500_000_000,
        decimals=6,
        investment=1_000,
        investor_gas=7,
    )
    assert gross == pytest.approx(120)
    assert fees == pytest.approx(20)
    assert gas == 7
    assert gross - fees - gas == pytest.approx(93)


def test_redemption_return_reconciles_size_matched_quotes():
    gross, fees, gas = redemption_return(991.0, 1002.0, 998.0, 500, 5.0)
    assert gross > 11
    assert fees > 4
    assert gross - fees - gas == pytest.approx(2)
    assert gas == 5


def test_stability_pool_lot_tracks_compounded_deposit_and_collateral():
    lusd_left, eth_gain = liquidation_lot(
        lusd_lot=1_000,
        deposited_before=1_000_000,
        burned_lusd=125_000,
        collateral_eth=2_500,
    )
    assert lusd_left == 875
    assert eth_gain == 2
