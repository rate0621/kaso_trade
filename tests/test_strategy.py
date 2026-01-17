"""戦略モジュールのテスト。"""

import pandas as pd
import pytest

from src.strategy import Signal, ma_crossover_signal


def create_test_df(prices: list[float]) -> pd.DataFrame:
    """テスト用のDataFrameを作成する。"""
    df = pd.DataFrame({
        "open": prices,
        "high": prices,
        "low": prices,
        "close": prices,
        "volume": [1000] * len(prices),
    })
    return df


class TestMACrossoverSignal:
    """移動平均クロスオーバーシグナルのテスト。"""

    def test_golden_cross(self):
        """ゴールデンクロスでBUYシグナルが出ること。"""
        # 短期MAが長期MAを下から上に抜けるパターン
        # [-2] short=99.4, long=99.8 → short < long
        # [-1] short=101.0, long=100.2 → short > long（クロス発生）
        prices = [100] * 20 + [98, 98, 98, 103, 108]
        df = create_test_df(prices)
        signal = ma_crossover_signal(df, short_period=5, long_period=20)
        assert signal == Signal.BUY

    def test_dead_cross(self):
        """デッドクロスでSELLシグナルが出ること。"""
        # 短期MAが長期MAを上から下に抜けるパターン
        # [-2] short=100.6, long=100.2 → short > long
        # [-1] short=99.0, long=99.8 → short < long（クロス発生）
        prices = [100] * 20 + [102, 102, 102, 97, 92]
        df = create_test_df(prices)
        signal = ma_crossover_signal(df, short_period=5, long_period=20)
        assert signal == Signal.SELL

    def test_no_cross(self):
        """クロスがない場合はHOLDシグナルが出ること。"""
        prices = [100] * 60  # 横ばい
        df = create_test_df(prices)
        signal = ma_crossover_signal(df, short_period=5, long_period=20)
        assert signal == Signal.HOLD

    def test_insufficient_data(self):
        """データ不足時はHOLDシグナルが出ること。"""
        prices = [100] * 10  # 短すぎ
        df = create_test_df(prices)
        signal = ma_crossover_signal(df, short_period=5, long_period=20)
        assert signal == Signal.HOLD
