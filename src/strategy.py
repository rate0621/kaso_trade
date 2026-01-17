"""売買戦略モジュール。"""

import logging
from enum import Enum

import pandas as pd

from src.indicators import add_moving_averages

logger = logging.getLogger(__name__)


class Signal(Enum):
    """売買シグナル。"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


def ma_crossover_signal(
    df: pd.DataFrame,
    short_period: int = 10,
    long_period: int = 20
) -> Signal:
    """移動平均クロスオーバーでシグナルを生成する。

    Args:
        df: OHLCVデータのDataFrame
        short_period: 短期移動平均期間
        long_period: 長期移動平均期間

    Returns:
        売買シグナル
    """
    df = add_moving_averages(df, short_period, long_period)

    short_col = f"sma_{short_period}"
    long_col = f"sma_{long_period}"

    # 直近のデータが不足している場合
    if df[short_col].isna().iloc[-1] or df[long_col].isna().iloc[-1]:
        logger.warning("Not enough data for MA calculation")
        return Signal.HOLD

    # 現在と1本前のクロス状態を確認
    current_short = df[short_col].iloc[-1]
    current_long = df[long_col].iloc[-1]
    prev_short = df[short_col].iloc[-2]
    prev_long = df[long_col].iloc[-2]

    # ゴールデンクロス（短期が長期を下から上に抜けた）
    if prev_short <= prev_long and current_short > current_long:
        logger.info(f"Golden Cross detected: short={current_short:.2f}, long={current_long:.2f}")
        return Signal.BUY

    # デッドクロス（短期が長期を上から下に抜けた）
    if prev_short >= prev_long and current_short < current_long:
        logger.info(f"Dead Cross detected: short={current_short:.2f}, long={current_long:.2f}")
        return Signal.SELL

    return Signal.HOLD
