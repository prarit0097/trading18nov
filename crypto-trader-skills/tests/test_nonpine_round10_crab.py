from fractions import Fraction

from research.nonpine_round10_crab import flow_wei, payout_wei


def test_conservative_redeem_rate_is_a_rational_lower_bound():
    ratio = min(Fraction(p, shares) for shares, p in [(10, 7), (5, 4)])
    assert payout_wei(3, ratio) == 2
    assert payout_wei(10, ratio) == 7


def test_hedge_proceeds_and_fee_conserve_cash():
    sale, gross, fee = flow_wei(
        deposit=500_000, swap_in=1_000, swap_out=300_000, minted=900, redemption=240_000
    )
    assert sale == 270_000
    assert fee == 812
    assert gross - fee == 10_000
