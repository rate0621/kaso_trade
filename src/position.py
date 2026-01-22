"""ポジション管理モジュール。

購入価格を記録し、損切り判定に使用する。
ローカル実行時はJSONファイル、Vercel実行時はSupabaseに保存。
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

POSITION_FILE = Path(__file__).parent.parent / "logs" / "position.json"


@dataclass
class Position:
    """ポジション情報。"""

    symbol: str
    entry_price: float
    amount: float
    entry_time: str


def save_position_local(position: Position) -> None:
    """ポジションをローカルファイルに保存する。"""
    POSITION_FILE.parent.mkdir(exist_ok=True)
    with open(POSITION_FILE, "w") as f:
        json.dump(asdict(position), f, indent=2)
    logger.info(f"Position saved: {position.symbol} @ {position.entry_price}")


def load_position_local(symbol: str) -> Optional[Position]:
    """ローカルファイルからポジションを読み込む。"""
    if not POSITION_FILE.exists():
        return None
    try:
        with open(POSITION_FILE) as f:
            data = json.load(f)
        if data.get("symbol") == symbol:
            return Position(**data)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to load position: {e}")
    return None


def clear_position_local() -> None:
    """ローカルのポジション情報を削除する。"""
    if POSITION_FILE.exists():
        POSITION_FILE.unlink()
        logger.info("Position cleared")


def is_supabase_configured() -> bool:
    """Supabaseが設定されているか確認する。"""
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def save_position_supabase(position: Position) -> None:
    """ポジションをSupabaseに保存する。"""
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    client = create_client(url, key)

    # 既存のポジションを削除してから保存
    client.table("positions").delete().eq("symbol", position.symbol).execute()
    client.table("positions").insert(asdict(position)).execute()
    logger.info(f"Position saved to Supabase: {position.symbol} @ {position.entry_price}")


def load_position_supabase(symbol: str) -> Optional[Position]:
    """Supabaseからポジションを読み込む。"""
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    client = create_client(url, key)

    # 必要なカラムのみ取得（idは除外）
    result = client.table("positions").select("symbol, entry_price, amount, entry_time").eq("symbol", symbol).execute()
    if result.data:
        return Position(**result.data[0])
    return None


def clear_position_supabase(symbol: str) -> None:
    """Supabaseのポジション情報を削除する。"""
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    client = create_client(url, key)

    client.table("positions").delete().eq("symbol", symbol).execute()
    logger.info("Position cleared from Supabase")


def save_position(symbol: str, entry_price: float, amount: float) -> None:
    """ポジションを保存する。"""
    position = Position(
        symbol=symbol,
        entry_price=entry_price,
        amount=amount,
        entry_time=datetime.now().isoformat(),
    )
    if is_supabase_configured():
        try:
            save_position_supabase(position)
        except Exception as e:
            logger.warning(f"Failed to save to Supabase, using local: {e}")
            save_position_local(position)
    else:
        save_position_local(position)


def load_position(symbol: str) -> Optional[Position]:
    """ポジションを読み込む。"""
    if is_supabase_configured():
        try:
            return load_position_supabase(symbol)
        except Exception as e:
            logger.warning(f"Failed to load from Supabase, using local: {e}")
            return load_position_local(symbol)
    return load_position_local(symbol)


def clear_position(symbol: str) -> None:
    """ポジション情報を削除する。"""
    if is_supabase_configured():
        try:
            clear_position_supabase(symbol)
        except Exception as e:
            logger.warning(f"Failed to clear from Supabase, using local: {e}")
            clear_position_local()
    else:
        clear_position_local()


def check_stop_loss(symbol: str, current_price: float, stop_loss_percent: float) -> bool:
    """損切り条件をチェックする。

    Args:
        symbol: 通貨ペア
        current_price: 現在価格
        stop_loss_percent: 損切りパーセンテージ（0.10 = 10%）

    Returns:
        損切りすべき場合はTrue
    """
    position = load_position(symbol)
    if position is None:
        return False

    drop_percent = (position.entry_price - current_price) / position.entry_price

    if drop_percent >= stop_loss_percent:
        logger.warning(
            f"STOP LOSS triggered: entry={position.entry_price:.0f}, "
            f"current={current_price:.0f}, drop={drop_percent*100:.1f}%"
        )
        return True

    return False
