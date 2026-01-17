"""ポジション管理・損切りのテスト。"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.position import (
    Position,
    check_stop_loss,
    clear_position_local,
    load_position_local,
    save_position_local,
)


@pytest.fixture
def temp_position_file(tmp_path):
    """一時的なポジションファイルを使用する。"""
    position_file = tmp_path / "position.json"
    with patch("src.position.POSITION_FILE", position_file):
        yield position_file


class TestPositionLocal:
    """ローカルファイルでのポジション管理テスト。"""

    def test_save_and_load_position(self, temp_position_file):
        """ポジションの保存と読み込みができること。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            position = Position(
                symbol="BTC/JPY",
                entry_price=1000000.0,
                amount=0.01,
                entry_time="2025-01-01T00:00:00",
            )
            save_position_local(position)

            loaded = load_position_local("BTC/JPY")
            assert loaded is not None
            assert loaded.symbol == "BTC/JPY"
            assert loaded.entry_price == 1000000.0
            assert loaded.amount == 0.01

    def test_load_nonexistent_position(self, temp_position_file):
        """存在しないポジションを読み込むとNoneが返ること。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            loaded = load_position_local("BTC/JPY")
            assert loaded is None

    def test_load_different_symbol(self, temp_position_file):
        """異なるシンボルのポジションはNoneが返ること。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            position = Position(
                symbol="ETH/JPY",
                entry_price=500000.0,
                amount=0.1,
                entry_time="2025-01-01T00:00:00",
            )
            save_position_local(position)

            loaded = load_position_local("BTC/JPY")
            assert loaded is None

    def test_clear_position(self, temp_position_file):
        """ポジションのクリアができること。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            position = Position(
                symbol="BTC/JPY",
                entry_price=1000000.0,
                amount=0.01,
                entry_time="2025-01-01T00:00:00",
            )
            save_position_local(position)
            assert temp_position_file.exists()

            clear_position_local()
            assert not temp_position_file.exists()


class TestStopLoss:
    """損切り判定のテスト。"""

    def test_stop_loss_triggered(self, temp_position_file):
        """10%下落で損切りが発動すること。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            # 購入価格: 100万円
            position = Position(
                symbol="BTC/JPY",
                entry_price=1000000.0,
                amount=0.01,
                entry_time="2025-01-01T00:00:00",
            )
            save_position_local(position)

            # 現在価格: 89万円（11%下落）→ 損切り発動
            result = check_stop_loss("BTC/JPY", 890000.0, 0.10)
            assert result is True

    def test_stop_loss_not_triggered(self, temp_position_file):
        """10%未満の下落では損切りが発動しないこと。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            # 購入価格: 100万円
            position = Position(
                symbol="BTC/JPY",
                entry_price=1000000.0,
                amount=0.01,
                entry_time="2025-01-01T00:00:00",
            )
            save_position_local(position)

            # 現在価格: 91万円（9%下落）→ 損切り発動しない
            result = check_stop_loss("BTC/JPY", 910000.0, 0.10)
            assert result is False

    def test_stop_loss_exact_threshold(self, temp_position_file):
        """ちょうど10%下落で損切りが発動すること。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            # 購入価格: 100万円
            position = Position(
                symbol="BTC/JPY",
                entry_price=1000000.0,
                amount=0.01,
                entry_time="2025-01-01T00:00:00",
            )
            save_position_local(position)

            # 現在価格: 90万円（ちょうど10%下落）→ 損切り発動
            result = check_stop_loss("BTC/JPY", 900000.0, 0.10)
            assert result is True

    def test_stop_loss_no_position(self, temp_position_file):
        """ポジションがない場合は損切りが発動しないこと。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            result = check_stop_loss("BTC/JPY", 890000.0, 0.10)
            assert result is False

    def test_stop_loss_price_increase(self, temp_position_file):
        """価格上昇時は損切りが発動しないこと。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            # 購入価格: 100万円
            position = Position(
                symbol="BTC/JPY",
                entry_price=1000000.0,
                amount=0.01,
                entry_time="2025-01-01T00:00:00",
            )
            save_position_local(position)

            # 現在価格: 110万円（10%上昇）→ 損切り発動しない
            result = check_stop_loss("BTC/JPY", 1100000.0, 0.10)
            assert result is False

    def test_stop_loss_custom_percent(self, temp_position_file):
        """カスタム損切りパーセンテージが機能すること。"""
        with patch("src.position.POSITION_FILE", temp_position_file):
            # 購入価格: 100万円
            position = Position(
                symbol="BTC/JPY",
                entry_price=1000000.0,
                amount=0.01,
                entry_time="2025-01-01T00:00:00",
            )
            save_position_local(position)

            # 5%の損切り設定で、6%下落 → 損切り発動
            result = check_stop_loss("BTC/JPY", 940000.0, 0.05)
            assert result is True

            # 5%の損切り設定で、4%下落 → 損切り発動しない
            result = check_stop_loss("BTC/JPY", 960000.0, 0.05)
            assert result is False
