"""設定管理モジュール。

環境変数から設定を読み込む。
bitFlyerにはテストネットがないため、本番環境のみ。
複数通貨・通貨別戦略に対応。
"""

import os
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv

# .envファイルがあれば読み込む（ローカル開発用）
load_dotenv()


class Strategy(Enum):
    """取引戦略。"""
    RSI_CONTRARIAN = "rsi_contrarian"  # RSI逆張り
    MA_CROSSOVER = "ma_crossover"  # 移動平均クロスオーバー順張り


@dataclass(frozen=True)
class SymbolConfig:
    """通貨ペアごとの設定。"""
    symbol: str  # 例: "BTC/JPY"
    strategy: Strategy  # 使用する戦略
    max_position_percent: float  # 最大ポジション割合
    stop_loss_percent: float  # 損切りライン

    # RSI設定（RSI_CONTRARIAN戦略用）
    rsi_period: int = 14
    rsi_oversold: int = 30
    rsi_overbought: int = 70

    # 移動平均設定（MA_CROSSOVER戦略用）
    ma_short_period: int = 25
    ma_long_period: int = 75


@dataclass(frozen=True)
class Config:
    """アプリケーション設定。"""

    # APIキー
    api_key: str
    api_secret: str

    # 共通設定
    timeframe: str

    # 通貨ペアごとの設定リスト
    symbols: list[SymbolConfig]


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

    # 通貨ペアごとの設定を読み込む
    symbols = _load_symbol_configs()

    return Config(
        api_key=api_key,
        api_secret=api_secret,
        timeframe=os.environ.get("TIMEFRAME", "1h"),
        symbols=symbols,
    )


def _load_symbol_configs() -> list[SymbolConfig]:
    """通貨ペアごとの設定を読み込む。

    環境変数の形式:
    - SYMBOLS=BTC/JPY,ETH/JPY  # 取引する通貨ペアのカンマ区切りリスト
    - BTC_STRATEGY=rsi_contrarian  # 戦略
    - BTC_MAX_POSITION_PERCENT=0.35
    - BTC_STOP_LOSS_PERCENT=0.10
    - BTC_RSI_PERIOD=14
    - BTC_RSI_OVERSOLD=30
    - BTC_RSI_OVERBOUGHT=70
    - ETH_STRATEGY=ma_crossover
    - ETH_MA_SHORT_PERIOD=25
    - ETH_MA_LONG_PERIOD=75
    """
    symbols_str = os.environ.get("SYMBOLS", "BTC/JPY")
    symbol_list = [s.strip() for s in symbols_str.split(",")]

    configs = []
    for symbol in symbol_list:
        # BTC/JPY → BTC
        prefix = symbol.split("/")[0].upper()

        # 戦略を取得
        strategy_str = os.environ.get(f"{prefix}_STRATEGY", "rsi_contrarian")
        strategy = Strategy(strategy_str)

        # 共通設定
        max_position = float(os.environ.get(
            f"{prefix}_MAX_POSITION_PERCENT",
            os.environ.get("MAX_POSITION_PERCENT", "0.35")
        ))
        stop_loss = float(os.environ.get(
            f"{prefix}_STOP_LOSS_PERCENT",
            os.environ.get("STOP_LOSS_PERCENT", "0.10")
        ))

        # RSI設定
        rsi_period = int(os.environ.get(
            f"{prefix}_RSI_PERIOD",
            os.environ.get("RSI_PERIOD", "14")
        ))
        rsi_oversold = int(os.environ.get(
            f"{prefix}_RSI_OVERSOLD",
            os.environ.get("RSI_OVERSOLD", "30")
        ))
        rsi_overbought = int(os.environ.get(
            f"{prefix}_RSI_OVERBOUGHT",
            os.environ.get("RSI_OVERBOUGHT", "70")
        ))

        # MA設定
        ma_short = int(os.environ.get(
            f"{prefix}_MA_SHORT_PERIOD",
            os.environ.get("MA_SHORT_PERIOD", "25")
        ))
        ma_long = int(os.environ.get(
            f"{prefix}_MA_LONG_PERIOD",
            os.environ.get("MA_LONG_PERIOD", "75")
        ))

        configs.append(SymbolConfig(
            symbol=symbol,
            strategy=strategy,
            max_position_percent=max_position,
            stop_loss_percent=stop_loss,
            rsi_period=rsi_period,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            ma_short_period=ma_short,
            ma_long_period=ma_long,
        ))

    return configs


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
