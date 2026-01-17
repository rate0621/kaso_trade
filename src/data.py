"""データ取得・加工モジュール。

bitFlyerはOHLCVをサポートしていないため、
bitbank（同じく日本の取引所）からOHLCVデータを取得する。
"""

import logging

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)

# OHLCVデータ取得用（APIキー不要）
_bitbank: ccxt.bitbank | None = None


def get_bitbank() -> ccxt.bitbank:
    """bitbankクライアントを取得する（OHLCVデータ用）。"""
    global _bitbank
    if _bitbank is None:
        _bitbank = ccxt.bitbank({"enableRateLimit": True})
        logger.info("bitbank client initialized for OHLCV data")
    return _bitbank


def ohlcv_to_dataframe(ohlcv: list[list]) -> pd.DataFrame:
    """OHLCVデータをDataFrameに変換する。

    Args:
        ohlcv: OHLCVデータのリスト [[timestamp, open, high, low, close, volume], ...]

    Returns:
        DataFrameに変換されたOHLCVデータ
    """
    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("datetime", inplace=True)
    return df


def fetch_ohlcv_as_df(
    exchange,  # Exchange型だが、bitFlyerでは使わない
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100
) -> pd.DataFrame:
    """OHLCVデータを取得してDataFrameで返す。

    bitFlyerはOHLCVをサポートしていないため、
    bitbankから同じ通貨ペアのデータを取得する。

    Args:
        exchange: Exchangeインスタンス（未使用、互換性のため）
        symbol: 通貨ペア（例: 'BTC/JPY'）
        timeframe: 時間足
        limit: 取得する本数

    Returns:
        OHLCVデータのDataFrame
    """
    bitbank = get_bitbank()
    ohlcv = bitbank.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = ohlcv_to_dataframe(ohlcv)
    logger.info(f"Fetched {len(df)} candles for {symbol} {timeframe} (via bitbank)")
    return df
