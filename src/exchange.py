"""取引所接続・注文モジュール。"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import ccxt

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)


class Exchange:
    """bitFlyerへの接続を管理するクラス。"""

    def __init__(self, api_key: str, api_secret: str) -> None:
        """
        Args:
            api_key: bitFlyer APIキー
            api_secret: bitFlyer APIシークレット
        """
        self.exchange = ccxt.bitflyer({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
        })
        logger.warning("bitFlyer connected - Trading with real money!")

    @classmethod
    def from_config(cls, config: Config) -> Exchange:
        """Configから Exchangeインスタンスを作成する。

        Args:
            config: 設定オブジェクト

        Returns:
            Exchangeインスタンス
        """
        return cls(
            api_key=config.api_key,
            api_secret=config.api_secret,
        )

    def fetch_balance(self) -> dict[str, Any]:
        """残高を取得する。

        Returns:
            残高情報の辞書
        """
        balance = self.exchange.fetch_balance()
        jpy = balance.get("JPY", {}).get("free", 0)
        btc = balance.get("BTC", {}).get("free", 0)
        logger.debug(f"Balance fetched: JPY={jpy}, BTC={btc}")
        return balance

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """現在の価格情報を取得する。

        Args:
            symbol: 通貨ペア（例: 'BTC/JPY'）

        Returns:
            価格情報の辞書
        """
        ticker = self.exchange.fetch_ticker(symbol)
        logger.debug(f"Ticker {symbol}: {ticker['last']}")
        return ticker

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> list[list]:
        """OHLCVデータを取得する。

        bitFlyerはOHLCVをサポートしていないため、
        bitbankから同じ通貨ペアのデータを取得する。

        Args:
            symbol: 通貨ペア
            timeframe: 時間足（'1m', '5m', '1h', '1d' など）
            limit: 取得する本数

        Returns:
            OHLCVデータのリスト [[timestamp, open, high, low, close, volume], ...]
        """
        # bitFlyerはOHLCVをサポートしていないためbitbankを使用
        from src.data import get_bitbank
        bitbank = get_bitbank()
        ohlcv = bitbank.fetch_ohlcv(symbol, timeframe, limit=limit)
        logger.debug(f"OHLCV fetched via bitbank: {symbol} {timeframe} x {len(ohlcv)} candles")
        return ohlcv

    def create_market_buy_order(
        self, symbol: str, amount: Decimal
    ) -> dict[str, Any]:
        """成行買い注文を実行する。

        Args:
            symbol: 通貨ペア
            amount: 購入数量

        Returns:
            注文結果
        """
        logger.info(f"Creating market BUY order: {symbol} amount={amount}")
        order = self.exchange.create_market_buy_order(symbol, float(amount))
        logger.info(f"Order executed: id={order['id']} status={order['status']}")
        return order

    def create_market_sell_order(
        self, symbol: str, amount: Decimal
    ) -> dict[str, Any]:
        """成行売り注文を実行する。

        Args:
            symbol: 通貨ペア
            amount: 売却数量

        Returns:
            注文結果
        """
        logger.info(f"Creating market SELL order: {symbol} amount={amount}")
        order = self.exchange.create_market_sell_order(symbol, float(amount))
        logger.info(f"Order executed: id={order['id']} status={order['status']}")
        return order

    def get_min_order_amount(self, symbol: str) -> Decimal:
        """最小注文数量を取得する。

        Args:
            symbol: 通貨ペア

        Returns:
            最小注文数量
        """
        self.exchange.load_markets()
        market = self.exchange.market(symbol)
        min_amount = market.get("limits", {}).get("amount", {}).get("min", 0)
        # bitFlyerのBTC最小注文は0.001 BTC
        return Decimal(str(min_amount)) if min_amount else Decimal("0.001")
