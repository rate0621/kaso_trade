"""データ取得・加工モジュール。

bitFlyerはOHLCVをサポートしていないため、
Binanceから BTC/USDT のOHLCVデータを取得する。
（価格変動パターンはBTC/JPYと同等のため、RSI計算に使用可能）
"""

import logging

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)

# OHLCVデータ取得用（APIキー不要）
_binance: ccxt.binance | None = None


def get_binance() -> ccxt.binance:
    """Binanceクライアントを取得する（OHLCVデータ用）。"""
    global _binance
    if _binance is None:
        _binance = ccxt.binance({"enableRateLimit": True})
        logger.info("Binance client initialized for OHLCV data")
    return _binance


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
    BinanceからBTC/USDTのデータを取得する。
    （RSI計算には価格の相対的な動きが重要なため、USDTベースでも問題なし）

    Args:
        exchange: Exchangeインスタンス（未使用、互換性のため）
        symbol: 通貨ペア（例: 'BTC/JPY'）→ BTC/USDTに変換
        timeframe: 時間足
        limit: 取得する本数

    Returns:
        OHLCVデータのDataFrame
    """
    binance = get_binance()
    # BTC/JPY → BTC/USDT に変換（Binanceには JPY ペアがない）
    binance_symbol = "BTC/USDT"
    ohlcv = binance.fetch_ohlcv(binance_symbol, timeframe, limit=limit)
    df = ohlcv_to_dataframe(ohlcv)
    logger.info(f"Fetched {len(df)} candles for {binance_symbol} {timeframe} (via Binance)")
    return df
