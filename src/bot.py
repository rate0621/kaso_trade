"""メインBotループモジュール。

複数通貨・通貨別戦略に対応。
"""

import csv
import logging
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Strategy, get_config
from src.exchange import Exchange
from src.trading import (
    TradeResult,
    get_crypto_currency,
    is_supabase_configured,
    process_symbol,
)

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
        ],
    )


def log_trade_to_csv(
    timestamp: datetime,
    action: str,
    symbol: str,
    amount: Decimal,
    price: float,
    balance_jpy: float,
    balance_crypto: float,
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
                "balance_jpy", "balance_crypto", "signal", "order_id",
            ])
        writer.writerow([
            timestamp.isoformat(), action, symbol, str(amount), price,
            balance_jpy, balance_crypto, signal, order_id or "",
        ])


def log_trade(result: TradeResult) -> None:
    """取引をログに記録する（CSV + Supabase）。"""
    if result.action == "none" or result.amount is None:
        return

    timestamp = datetime.now()

    # CSVに保存（ローカル用）
    log_trade_to_csv(
        timestamp=timestamp,
        action=result.action,
        symbol=result.symbol,
        amount=result.amount,
        price=result.price,
        balance_jpy=result.balance_jpy,
        balance_crypto=result.balance_crypto,
        signal=result.signal,
        order_id=result.order_id,
    )

    # Supabaseに保存（設定されている場合）
    if is_supabase_configured():
        try:
            from src.database import save_trade_log

            save_trade_log(
                timestamp=timestamp,
                environment="production",  # bitFlyerは本番のみ
                action=result.action,
                symbol=result.symbol,
                amount=result.amount,
                price=result.price,
                balance_usdt=result.balance_jpy,  # JPYをUSDTカラムに保存
                balance_btc=result.balance_crypto,
                signal=result.signal,
                order_id=result.order_id,
            )
        except Exception as e:
            logger.warning(f"Failed to save to Supabase: {e}")


def run_bot(interval_seconds: int = 3600) -> None:
    """Botメインループを実行する。"""
    setup_logging()

    config = get_config()

    logger.info("=" * 60)
    logger.info("Starting multi-currency trading bot (bitFlyer)...")
    logger.info(f"Timeframe: {config.timeframe}")
    logger.info(f"Supabase: {'Enabled' if is_supabase_configured() else 'Disabled (CSV only)'}")
    logger.info("-" * 60)
    for sc in config.symbols:
        logger.info(f"  {sc.symbol}: {sc.strategy.value}")
        if sc.strategy == Strategy.RSI_CONTRARIAN:
            logger.info(
                f"    RSI: period={sc.rsi_period}, "
                f"oversold={sc.rsi_oversold}, overbought={sc.rsi_overbought}"
            )
        else:
            logger.info(f"    MA: short={sc.ma_short_period}, long={sc.ma_long_period}")
        logger.info(
            f"    Max position: {sc.max_position_percent * 100}%, "
            f"Stop loss: {sc.stop_loss_percent * 100}%"
        )
    logger.info("=" * 60)

    logger.warning("!!! TRADING WITH REAL MONEY (bitFlyer) !!!")
    logger.warning("Press Ctrl+C within 10 seconds to cancel...")
    time.sleep(10)

    exchange = Exchange.from_config(config)

    while True:
        try:
            logger.info("=" * 40)
            logger.info(f"Trading cycle started at {datetime.now().isoformat()}")

            # 各通貨ペアを処理
            for symbol_config in config.symbols:
                crypto = get_crypto_currency(symbol_config.symbol)
                logger.info(
                    f"--- Processing {symbol_config.symbol} "
                    f"({symbol_config.strategy.value}) ---"
                )
                try:
                    result = process_symbol(exchange, config, symbol_config)
                    log_trade(result)
                except Exception as e:
                    logger.error(f"[{symbol_config.symbol}] Error: {e}")

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
