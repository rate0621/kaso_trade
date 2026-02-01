"""取引ロジックの共通モジュール。

bot.py（ローカル実行）とapi/trade.py（Vercel Cron）で共有する。
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from src.config import Config, Strategy, SymbolConfig
from src.data import fetch_ohlcv_as_df
from src.exchange import Exchange
from src.position import check_stop_loss, clear_position, load_position, save_position
from src.strategy import Signal, ma_crossover_signal, rsi_contrarian_signal

logger = logging.getLogger(__name__)


class Trend:
    """トレンド状態。"""

    UPTREND = "uptrend"  # 上昇トレンド
    DOWNTREND = "downtrend"  # 下降トレンド
    SIDEWAYS = "sideways"  # 横ばい


@dataclass
class TradeResult:
    """取引結果。"""

    symbol: str
    strategy: str
    signal: str
    price: float
    balance_jpy: float
    balance_crypto: float
    has_position: bool
    action: str = "none"
    amount: Optional[Decimal] = None
    order_id: Optional[str] = None
    error: Optional[str] = None
    trend: Optional[str] = None  # トレンド状態


def is_supabase_configured() -> bool:
    """Supabaseが設定されているか確認する。"""
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def get_crypto_currency(symbol: str) -> str:
    """シンボルから暗号通貨部分を取得する。

    Args:
        symbol: 通貨ペア（例: 'BTC/JPY', 'ETH/JPY'）

    Returns:
        暗号通貨コード（例: 'BTC', 'ETH'）
    """
    return symbol.split("/")[0]


def get_order_unit(symbol: str) -> Decimal:
    """通貨ペアの注文単位を取得する。

    bitFlyerは通貨ごとに注文単位が異なる。
    """
    crypto = symbol.split("/")[0]
    # bitFlyerの注文単位
    units = {
        "BTC": Decimal("0.001"),
        "ETH": Decimal("0.01"),
    }
    return units.get(crypto, Decimal("0.01"))


def get_min_balance(symbol: str) -> float:
    """通貨ペアの最小残高を取得する。"""
    crypto = get_crypto_currency(symbol)
    if crypto == "BTC":
        return 0.001
    return 0.01  # ETHなど


def check_trend(df, ma_period: int = 50, lookback: int = 5) -> str:
    """トレンドを判定する。

    判定ロジック:
    - 価格 > MA50 かつ MA50が上向き → 上昇トレンド
    - 価格 < MA50 かつ MA50が下向き → 下降トレンド
    - それ以外 → 横ばい

    Args:
        df: OHLCVデータ
        ma_period: 移動平均期間
        lookback: MA傾き判定の期間

    Returns:
        トレンド状態
    """
    df = df.copy()
    df[f"ma{ma_period}"] = df["close"].rolling(ma_period).mean()

    if len(df) < ma_period + lookback:
        logger.warning("Not enough data for trend check")
        return Trend.SIDEWAYS

    current_price = df["close"].iloc[-1]
    current_ma = df[f"ma{ma_period}"].iloc[-1]
    prev_ma = df[f"ma{ma_period}"].iloc[-1 - lookback]

    price_above_ma = current_price > current_ma
    ma_rising = current_ma > prev_ma

    if price_above_ma and ma_rising:
        trend = Trend.UPTREND
    elif not price_above_ma and not ma_rising:
        trend = Trend.DOWNTREND
    else:
        trend = Trend.SIDEWAYS

    logger.info(
        f"Trend: {trend} (price={current_price:.0f}, "
        f"MA{ma_period}={current_ma:.0f}, rising={ma_rising})"
    )

    return trend


def get_signal_for_symbol(
    df,
    symbol_config: SymbolConfig,
    has_position: bool,
) -> Signal:
    """シンボル設定に応じた戦略でシグナルを生成する。"""
    if symbol_config.strategy == Strategy.RSI_CONTRARIAN:
        return rsi_contrarian_signal(
            df,
            period=symbol_config.rsi_period,
            oversold=symbol_config.rsi_oversold,
            overbought=symbol_config.rsi_overbought,
            has_position=has_position,
        )
    elif symbol_config.strategy == Strategy.MA_CROSSOVER:
        return ma_crossover_signal(
            df,
            short_period=symbol_config.ma_short_period,
            long_period=symbol_config.ma_long_period,
            has_position=has_position,
        )
    else:
        logger.warning(f"Unknown strategy: {symbol_config.strategy}")
        return Signal.HOLD


def process_symbol(
    exchange: Exchange,
    config: Config,
    symbol_config: SymbolConfig,
) -> TradeResult:
    """1つの通貨ペアの取引処理を行い、結果を返す。

    Args:
        exchange: 取引所インスタンス
        config: 設定
        symbol_config: 通貨ペアごとの設定

    Returns:
        取引結果
    """
    symbol = symbol_config.symbol
    crypto = get_crypto_currency(symbol)

    # データ取得
    df = fetch_ohlcv_as_df(exchange, symbol, config.timeframe, limit=100)

    # 残高確認
    balance = exchange.fetch_balance()
    jpy_balance = float(balance.get("JPY", {}).get("free", 0))
    crypto_balance = float(balance.get(crypto, {}).get("free", 0))

    ticker = exchange.fetch_ticker(symbol)
    current_price = ticker["last"]

    # 最小取引量
    min_balance = get_min_balance(symbol)

    # ポジション保有状態を確認（実残高ベースで判定）
    # ※ポジションデータ（Supabase）は購入価格の記録として損切り計算にのみ使用
    has_position = crypto_balance > min_balance

    # トレンド判定（MA50ベース）
    trend = check_trend(df, ma_period=50, lookback=5)

    # 戦略に応じたシグナル生成
    signal = get_signal_for_symbol(df, symbol_config, has_position)
    logger.info(f"[{symbol}] Signal: {signal.value}, Trend: {trend}")

    # RSI逆張り戦略の場合のみ、下降トレンドで買いシグナルをスキップ
    # （順張りMAクロスオーバーは自身でトレンドを判断しているためフィルター不要）
    if (
        symbol_config.strategy == Strategy.RSI_CONTRARIAN
        and signal == Signal.BUY
        and trend == Trend.DOWNTREND
    ):
        logger.warning(f"[{symbol}] Buy signal skipped due to downtrend (RSI contrarian)")
        signal = Signal.HOLD

    result = TradeResult(
        symbol=symbol,
        strategy=symbol_config.strategy.value,
        signal=signal.value,
        price=current_price,
        balance_jpy=jpy_balance,
        balance_crypto=crypto_balance,
        has_position=has_position,
        trend=trend,
    )

    order_unit = get_order_unit(symbol)

    # 損切りチェック（シグナルより優先）
    if crypto_balance > min_balance and check_stop_loss(
        symbol, current_price, symbol_config.stop_loss_percent
    ):
        amount = Decimal(str(crypto_balance)).quantize(order_unit, rounding=ROUND_DOWN)
        order = exchange.create_market_sell_order(symbol, float(amount))
        balance = exchange.fetch_balance()

        result.action = "sell"
        result.signal = "stop_loss"
        result.amount = amount
        result.order_id = str(order.get("id"))
        result.balance_jpy = float(balance.get("JPY", {}).get("free", 0))
        result.balance_crypto = float(balance.get(crypto, {}).get("free", 0))

        clear_position(symbol)
        logger.warning(f"[{symbol}] Stop loss executed!")

    # シグナルに基づいて取引
    elif signal == Signal.BUY and jpy_balance > 1000:
        jpy_to_use = jpy_balance * symbol_config.max_position_percent
        amount = Decimal(str(jpy_to_use / current_price)).quantize(
            order_unit, rounding=ROUND_DOWN
        )

        min_amount = exchange.get_min_order_amount(symbol)
        if amount >= min_amount:
            order = exchange.create_market_buy_order(symbol, float(amount))
            balance = exchange.fetch_balance()

            result.action = "buy"
            result.amount = amount
            result.order_id = str(order.get("id"))
            result.balance_jpy = float(balance.get("JPY", {}).get("free", 0))
            result.balance_crypto = float(balance.get(crypto, {}).get("free", 0))

            # 購入価格を記録
            save_position(symbol, current_price, float(amount))
            logger.info(f"[{symbol}] Buy executed: {amount} at {current_price}")

    elif signal == Signal.SELL and crypto_balance > min_balance:
        amount = Decimal(str(crypto_balance)).quantize(order_unit, rounding=ROUND_DOWN)
        order = exchange.create_market_sell_order(symbol, float(amount))
        balance = exchange.fetch_balance()

        result.action = "sell"
        result.amount = amount
        result.order_id = str(order.get("id"))
        result.balance_jpy = float(balance.get("JPY", {}).get("free", 0))
        result.balance_crypto = float(balance.get(crypto, {}).get("free", 0))

        # ポジション情報をクリア
        clear_position(symbol)
        logger.info(f"[{symbol}] Sell executed: {amount} at {current_price}")

    logger.info(
        f"[{symbol}] Balance: JPY={jpy_balance:,.0f}, {crypto}={crypto_balance:.8f}"
    )

    return result
