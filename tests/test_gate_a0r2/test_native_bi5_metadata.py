from __future__ import annotations

from datetime import date

import pytest

from fx_smc_bot.data.dukascopy_bi5 import (
    BI5_INSTRUMENTS,
    dukascopy_candle_url,
    instrument_metadata,
)


def test_all_authorized_a0r2_pairs_have_frozen_native_metadata() -> None:
    assert set(BI5_INSTRUMENTS) == {
        "EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCAD", "USDCHF",
        "EURJPY", "GBPJPY", "AUDJPY",
    }
    assert all(item.candle_record_size == 24 for item in BI5_INSTRUMENTS.values())
    assert all(item.endianness == "big" for item in BI5_INSTRUMENTS.values())
    assert all(item.timezone == "UTC" for item in BI5_INSTRUMENTS.values())


@pytest.mark.parametrize("pair", sorted(BI5_INSTRUMENTS))
def test_native_urls_preserve_frozen_pair_and_side_contract(pair: str) -> None:
    metadata = instrument_metadata(pair)
    bid = dukascopy_candle_url(pair, date(2010, 1, 4), "bid")
    ask = dukascopy_candle_url(pair, date(2010, 1, 4), "ask")

    assert f"/{metadata.instrument_code}/2010/00/04/" in bid
    assert bid.endswith("/BID_candles_min_1.bi5")
    assert ask.endswith("/ASK_candles_min_1.bi5")


def test_unauthorized_native_pair_is_rejected() -> None:
    with pytest.raises(ValueError, match="A0R2_UNAUTHORIZED_NATIVE_BI5_INSTRUMENT"):
        instrument_metadata("NZDUSD")
