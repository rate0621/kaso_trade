"""Vercel Cron用のトレードエンドポイント。

複数通貨・通貨別戦略に対応。
"""

import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
import json

from src.config import Config, Strategy, SymbolConfig, get_config
from src.data import fetch_ohlcv_as_df
from src.exchange import Exchange
from src.position import check_stop_loss, clear_position, load_position, save_position
from src.strategy import Signal, ma_crossover_signal, rsi_contrarian_signal


def is_supabase_configured() -> bool:
    """Supabaseが設定されているか確認する。"""
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def save_trade_to_db(
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
    """取引をSupabaseに保存する。"""
    if is_supabase_configured():
        try:
            from src.database import save_trade_log
            save_trade_log(
                timestamp=timestamp,
                environment="production",
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
            # ログ保存失敗しても取引自体は成功しているので継続
            print(f"Warning: Failed to save to Supabase: {e}")


def get_crypto_currency(symbol: str) -> str:
    """シンボルから暗号通貨部分を取得する。"""
    return symbol.split("/")[0]


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
        return Signal.HOLD


def process_symbol(
    exchange: Exchange,
    config: Config,
    symbol_config: SymbolConfig,
) -> dict:
    """1つの通貨ペアの取引処理を行い、結果を返す。"""
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

    # ポジション保有状態を確認
    has_position = load_position(symbol) is not None

    # 戦略に応じたシグナル生成
    signal = get_signal_for_symbol(df, symbol_config, has_position)

    result = {
        "symbol": symbol,
        "strategy": symbol_config.strategy.value,
        "signal": signal.value,
        "price": current_price,
        "balance_jpy": jpy_balance,
        f"balance_{crypto.lower()}": crypto_balance,
        "action": "none",
        "has_position": has_position,
    }

    # 最小取引量（暗号通貨による）
    min_balance = 0.001 if crypto == "BTC" else 0.01  # ETHは0.01

    # 損切りチェック（シグナルより優先）
    if crypto_balance > min_balance and check_stop_loss(
        symbol, current_price, symbol_config.stop_loss_percent
    ):
        amount = Decimal(str(crypto_balance)).quantize(Decimal("0.00000001"))
        order = exchange.create_market_sell_order(symbol, float(amount))
        balance = exchange.fetch_balance()

        result["action"] = "sell"
        result["amount"] = str(amount)
        result["order_id"] = str(order["id"])
        result["signal"] = "stop_loss"

        save_trade_to_db(
            timestamp=datetime.now(),
            action="sell",
            symbol=symbol,
            amount=amount,
            price=current_price,
            balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
            balance_crypto=float(balance.get(crypto, {}).get("free", 0)),
            signal="stop_loss",
            order_id=str(order["id"]),
        )
        clear_position(symbol)

    # シグナルに基づいて取引
    elif signal == Signal.BUY and jpy_balance > 1000:
        jpy_to_use = jpy_balance * symbol_config.max_position_percent
        amount = Decimal(str(jpy_to_use / current_price)).quantize(Decimal("0.00000001"))

        min_amount = exchange.get_min_order_amount(symbol)
        if amount >= min_amount:
            order = exchange.create_market_buy_order(symbol, float(amount))
            balance = exchange.fetch_balance()

            result["action"] = "buy"
            result["amount"] = str(amount)
            result["order_id"] = str(order["id"])

            save_trade_to_db(
                timestamp=datetime.now(),
                action="buy",
                symbol=symbol,
                amount=amount,
                price=current_price,
                balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
                balance_crypto=float(balance.get(crypto, {}).get("free", 0)),
                signal=signal.value,
                order_id=str(order["id"]),
            )
            # 購入価格を記録
            save_position(symbol, current_price, float(amount))

    elif signal == Signal.SELL and crypto_balance > min_balance:
        amount = Decimal(str(crypto_balance)).quantize(Decimal("0.00000001"))
        order = exchange.create_market_sell_order(symbol, float(amount))
        balance = exchange.fetch_balance()

        result["action"] = "sell"
        result["amount"] = str(amount)
        result["order_id"] = str(order["id"])

        save_trade_to_db(
            timestamp=datetime.now(),
            action="sell",
            symbol=symbol,
            amount=amount,
            price=current_price,
            balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
            balance_crypto=float(balance.get(crypto, {}).get("free", 0)),
            signal=signal.value,
            order_id=str(order["id"]),
        )
        # ポジション情報をクリア
        clear_position(symbol)

    return result


def run_trading_cycle() -> dict:
    """1回のトレードサイクルを実行する（全通貨ペア）。

    Returns:
        取引結果の辞書
    """
    config = get_config()
    exchange = Exchange.from_config(config)

    results = {
        "timestamp": datetime.now().isoformat(),
        "exchange": "bitflyer",
        "supabase_enabled": is_supabase_configured(),
        "symbols": [],
    }

    # 各通貨ペアを処理
    for symbol_config in config.symbols:
        try:
            symbol_result = process_symbol(exchange, config, symbol_config)
            results["symbols"].append(symbol_result)
        except Exception as e:
            results["symbols"].append({
                "symbol": symbol_config.symbol,
                "error": str(e),
            })

    return results


class handler(BaseHTTPRequestHandler):
    """Vercelサーバーレス関数のハンドラー。"""

    def do_GET(self):
        """GETリクエストを処理する。"""
        try:
            result = run_trading_cycle()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, indent=2).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
