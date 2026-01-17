"""メインBotループモジュール。"""

import csv
import logging
import os
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.data import fetch_ohlcv_as_df
from src.exchange import Exchange
from src.position import check_stop_loss, clear_position, save_position
from src.strategy import Signal, ma_crossover_signal

logger = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parent.parent / "logs"
TRADES_LOG = LOGS_DIR / "trades.csv"


def setup_logging() -> None:
    """ロギングを設定する。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
        ]
    )


def is_supabase_configured() -> bool:
    """Supabaseが設定されているか確認する。"""
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def log_trade_to_csv(
    timestamp: datetime,
    action: str,
    symbol: str,
    amount: Decimal,
    price: float,
    balance_jpy: float,
    balance_btc: float,
    signal: str,
    order_id: str | None = None,
) -> None:
    """取引をCSVに記録する。"""
    LOGS_DIR.mkdir(exist_ok=True)

    file_exists = TRADES_LOG.exists()
    with open(TRADES_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "action", "symbol", "amount", "price",
                "balance_jpy", "balance_btc", "signal", "order_id"
            ])
        writer.writerow([
            timestamp.isoformat(), action, symbol, str(amount), price,
            balance_jpy, balance_btc, signal, order_id or ""
        ])


def log_trade(
    timestamp: datetime,
    action: str,
    symbol: str,
    amount: Decimal,
    price: float,
    balance_jpy: float,
    balance_btc: float,
    signal: str,
    order_id: str | None = None,
) -> None:
    """取引をログに記録する（CSV + Supabase）。"""
    # CSVに保存（ローカル用）
    log_trade_to_csv(
        timestamp, action, symbol, amount, price,
        balance_jpy, balance_btc, signal, order_id
    )

    # Supabaseに保存（設定されている場合）
    if is_supabase_configured():
        try:
            from src.database import save_trade_log
            save_trade_log(
                timestamp=timestamp,
                environment="production",  # bitFlyerは本番のみ
                action=action,
                symbol=symbol,
                amount=amount,
                price=price,
                balance_usdt=balance_jpy,  # JPYをUSDTカラムに保存
                balance_btc=balance_btc,
                signal=signal,
                order_id=order_id,
            )
        except Exception as e:
            logger.warning(f"Failed to save to Supabase: {e}")


def calculate_buy_amount(
    exchange: Exchange,
    symbol: str,
    jpy_balance: float,
    max_position_percent: float,
) -> Decimal:
    """購入数量を計算する。"""
    ticker = exchange.fetch_ticker(symbol)
    price = ticker["last"]

    jpy_to_use = jpy_balance * max_position_percent
    amount = Decimal(str(jpy_to_use / price))

    min_amount = exchange.get_min_order_amount(symbol)
    if amount < min_amount:
        logger.warning(f"Calculated amount {amount} is less than minimum {min_amount}")
        return Decimal("0")

    # bitFlyerは小数点以下8桁まで
    return amount.quantize(Decimal("0.00000001"))


def run_bot(interval_seconds: int = 3600) -> None:
    """Botメインループを実行する。"""
    setup_logging()

    config = get_config()

    logger.info("=" * 50)
    logger.info("Starting trading bot (bitFlyer)...")
    logger.info(f"Symbol: {config.symbol}")
    logger.info(f"Timeframe: {config.timeframe}")
    logger.info(f"MA periods: {config.ma_short_period}/{config.ma_long_period}")
    logger.info(f"Max position: {config.max_position_percent * 100}%")
    logger.info(f"Stop loss: {config.stop_loss_percent * 100}%")
    logger.info(f"Supabase: {'Enabled' if is_supabase_configured() else 'Disabled (CSV only)'}")
    logger.info("=" * 50)

    logger.warning("!!! TRADING WITH REAL MONEY (bitFlyer) !!!")
    logger.warning("Press Ctrl+C within 10 seconds to cancel...")
    time.sleep(10)

    exchange = Exchange.from_config(config)

    while True:
        try:
            # データ取得
            df = fetch_ohlcv_as_df(exchange, config.symbol, config.timeframe, limit=100)

            # シグナル生成
            signal = ma_crossover_signal(
                df,
                short_period=config.ma_short_period,
                long_period=config.ma_long_period,
            )
            logger.info(f"Signal: {signal.value}")

            # 残高確認
            balance = exchange.fetch_balance()
            jpy_balance = float(balance.get("JPY", {}).get("free", 0))
            btc_balance = float(balance.get("BTC", {}).get("free", 0))

            ticker = exchange.fetch_ticker(config.symbol)
            current_price = ticker["last"]

            # 損切りチェック（シグナルより優先）
            if btc_balance > 0.001 and check_stop_loss(
                config.symbol, current_price, config.stop_loss_percent
            ):
                amount = Decimal(str(btc_balance)).quantize(Decimal("0.00000001"))
                order = exchange.create_market_sell_order(config.symbol, amount)
                balance = exchange.fetch_balance()
                log_trade(
                    timestamp=datetime.now(),
                    action="sell",
                    symbol=config.symbol,
                    amount=amount,
                    price=current_price,
                    balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
                    balance_btc=float(balance.get("BTC", {}).get("free", 0)),
                    signal="stop_loss",
                    order_id=str(order.get("id")),
                )
                clear_position(config.symbol)

            # シグナルに基づいて取引
            # 最低取引額: 約15,000円（0.001 BTC × 1500万円として）
            elif signal == Signal.BUY and jpy_balance > 1000:
                amount = calculate_buy_amount(
                    exchange, config.symbol, jpy_balance, config.max_position_percent
                )
                if amount > 0:
                    order = exchange.create_market_buy_order(config.symbol, amount)
                    balance = exchange.fetch_balance()
                    log_trade(
                        timestamp=datetime.now(),
                        action="buy",
                        symbol=config.symbol,
                        amount=amount,
                        price=current_price,
                        balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
                        balance_btc=float(balance.get("BTC", {}).get("free", 0)),
                        signal=signal.value,
                        order_id=str(order.get("id")),
                    )
                    # 購入価格を記録
                    save_position(config.symbol, current_price, float(amount))

            elif signal == Signal.SELL and btc_balance > 0.001:
                amount = Decimal(str(btc_balance)).quantize(Decimal("0.00000001"))
                order = exchange.create_market_sell_order(config.symbol, amount)
                balance = exchange.fetch_balance()
                log_trade(
                    timestamp=datetime.now(),
                    action="sell",
                    symbol=config.symbol,
                    amount=amount,
                    price=current_price,
                    balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
                    balance_btc=float(balance.get("BTC", {}).get("free", 0)),
                    signal=signal.value,
                    order_id=str(order.get("id")),
                )
                # ポジション情報をクリア
                clear_position(config.symbol)

            logger.info(f"Balance: JPY={jpy_balance:,.0f}, BTC={btc_balance:.8f}")
            logger.info(f"Sleeping for {interval_seconds} seconds...")
            time.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    run_bot()
