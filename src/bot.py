"""メインBotループモジュール。

複数通貨・通貨別戦略に対応。
"""

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

from src.config import Config, Strategy, SymbolConfig, get_config
from src.data import fetch_ohlcv_as_df
from src.exchange import Exchange
from src.position import check_stop_loss, clear_position, load_position, save_position
from src.strategy import Signal, ma_crossover_signal, rsi_contrarian_signal

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
                "balance_jpy", "balance_crypto", "signal", "order_id"
            ])
        writer.writerow([
            timestamp.isoformat(), action, symbol, str(amount), price,
            balance_jpy, balance_crypto, signal, order_id or ""
        ])


def log_trade(
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
    """取引をログに記録する（CSV + Supabase）。"""
    # CSVに保存（ローカル用）
    log_trade_to_csv(
        timestamp, action, symbol, amount, price,
        balance_jpy, balance_crypto, signal, order_id
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
                balance_btc=balance_crypto,
                signal=signal,
                order_id=order_id,
            )
        except Exception as e:
            logger.warning(f"Failed to save to Supabase: {e}")


def get_crypto_currency(symbol: str) -> str:
    """シンボルから暗号通貨部分を取得する。

    Args:
        symbol: 通貨ペア（例: 'BTC/JPY', 'ETH/JPY'）

    Returns:
        暗号通貨コード（例: 'BTC', 'ETH'）
    """
    return symbol.split("/")[0]


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
) -> None:
    """1つの通貨ペアの取引処理を行う。"""
    symbol = symbol_config.symbol
    crypto = get_crypto_currency(symbol)

    logger.info(f"--- Processing {symbol} ({symbol_config.strategy.value}) ---")

    try:
        # データ取得
        df = fetch_ohlcv_as_df(exchange, symbol, config.timeframe, limit=100)

        # 残高確認
        balance = exchange.fetch_balance()
        jpy_balance = float(balance.get("JPY", {}).get("free", 0))
        crypto_balance = float(balance.get(crypto, {}).get("free", 0))

        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker["last"]

        # ポジション保有状態を確認
        has_position = load_position(symbol) is not None

        # 戦略に応じたシグナル生成
        signal = get_signal_for_symbol(df, symbol_config, has_position)
        logger.info(f"[{symbol}] Signal: {signal.value}")

        # 最小取引量（暗号通貨による）
        min_balance = 0.001 if crypto == "BTC" else 0.01  # ETHは0.01

        # 損切りチェック（シグナルより優先）
        if crypto_balance > min_balance and check_stop_loss(
            symbol, current_price, symbol_config.stop_loss_percent
        ):
            amount = Decimal(str(crypto_balance)).quantize(Decimal("0.00000001"))
            order = exchange.create_market_sell_order(symbol, amount)
            balance = exchange.fetch_balance()
            log_trade(
                timestamp=datetime.now(),
                action="sell",
                symbol=symbol,
                amount=amount,
                price=current_price,
                balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
                balance_crypto=float(balance.get(crypto, {}).get("free", 0)),
                signal="stop_loss",
                order_id=str(order.get("id")),
            )
            clear_position(symbol)
            logger.warning(f"[{symbol}] Stop loss executed!")

        # シグナルに基づいて取引
        elif signal == Signal.BUY and jpy_balance > 1000:
            amount = calculate_buy_amount(
                exchange, symbol, jpy_balance, symbol_config.max_position_percent
            )
            if amount > 0:
                order = exchange.create_market_buy_order(symbol, amount)
                balance = exchange.fetch_balance()
                log_trade(
                    timestamp=datetime.now(),
                    action="buy",
                    symbol=symbol,
                    amount=amount,
                    price=current_price,
                    balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
                    balance_crypto=float(balance.get(crypto, {}).get("free", 0)),
                    signal=signal.value,
                    order_id=str(order.get("id")),
                )
                # 購入価格を記録
                save_position(symbol, current_price, float(amount))
                logger.info(f"[{symbol}] Buy executed: {amount} at {current_price}")

        elif signal == Signal.SELL and crypto_balance > min_balance:
            amount = Decimal(str(crypto_balance)).quantize(Decimal("0.00000001"))
            order = exchange.create_market_sell_order(symbol, amount)
            balance = exchange.fetch_balance()
            log_trade(
                timestamp=datetime.now(),
                action="sell",
                symbol=symbol,
                amount=amount,
                price=current_price,
                balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
                balance_crypto=float(balance.get(crypto, {}).get("free", 0)),
                signal=signal.value,
                order_id=str(order.get("id")),
            )
            # ポジション情報をクリア
            clear_position(symbol)
            logger.info(f"[{symbol}] Sell executed: {amount} at {current_price}")

        logger.info(f"[{symbol}] Balance: JPY={jpy_balance:,.0f}, {crypto}={crypto_balance:.8f}")

    except Exception as e:
        logger.error(f"[{symbol}] Error: {e}")


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
            logger.info(f"    RSI: period={sc.rsi_period}, oversold={sc.rsi_oversold}, overbought={sc.rsi_overbought}")
        else:
            logger.info(f"    MA: short={sc.ma_short_period}, long={sc.ma_long_period}")
        logger.info(f"    Max position: {sc.max_position_percent * 100}%, Stop loss: {sc.stop_loss_percent * 100}%")
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
                process_symbol(exchange, config, symbol_config)

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
