"""戦略モジュールのテスト。"""

import pandas as pd
import pytest

from src.strategy import Signal, ma_crossover_signal, rsi_contrarian_signal


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


class TestRSIContrarianSignal:
    """RSI逆張り戦略シグナルのテスト。"""

    def test_oversold_buy(self):
        """売られすぎ（RSI<30）でBUYシグナルが出ること。"""
        # 大きく下落するパターン（RSIが30未満になる）
        prices = [100] * 20 + [95, 90, 85, 80, 75, 70, 65, 60, 55, 50]
        df = create_test_df(prices)
        signal = rsi_contrarian_signal(df, period=14, oversold=30, overbought=70, has_position=False)
        assert signal == Signal.BUY

    def test_overbought_sell(self):
        """買われすぎ（RSI>70）でSELLシグナルが出ること（ポジションあり）。"""
        # 大きく上昇するパターン（RSIが70超になる）
        prices = [100] * 20 + [105, 110, 115, 120, 125, 130, 135, 140, 145, 150]
        df = create_test_df(prices)
        signal = rsi_contrarian_signal(df, period=14, oversold=30, overbought=70, has_position=True)
        assert signal == Signal.SELL

    def test_no_position_no_sell(self):
        """ポジションなしでは買われすぎでもSELLシグナルが出ないこと。"""
        # RSIが70超でもポジションがなければ売らない
        prices = [100] * 20 + [105, 110, 115, 120, 125, 130, 135, 140, 145, 150]
        df = create_test_df(prices)
        signal = rsi_contrarian_signal(df, period=14, oversold=30, overbought=70, has_position=False)
        assert signal == Signal.HOLD

    def test_has_position_no_buy(self):
        """ポジションありでは売られすぎでもBUYシグナルが出ないこと。"""
        # RSIが30未満でもポジションがあれば買わない（売りシグナルを待つ）
        prices = [100] * 20 + [95, 90, 85, 80, 75, 70, 65, 60, 55, 50]
        df = create_test_df(prices)
        signal = rsi_contrarian_signal(df, period=14, oversold=30, overbought=70, has_position=True)
        assert signal == Signal.HOLD

    def test_neutral_hold(self):
        """RSIが30-70の間ではHOLDシグナルが出ること。"""
        prices = [100] * 30  # 横ばい（RSI≒50）
        df = create_test_df(prices)
        signal = rsi_contrarian_signal(df, period=14, oversold=30, overbought=70, has_position=False)
        assert signal == Signal.HOLD

    def test_insufficient_data(self):
        """データ不足時はHOLDシグナルが出ること。"""
        prices = [100] * 5  # 短すぎ
        df = create_test_df(prices)
        signal = rsi_contrarian_signal(df, period=14, oversold=30, overbought=70, has_position=False)
        assert signal == Signal.HOLD
