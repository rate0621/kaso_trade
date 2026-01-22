"""売買戦略モジュール。"""

import logging
from enum import Enum

import pandas as pd

from src.indicators import add_moving_averages, add_rsi

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


def rsi_contrarian_signal(
    df: pd.DataFrame,
    period: int = 14,
    oversold: int = 30,
    overbought: int = 70,
    has_position: bool = False,
) -> Signal:
    """RSI逆張り戦略でシグナルを生成する。

    売られすぎ（RSI < oversold）で買い、買われすぎ（RSI > overbought）で売り。

    Args:
        df: OHLCVデータのDataFrame
        period: RSI計算期間
        oversold: 売られすぎレベル（この値以下で買い）
        overbought: 買われすぎレベル（この値以上で売り）
        has_position: ポジションを保有しているか

    Returns:
        売買シグナル
    """
    df = df.copy()
    closes = df["close"]

    # RSI計算の詳細ログ
    logger.info(f"=== RSI計算開始 (期間: {period}) ===")

    # 直近の価格変動を表示
    recent_prices = closes.tail(period + 1)
    logger.info(f"直近{period + 1}本の終値: {[f'{p:.2f}' for p in recent_prices.values]}")

    # 価格変動を計算
    deltas = closes.diff()
    gains = deltas.where(deltas > 0, 0.0)
    losses = (-deltas).where(deltas < 0, 0.0)

    # 直近periodの上昇/下降
    recent_gains = gains.tail(period)
    recent_losses = losses.tail(period)

    gain_count = (recent_gains > 0).sum()
    loss_count = (recent_losses > 0).sum()
    total_gain = recent_gains.sum()
    total_loss = recent_losses.sum()

    logger.info(f"直近{period}本: 上昇{gain_count}回(計{total_gain:.2f}), 下降{loss_count}回(計{total_loss:.2f})")

    # 平均上昇/下降
    avg_gain = gains.rolling(window=period, min_periods=period).mean()
    avg_loss = losses.rolling(window=period, min_periods=period).mean()

    current_avg_gain = avg_gain.iloc[-1]
    current_avg_loss = avg_loss.iloc[-1]

    # RSI計算
    if pd.isna(current_avg_gain) or pd.isna(current_avg_loss):
        logger.warning("Not enough data for RSI calculation")
        return Signal.HOLD

    if current_avg_loss == 0:
        current_rsi = 100.0
    else:
        rs = current_avg_gain / current_avg_loss
        current_rsi = 100 - (100 / (1 + rs))

    logger.info(f"平均上昇: {current_avg_gain:.4f}, 平均下降: {current_avg_loss:.4f}")
    logger.info(f"RSI = {current_rsi:.2f} (売られすぎ: <{oversold}, 買われすぎ: >{overbought})")
    logger.info(f"ポジション: {'あり' if has_position else 'なし'}")

    # シグナル判定
    signal = Signal.HOLD
    reason = ""

    if has_position:
        if current_rsi > overbought:
            signal = Signal.SELL
            reason = f"RSI({current_rsi:.1f}) > {overbought} → 買われすぎ、売りシグナル"
        else:
            reason = f"RSI({current_rsi:.1f}) <= {overbought} → まだ売り時ではない、ホールド"
    else:
        if current_rsi < oversold:
            signal = Signal.BUY
            reason = f"RSI({current_rsi:.1f}) < {oversold} → 売られすぎ、買いシグナル"
        else:
            reason = f"RSI({current_rsi:.1f}) >= {oversold} → まだ買い時ではない、ホールド"

    logger.info(f"判定: {reason}")
    logger.info(f"=== 結果: {signal.value.upper()} ===")

    return signal
