"""設定管理モジュール。

環境変数から設定を読み込む。
bitFlyerにはテストネットがないため、本番環境のみ。
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# .envファイルがあれば読み込む（ローカル開発用）
load_dotenv()


@dataclass(frozen=True)
class Config:
    """アプリケーション設定。"""

    # APIキー
    api_key: str
    api_secret: str

    # 取引設定
    symbol: str
    timeframe: str
    max_position_percent: float

    # 損切り設定
    stop_loss_percent: float

    # RSI設定
    rsi_period: int
    rsi_oversold: int
    rsi_overbought: int

    # 移動平均設定（レガシー、将来削除予定）
    ma_short_period: int
    ma_long_period: int


def load_config() -> Config:
    """環境変数から設定を読み込む。

    Returns:
        Config: 設定オブジェクト

    Raises:
        ValueError: 必須の環境変数が設定されていない場合
    """
    # APIキー
    api_key = os.environ.get("BITFLYER_API_KEY", "")
    api_secret = os.environ.get("BITFLYER_API_SECRET", "")

    if not api_key or not api_secret:
        raise ValueError(
            "BITFLYER_API_KEY and BITFLYER_API_SECRET must be set. "
            "Create a .env file or set environment variables."
        )

    # 本番取引の確認（安全対策）
    confirm = os.environ.get("CONFIRM_TRADING", "").lower()
    if confirm != "yes":
        raise ValueError(
            "CONFIRM_TRADING=yes must be set to enable trading. "
            "This is a safety measure - bitFlyer has no testnet, "
            "all trades use real money."
        )

    return Config(
        api_key=api_key,
        api_secret=api_secret,
        symbol=os.environ.get("SYMBOL", "BTC/JPY"),
        timeframe=os.environ.get("TIMEFRAME", "1h"),
        max_position_percent=float(os.environ.get("MAX_POSITION_PERCENT", "0.35")),
        stop_loss_percent=float(os.environ.get("STOP_LOSS_PERCENT", "0.10")),
        rsi_period=int(os.environ.get("RSI_PERIOD", "14")),
        rsi_oversold=int(os.environ.get("RSI_OVERSOLD", "30")),
        rsi_overbought=int(os.environ.get("RSI_OVERBOUGHT", "70")),
        ma_short_period=int(os.environ.get("MA_SHORT_PERIOD", "10")),
        ma_long_period=int(os.environ.get("MA_LONG_PERIOD", "20")),
    )


# シングルトンとして設定を保持
_config: Config | None = None


def get_config() -> Config:
    """設定を取得する（遅延読み込み）。

    Returns:
        Config: 設定オブジェクト
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config
