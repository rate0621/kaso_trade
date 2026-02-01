"""Vercel Cron用のトレードエンドポイント。

複数通貨・通貨別戦略に対応。
"""

import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.exchange import Exchange
from src.trading import (
    TradeResult,
    get_crypto_currency,
    is_supabase_configured,
    process_symbol,
)


def save_trade_to_db(result: TradeResult) -> None:
    """取引をSupabaseに保存する。"""
    if result.action == "none" or result.amount is None:
        return

    if not is_supabase_configured():
        return

    try:
        from src.database import save_trade_log

        save_trade_log(
            timestamp=datetime.now(),
            environment="production",
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
        # ログ保存失敗しても取引自体は成功しているので継続
        print(f"Warning: Failed to save to Supabase: {e}")


def result_to_dict(result: TradeResult) -> dict:
    """TradeResultを辞書に変換する。"""
    crypto = get_crypto_currency(result.symbol)
    data = {
        "symbol": result.symbol,
        "strategy": result.strategy,
        "signal": result.signal,
        "trend": result.trend,
        "price": result.price,
        "balance_jpy": result.balance_jpy,
        f"balance_{crypto.lower()}": result.balance_crypto,
        "action": result.action,
        "has_position": result.has_position,
    }
    if result.amount is not None:
        data["amount"] = str(result.amount)
    if result.order_id is not None:
        data["order_id"] = result.order_id
    return data


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
            result = process_symbol(exchange, config, symbol_config)
            save_trade_to_db(result)
            results["symbols"].append(result_to_dict(result))
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
