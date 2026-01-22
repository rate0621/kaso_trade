"""bitFlyerの市場情報と残高を確認するスクリプト。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.exchange import Exchange


def main():
    config = get_config()
    exchange = Exchange.from_config(config)

    # 市場情報を取得
    exchange.exchange.load_markets()

    print("=== 利用可能なマーケット ===")
    for symbol in exchange.exchange.symbols:
        print(f"  {symbol}")
    print()

    print("=== BTC/JPY 市場情報（生データ） ===")
    market = exchange.exchange.market("BTC/JPY")
    for key, value in market.items():
        print(f"  {key}: {value}")
    print()

    # 残高を取得
    print("=== 残高 ===")
    balance = exchange.fetch_balance()
    print(f"JPY (free): {balance.get('JPY', {}).get('free', 0)}")
    print(f"JPY (used): {balance.get('JPY', {}).get('used', 0)}")
    print(f"BTC (free): {balance.get('BTC', {}).get('free', 0)}")
    print(f"BTC (used): {balance.get('BTC', {}).get('used', 0)}")
    print()

    # 小額の売り注文をテスト（実行せず確認のみ）
    print("=== 売り注文テスト ===")
    btc_balance = balance.get('BTC', {}).get('free', 0)
    print(f"売却予定量: {btc_balance} BTC")

    # 最小注文量の確認（bitFlyerの公式ドキュメントより）
    print("bitFlyer Lightning BTC/JPY 最小注文量: 0.001 BTC")
    print(f"残高 >= 0.001: {btc_balance >= 0.001}")
    print()

    # 実際に売り注文を試す（少量でテスト）
    print("=== 売り注文を実行しますか？ ===")
    print(f"  売却量: {btc_balance} BTC")
    answer = input("実行する場合は 'yes' を入力: ")
    if answer.lower() == "yes":
        try:
            order = exchange.exchange.create_market_sell_order("BTC/JPY", btc_balance)
            print(f"成功: {order}")
        except Exception as e:
            print(f"エラー: {e}")
            print()
            print("=== 0.001 BTCで再試行 ===")
            retry = input("0.001 BTCで試しますか？ 'yes' を入力: ")
            if retry.lower() == "yes":
                try:
                    order = exchange.exchange.create_market_sell_order("BTC/JPY", 0.001)
                    print(f"成功: {order}")
                except Exception as e2:
                    print(f"エラー: {e2}")


if __name__ == "__main__":
    main()
