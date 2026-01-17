#!/usr/bin/env python3
"""接続確認スクリプト。

bitFlyerへの接続と基本操作を確認する。

Usage:
    python scripts/check_connection.py
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.exchange import Exchange
from src.data import fetch_ohlcv_as_df


def main() -> None:
    """接続確認を実行する。"""
    config = get_config()

    print("=" * 50)
    print("bitFlyer 接続確認")
    print("=" * 50)

    # Exchangeインスタンス作成
    exchange = Exchange.from_config(config)

    # 残高確認
    print("\n[残高確認]")
    balance = exchange.fetch_balance()
    jpy_balance = balance.get("JPY", {}).get("free", 0)
    btc_balance = balance.get("BTC", {}).get("free", 0)
    print(f"  JPY: {jpy_balance:,.0f} 円")
    print(f"  BTC: {btc_balance:.8f}")

    # 価格取得
    print("\n[価格取得]")
    ticker = exchange.fetch_ticker(config.symbol)
    print(f"  {config.symbol}: {ticker['last']:,.0f} 円")

    # OHLCV取得（bitbank経由）
    print("\n[OHLCVデータ取得] (via bitbank)")
    df = fetch_ohlcv_as_df(exchange, config.symbol, config.timeframe, limit=5)
    print(f"  最新5本の{config.timeframe}足:")
    for idx, row in df.iterrows():
        print(f"    Open: {row['open']:,.0f} | High: {row['high']:,.0f} | Low: {row['low']:,.0f} | Close: {row['close']:,.0f}")

    print("\n" + "=" * 50)
    print("接続確認完了!")
    print("=" * 50)


if __name__ == "__main__":
    main()
