"""Vercel Cron用のトレードエンドポイント。"""

import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
import json

from src.config import get_config
from src.data import fetch_ohlcv_as_df
from src.exchange import Exchange
from src.position import check_stop_loss, clear_position, load_position, save_position
from src.strategy import Signal, rsi_contrarian_signal


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
    balance_btc: float,
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
                balance_btc=balance_btc,
                signal=signal,
                order_id=order_id,
            )
        except Exception as e:
            # ログ保存失敗しても取引自体は成功しているので継続
            print(f"Warning: Failed to save to Supabase: {e}")


def run_trading_cycle() -> dict:
    """1回のトレードサイクルを実行する。

    Returns:
        取引結果の辞書
    """
    config = get_config()
    exchange = Exchange.from_config(config)

    # データ取得（bitbankから取得）
    df = fetch_ohlcv_as_df(exchange, config.symbol, config.timeframe, limit=100)

    # 残高確認
    balance = exchange.fetch_balance()
    jpy_balance = float(balance.get("JPY", {}).get("free", 0))
    btc_balance = float(balance.get("BTC", {}).get("free", 0))

    ticker = exchange.fetch_ticker(config.symbol)
    current_price = ticker["last"]

    # ポジション保有状態を確認
    has_position = load_position(config.symbol) is not None

    # RSI逆張りシグナル生成
    signal = rsi_contrarian_signal(
        df,
        period=config.rsi_period,
        oversold=config.rsi_oversold,
        overbought=config.rsi_overbought,
        has_position=has_position,
    )

    result = {
        "timestamp": datetime.now().isoformat(),
        "exchange": "bitflyer",
        "strategy": "rsi_contrarian",
        "signal": signal.value,
        "price": current_price,
        "balance_jpy": jpy_balance,
        "balance_btc": btc_balance,
        "action": "none",
        "has_position": has_position,
        "supabase_enabled": is_supabase_configured(),
    }

    # 損切りチェック（シグナルより優先）
    if btc_balance > 0.001 and check_stop_loss(
        config.symbol, current_price, config.stop_loss_percent
    ):
        amount = Decimal(str(btc_balance)).quantize(Decimal("0.00000001"))
        order = exchange.create_market_sell_order(config.symbol, float(amount))
        balance = exchange.fetch_balance()

        result["action"] = "sell"
        result["amount"] = str(amount)
        result["order_id"] = str(order["id"])
        result["signal"] = "stop_loss"

        save_trade_to_db(
            timestamp=datetime.now(),
            action="sell",
            symbol=config.symbol,
            amount=amount,
            price=current_price,
            balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
            balance_btc=float(balance.get("BTC", {}).get("free", 0)),
            signal="stop_loss",
            order_id=str(order["id"]),
        )
        clear_position(config.symbol)

    # シグナルに基づいて取引
    elif signal == Signal.BUY and jpy_balance > 1000:
        jpy_to_use = jpy_balance * config.max_position_percent
        amount = Decimal(str(jpy_to_use / current_price)).quantize(Decimal("0.00000001"))

        min_amount = exchange.get_min_order_amount(config.symbol)
        if amount >= min_amount:
            order = exchange.create_market_buy_order(config.symbol, float(amount))
            balance = exchange.fetch_balance()

            result["action"] = "buy"
            result["amount"] = str(amount)
            result["order_id"] = str(order["id"])

            save_trade_to_db(
                timestamp=datetime.now(),
                action="buy",
                symbol=config.symbol,
                amount=amount,
                price=current_price,
                balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
                balance_btc=float(balance.get("BTC", {}).get("free", 0)),
                signal=signal.value,
                order_id=str(order["id"]),
            )
            # 購入価格を記録
            save_position(config.symbol, current_price, float(amount))

    elif signal == Signal.SELL and btc_balance > 0.001:
        amount = Decimal(str(btc_balance)).quantize(Decimal("0.00000001"))
        order = exchange.create_market_sell_order(config.symbol, float(amount))
        balance = exchange.fetch_balance()

        result["action"] = "sell"
        result["amount"] = str(amount)
        result["order_id"] = str(order["id"])

        save_trade_to_db(
            timestamp=datetime.now(),
            action="sell",
            symbol=config.symbol,
            amount=amount,
            price=current_price,
            balance_jpy=float(balance.get("JPY", {}).get("free", 0)),
            balance_btc=float(balance.get("BTC", {}).get("free", 0)),
            signal=signal.value,
            order_id=str(order["id"]),
        )
        # ポジション情報をクリア
        clear_position(config.symbol)

    return result


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
