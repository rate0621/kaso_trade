"""データベース操作モジュール。

Supabaseを使用して取引ログを保存する。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from supabase import create_client, Client

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_supabase_client() -> Client:
    """Supabaseクライアントを取得する（シングルトン）。

    Returns:
        Supabaseクライアント

    Raises:
        ValueError: 環境変数が設定されていない場合
    """
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")

        if not url or not key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be set. "
                "Get these from your Supabase project settings."
            )

        _client = create_client(url, key)
        logger.info("Supabase client initialized")

    return _client


def save_trade_log(
    timestamp: datetime,
    environment: str,
    action: str,
    symbol: str,
    amount: Decimal,
    price: float,
    balance_usdt: float,
    balance_btc: float,
    signal: str | None = None,
    order_id: str | None = None,
) -> dict:
    """取引ログをデータベースに保存する。

    Args:
        timestamp: 取引時刻
        environment: 実行環境（sandbox/production）
        action: 取引種別（buy/sell/hold）
        symbol: 通貨ペア
        amount: 取引数量
        price: 約定価格
        balance_usdt: 取引後USDT残高
        balance_btc: 取引後BTC残高
        signal: シグナル種別
        order_id: 注文ID

    Returns:
        挿入されたレコード
    """
    client = get_supabase_client()

    data = {
        "timestamp": timestamp.isoformat(),
        "environment": environment,
        "action": action,
        "symbol": symbol,
        "amount": str(amount),
        "price": price,
        "balance_usdt": balance_usdt,
        "balance_btc": balance_btc,
        "signal": signal,
        "order_id": order_id,
    }

    result = client.table("trade_logs").insert(data).execute()
    logger.info(f"Trade log saved: {action} {amount} {symbol} @ {price}")

    return result.data[0] if result.data else {}


def get_trade_logs(
    environment: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """取引ログを取得する。

    Args:
        environment: フィルタする環境（None で全て）
        limit: 取得件数
        offset: オフセット

    Returns:
        取引ログのリスト
    """
    client = get_supabase_client()

    query = client.table("trade_logs").select("*")

    if environment:
        query = query.eq("environment", environment)

    result = (
        query
        .order("timestamp", desc=True)
        .limit(limit)
        .offset(offset)
        .execute()
    )

    return result.data


def get_trade_summary(environment: str | None = None) -> dict:
    """取引サマリーを取得する。

    Args:
        environment: フィルタする環境

    Returns:
        サマリー情報
    """
    logs = get_trade_logs(environment=environment, limit=1000)

    if not logs:
        return {
            "total_trades": 0,
            "buy_count": 0,
            "sell_count": 0,
        }

    buy_count = sum(1 for log in logs if log["action"] == "buy")
    sell_count = sum(1 for log in logs if log["action"] == "sell")

    return {
        "total_trades": len(logs),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "first_trade": logs[-1]["timestamp"] if logs else None,
        "last_trade": logs[0]["timestamp"] if logs else None,
    }
