"""データ取得・加工モジュール。

bitFlyerはOHLCVをサポートしていないため、
KuCoinからBTC/USDTのOHLCVデータを取得する。
（価格変動パターンはBTC/JPYと同等のため、RSI計算に使用可能）
"""

import logging

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)

# OHLCVデータ取得用（APIキー不要）
_kucoin: ccxt.kucoin | None = None


def get_kucoin() -> ccxt.kucoin:
    """KuCoinクライアントを取得する（OHLCVデータ用）。"""
    global _kucoin
    if _kucoin is None:
        _kucoin = ccxt.kucoin({"enableRateLimit": True})
        logger.info("KuCoin client initialized for OHLCV data")
    return _kucoin


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
    KuCoinからBTC/USDTのデータを取得する。
    （RSI計算には価格の相対的な動きが重要なため、USDTベースでも問題なし）

    Args:
        exchange: Exchangeインスタンス（未使用、互換性のため）
        symbol: 通貨ペア（例: 'BTC/JPY'）→ BTC/USDTに変換
        timeframe: 時間足
        limit: 取得する本数

    Returns:
        OHLCVデータのDataFrame
    """
    kucoin = get_kucoin()
    # BTC/JPY → BTC/USDT に変換
    kucoin_symbol = "BTC/USDT"
    ohlcv = kucoin.fetch_ohlcv(kucoin_symbol, timeframe, limit=limit)
    df = ohlcv_to_dataframe(ohlcv)
    logger.info(f"Fetched {len(df)} candles for {kucoin_symbol} {timeframe} (via KuCoin)")
    return df
