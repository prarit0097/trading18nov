from research.nonpine_round8_squeeth import decode_data, settlement_wei


def test_published_integer_settlement_matches_protocol_rounding():
    normalization = 134220908262942152
    index = 243770599400000000
    assert settlement_wei(10**18, normalization, index) == 32719111259269821
    assert settlement_wei(1, normalization, index) == 0


def test_swap_amounts_are_signed_256_bit_values():
    raw = "0x" + f"{7:064x}" + f"{2**256 - 10:064x}"
    assert decode_data(raw, ("uint256", "int256")) == (7, -10)
