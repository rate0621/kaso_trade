"""テクニカル指標計算モジュール。"""

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, SMAIndicator


def add_sma(df: pd.DataFrame, period: int, column: str = "close") -> pd.DataFrame:
    """単純移動平均を追加する。

    Args:
        df: OHLCVデータのDataFrame
        period: 移動平均期間
        column: 計算に使用するカラム名

    Returns:
        SMAカラムが追加されたDataFrame
    """
    sma = SMAIndicator(close=df[column], window=period)
    df[f"sma_{period}"] = sma.sma_indicator()
    return df


def add_ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.DataFrame:
    """指数移動平均を追加する。

    Args:
        df: OHLCVデータのDataFrame
        period: 移動平均期間
        column: 計算に使用するカラム名

    Returns:
        EMAカラムが追加されたDataFrame
    """
    ema = EMAIndicator(close=df[column], window=period)
    df[f"ema_{period}"] = ema.ema_indicator()
    return df


def add_moving_averages(
    df: pd.DataFrame,
    short_period: int = 10,
    long_period: int = 20
) -> pd.DataFrame:
    """短期・長期移動平均を追加する。

    Args:
        df: OHLCVデータのDataFrame
        short_period: 短期移動平均期間
        long_period: 長期移動平均期間

    Returns:
        移動平均カラムが追加されたDataFrame
    """
    df = add_sma(df, short_period)
    df = add_sma(df, long_period)
    return df


def add_rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.DataFrame:
    """RSI（相対力指数）を追加する。

    Args:
        df: OHLCVデータのDataFrame
        period: RSI計算期間
        column: 計算に使用するカラム名

    Returns:
        RSIカラムが追加されたDataFrame
    """
    rsi = RSIIndicator(close=df[column], window=period)
    df[f"rsi_{period}"] = rsi.rsi()
    return df
