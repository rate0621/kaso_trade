#!/usr/bin/env python3
"""トレンドフィルター追加版バックテストスクリプト。

既存の移動平均クロス戦略にトレンドフィルターを追加して検証する。
- ATRフィルター: ボラティリティが高いときのみエントリー
- ADXフィルター: トレンドが強いときのみエントリー
- 上位足フィルター: 上位足のトレンド方向を確認

Usage:
    python scripts/backtest_trend_filter.py
    python scripts/backtest_trend_filter.py --days 365
    python scripts/backtest_trend_filter.py --verbose
"""

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import ccxt
import numpy as np
import pandas as pd

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backtest import (
    INITIAL_CAPITAL,
    POSITION_PERCENT,
    MIN_TRADE_AMOUNT,
    STOP_LOSS_PERCENT,
    TRADE_FEE_PERCENT,
    fetch_ohlcv_data,
)

# ディレクトリ設定
DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"

# 基本MA設定
MA_SHORT = 20
MA_LONG = 50

# ATRフィルターパラメータ
ATR_PERIODS = [14, 20]
ATR_THRESHOLDS = [1.0, 1.2, 1.5]

# ADXフィルターパラメータ
ADX_PERIODS = [14, 20]
ADX_THRESHOLDS = [20, 25, 30]

# 上位足フィルターパラメータ
HIGHER_TIMEFRAMES = ["4h", "1d"]
HIGHER_MA_SHORT = [10, 20]
HIGHER_MA_LONG = [20, 50]


@dataclass
class TradeResult:
    """個別取引の結果。"""
    entry_price: float
    exit_price: float
    amount: float
    profit: float
    is_stop_loss: bool


@dataclass
class BacktestResult:
    """バックテスト結果。"""
    filter_type: str
    params: str
    profit_rate: float
    win_rate: float
    trades: int
    max_drawdown: float
    profit_factor: float
    stop_loss_count: int
    final_capital: float


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(description="トレンドフィルター追加版バックテスト")
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="取得する日数（デフォルト: 365）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細ログを出力",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="キャッシュを使用しない",
    )
    return parser.parse_args()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR（Average True Range）を計算する。

    TR = max(高値-安値, |高値-前日終値|, |安値-前日終値|)
    ATR = TRのperiod期間移動平均

    Args:
        df: OHLCVデータ
        period: ATR計算期間

    Returns:
        ATR値のSeries
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    return atr


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ADX（Average Directional Index）を計算する。

    Args:
        df: OHLCVデータ
        period: ADX計算期間

    Returns:
        ADX値のSeries
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # +DM, -DM
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Smoothed averages
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)

    # DX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)

    # ADX
    adx = dx.rolling(window=period).mean()

    return adx


def calculate_ma(df: pd.DataFrame, short_period: int, long_period: int) -> pd.DataFrame:
    """移動平均を計算する。"""
    df = df.copy()
    df["ma_short"] = df["close"].rolling(window=short_period).mean()
    df["ma_long"] = df["close"].rolling(window=long_period).mean()
    return df


def run_atr_filter_simulation(
    df: pd.DataFrame,
    atr_period: int,
    atr_threshold: float,
    verbose: bool = False,
) -> BacktestResult:
    """ATRフィルター付きMAクロス戦略のシミュレーションを実行する。"""
    # 移動平均とATRを計算
    df = calculate_ma(df, MA_SHORT, MA_LONG)
    df["atr"] = calculate_atr(df, atr_period)
    df["atr_ma"] = df["atr"].rolling(window=20).mean()

    # 初期状態
    capital = INITIAL_CAPITAL
    btc_amount = 0.0
    entry_price = 0.0
    trades: list[TradeResult] = []
    capital_history = [capital]
    stop_loss_count = 0

    # シミュレーション実行
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]

        # 指標が計算できない期間はスキップ
        if pd.isna(row["ma_short"]) or pd.isna(row["ma_long"]) or pd.isna(row["atr_ma"]):
            continue

        current_price = row["close"]
        atr_condition = row["atr"] > row["atr_ma"] * atr_threshold

        # ポジションを持っている場合
        if btc_amount > 0:
            # 損切りチェック
            drop_percent = (entry_price - current_price) / entry_price
            if drop_percent >= STOP_LOSS_PERCENT:
                sell_value = btc_amount * current_price * (1 - TRADE_FEE_PERCENT)
                profit = sell_value - (btc_amount * entry_price)
                trades.append(TradeResult(
                    entry_price=entry_price,
                    exit_price=current_price,
                    amount=btc_amount,
                    profit=profit,
                    is_stop_loss=True,
                ))
                capital += sell_value
                btc_amount = 0.0
                entry_price = 0.0
                stop_loss_count += 1

            # デッドクロス
            elif (prev_row["ma_short"] >= prev_row["ma_long"] and
                  row["ma_short"] < row["ma_long"]):
                sell_value = btc_amount * current_price * (1 - TRADE_FEE_PERCENT)
                profit = sell_value - (btc_amount * entry_price)
                trades.append(TradeResult(
                    entry_price=entry_price,
                    exit_price=current_price,
                    amount=btc_amount,
                    profit=profit,
                    is_stop_loss=False,
                ))
                capital += sell_value
                btc_amount = 0.0
                entry_price = 0.0

        # ポジションを持っていない場合
        else:
            # ゴールデンクロス + ATR条件
            if (prev_row["ma_short"] <= prev_row["ma_long"] and
                row["ma_short"] > row["ma_long"] and
                atr_condition):
                usdt_to_use = capital * POSITION_PERCENT
                amount = usdt_to_use / current_price * (1 - TRADE_FEE_PERCENT)

                if amount >= MIN_TRADE_AMOUNT:
                    btc_amount = amount
                    entry_price = current_price
                    capital -= usdt_to_use

        # 資産推移を記録
        total_value = capital + btc_amount * current_price
        capital_history.append(total_value)

    # 最終ポジション時価評価
    if btc_amount > 0:
        capital += btc_amount * df.iloc[-1]["close"] * (1 - TRADE_FEE_PERCENT)

    # 評価指標を計算
    profit_rate = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    if trades:
        win_count = sum(1 for t in trades if t.profit > 0)
        win_rate = win_count / len(trades) * 100
        total_profit = sum(t.profit for t in trades if t.profit > 0)
        total_loss = abs(sum(t.profit for t in trades if t.profit < 0))
        profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")
    else:
        win_rate = 0.0
        profit_factor = 0.0

    max_drawdown = 0.0
    peak = capital_history[0]
    for value in capital_history:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return BacktestResult(
        filter_type="ATR",
        params=f"ATR({atr_period}, {atr_threshold})",
        profit_rate=profit_rate,
        win_rate=win_rate,
        trades=len(trades),
        max_drawdown=-max_drawdown,
        profit_factor=profit_factor,
        stop_loss_count=stop_loss_count,
        final_capital=capital,
    )


def run_adx_filter_simulation(
    df: pd.DataFrame,
    adx_period: int,
    adx_threshold: int,
    verbose: bool = False,
) -> BacktestResult:
    """ADXフィルター付きMAクロス戦略のシミュレーションを実行する。"""
    # 移動平均とADXを計算
    df = calculate_ma(df, MA_SHORT, MA_LONG)
    df["adx"] = calculate_adx(df, adx_period)

    # 初期状態
    capital = INITIAL_CAPITAL
    btc_amount = 0.0
    entry_price = 0.0
    trades: list[TradeResult] = []
    capital_history = [capital]
    stop_loss_count = 0

    # シミュレーション実行
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]

        if pd.isna(row["ma_short"]) or pd.isna(row["ma_long"]) or pd.isna(row["adx"]):
            continue

        current_price = row["close"]
        adx_condition = row["adx"] > adx_threshold

        if btc_amount > 0:
            drop_percent = (entry_price - current_price) / entry_price
            if drop_percent >= STOP_LOSS_PERCENT:
                sell_value = btc_amount * current_price * (1 - TRADE_FEE_PERCENT)
                profit = sell_value - (btc_amount * entry_price)
                trades.append(TradeResult(
                    entry_price=entry_price,
                    exit_price=current_price,
                    amount=btc_amount,
                    profit=profit,
                    is_stop_loss=True,
                ))
                capital += sell_value
                btc_amount = 0.0
                entry_price = 0.0
                stop_loss_count += 1

            elif (prev_row["ma_short"] >= prev_row["ma_long"] and
                  row["ma_short"] < row["ma_long"]):
                sell_value = btc_amount * current_price * (1 - TRADE_FEE_PERCENT)
                profit = sell_value - (btc_amount * entry_price)
                trades.append(TradeResult(
                    entry_price=entry_price,
                    exit_price=current_price,
                    amount=btc_amount,
                    profit=profit,
                    is_stop_loss=False,
                ))
                capital += sell_value
                btc_amount = 0.0
                entry_price = 0.0

        else:
            if (prev_row["ma_short"] <= prev_row["ma_long"] and
                row["ma_short"] > row["ma_long"] and
                adx_condition):
                usdt_to_use = capital * POSITION_PERCENT
                amount = usdt_to_use / current_price * (1 - TRADE_FEE_PERCENT)

                if amount >= MIN_TRADE_AMOUNT:
                    btc_amount = amount
                    entry_price = current_price
                    capital -= usdt_to_use

        total_value = capital + btc_amount * current_price
        capital_history.append(total_value)

    if btc_amount > 0:
        capital += btc_amount * df.iloc[-1]["close"] * (1 - TRADE_FEE_PERCENT)

    profit_rate = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    if trades:
        win_count = sum(1 for t in trades if t.profit > 0)
        win_rate = win_count / len(trades) * 100
        total_profit = sum(t.profit for t in trades if t.profit > 0)
        total_loss = abs(sum(t.profit for t in trades if t.profit < 0))
        profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")
    else:
        win_rate = 0.0
        profit_factor = 0.0

    max_drawdown = 0.0
    peak = capital_history[0]
    for value in capital_history:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return BacktestResult(
        filter_type="ADX",
        params=f"ADX({adx_period}, {adx_threshold})",
        profit_rate=profit_rate,
        win_rate=win_rate,
        trades=len(trades),
        max_drawdown=-max_drawdown,
        profit_factor=profit_factor,
        stop_loss_count=stop_loss_count,
        final_capital=capital,
    )


def fetch_higher_timeframe_data(
    timeframe: str,
    days: int,
    use_cache: bool = True,
) -> pd.DataFrame:
    """上位足データを取得する。"""
    cache_file = DATA_DIR / f"btc_usdt_{timeframe}.csv"

    if use_cache and cache_file.exists():
        df = pd.read_csv(cache_file, parse_dates=["datetime"])
        df.set_index("datetime", inplace=True)
        return df

    print(f"  Binanceから{timeframe}データを取得中...")
    exchange = ccxt.binance({"enableRateLimit": True})
    symbol = "BTC/USDT"

    all_ohlcv = []
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    since = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    limit = 500

    while since < end_ms:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except Exception as e:
            print(f"\n  警告: データ取得エラー: {e}")
            break

        if not ohlcv:
            break

        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1
        time.sleep(0.2)

        if len(ohlcv) < limit:
            break

    print(f"  完了: {len(all_ohlcv)}本取得")

    df = pd.DataFrame(
        all_ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("datetime", inplace=True)

    DATA_DIR.mkdir(exist_ok=True)
    df.reset_index().to_csv(cache_file, index=False)

    return df


def run_higher_tf_filter_simulation(
    df_1h: pd.DataFrame,
    df_higher: pd.DataFrame,
    higher_ma_short: int,
    higher_ma_long: int,
    timeframe: str,
    verbose: bool = False,
) -> BacktestResult:
    """上位足フィルター付きMAクロス戦略のシミュレーションを実行する。"""
    # 1時間足の移動平均
    df_1h = calculate_ma(df_1h, MA_SHORT, MA_LONG)

    # 上位足の移動平均
    df_higher = df_higher.copy()
    df_higher["higher_ma_short"] = df_higher["close"].rolling(window=higher_ma_short).mean()
    df_higher["higher_ma_long"] = df_higher["close"].rolling(window=higher_ma_long).mean()

    # 初期状態
    capital = INITIAL_CAPITAL
    btc_amount = 0.0
    entry_price = 0.0
    trades: list[TradeResult] = []
    capital_history = [capital]
    stop_loss_count = 0

    # シミュレーション実行
    for i in range(1, len(df_1h)):
        row = df_1h.iloc[i]
        prev_row = df_1h.iloc[i - 1]

        if pd.isna(row["ma_short"]) or pd.isna(row["ma_long"]):
            continue

        current_price = row["close"]
        current_time = row.name

        # 上位足のトレンド確認
        higher_row = df_higher[df_higher.index <= current_time]
        if len(higher_row) == 0:
            continue
        higher_row = higher_row.iloc[-1]

        if pd.isna(higher_row["higher_ma_short"]) or pd.isna(higher_row["higher_ma_long"]):
            continue

        higher_uptrend = higher_row["higher_ma_short"] > higher_row["higher_ma_long"]

        if btc_amount > 0:
            drop_percent = (entry_price - current_price) / entry_price
            if drop_percent >= STOP_LOSS_PERCENT:
                sell_value = btc_amount * current_price * (1 - TRADE_FEE_PERCENT)
                profit = sell_value - (btc_amount * entry_price)
                trades.append(TradeResult(
                    entry_price=entry_price,
                    exit_price=current_price,
                    amount=btc_amount,
                    profit=profit,
                    is_stop_loss=True,
                ))
                capital += sell_value
                btc_amount = 0.0
                entry_price = 0.0
                stop_loss_count += 1

            elif (prev_row["ma_short"] >= prev_row["ma_long"] and
                  row["ma_short"] < row["ma_long"]):
                sell_value = btc_amount * current_price * (1 - TRADE_FEE_PERCENT)
                profit = sell_value - (btc_amount * entry_price)
                trades.append(TradeResult(
                    entry_price=entry_price,
                    exit_price=current_price,
                    amount=btc_amount,
                    profit=profit,
                    is_stop_loss=False,
                ))
                capital += sell_value
                btc_amount = 0.0
                entry_price = 0.0

        else:
            # ゴールデンクロス + 上位足上昇トレンド
            if (prev_row["ma_short"] <= prev_row["ma_long"] and
                row["ma_short"] > row["ma_long"] and
                higher_uptrend):
                usdt_to_use = capital * POSITION_PERCENT
                amount = usdt_to_use / current_price * (1 - TRADE_FEE_PERCENT)

                if amount >= MIN_TRADE_AMOUNT:
                    btc_amount = amount
                    entry_price = current_price
                    capital -= usdt_to_use

        total_value = capital + btc_amount * current_price
        capital_history.append(total_value)

    if btc_amount > 0:
        capital += btc_amount * df_1h.iloc[-1]["close"] * (1 - TRADE_FEE_PERCENT)

    profit_rate = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    if trades:
        win_count = sum(1 for t in trades if t.profit > 0)
        win_rate = win_count / len(trades) * 100
        total_profit = sum(t.profit for t in trades if t.profit > 0)
        total_loss = abs(sum(t.profit for t in trades if t.profit < 0))
        profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")
    else:
        win_rate = 0.0
        profit_factor = 0.0

    max_drawdown = 0.0
    peak = capital_history[0]
    for value in capital_history:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return BacktestResult(
        filter_type="HigherTF",
        params=f"{timeframe} MA({higher_ma_short}/{higher_ma_long})",
        profit_rate=profit_rate,
        win_rate=win_rate,
        trades=len(trades),
        max_drawdown=-max_drawdown,
        profit_factor=profit_factor,
        stop_loss_count=stop_loss_count,
        final_capital=capital,
    )


def print_results(
    results: list[BacktestResult],
    title: str,
    top_n: int = 5,
) -> None:
    """結果を表示する。"""
    print(f"\n{title}")
    print("=" * 80)

    sorted_results = sorted(results, key=lambda r: r.profit_rate, reverse=True)

    for i, r in enumerate(sorted_results[:top_n], 1):
        pf_str = f"{r.profit_factor:.1f}" if r.profit_factor != float("inf") else "∞"
        print(
            f"{i}. MA({MA_SHORT}/{MA_LONG}) + {r.params}: "
            f"利益率 {r.profit_rate:+6.1f}%, "
            f"勝率 {r.win_rate:4.1f}%, "
            f"取引 {r.trades:3d}回, "
            f"最大DD {r.max_drawdown:5.1f}%, "
            f"PF {pf_str}"
        )


def save_results(results: list[BacktestResult], filename: str) -> None:
    """結果をCSVに保存する。"""
    RESULTS_DIR.mkdir(exist_ok=True)
    filepath = RESULTS_DIR / filename

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "filter_type", "params", "profit_rate", "win_rate", "trades",
            "max_drawdown", "profit_factor", "stop_loss_count", "final_capital"
        ])
        for r in results:
            pf = r.profit_factor if r.profit_factor != float("inf") else 9999
            writer.writerow([
                r.filter_type, r.params,
                f"{r.profit_rate:.2f}", f"{r.win_rate:.2f}",
                r.trades, f"{r.max_drawdown:.2f}", f"{pf:.2f}",
                r.stop_loss_count, f"{r.final_capital:.0f}"
            ])

    print(f"\n結果を保存: {filepath}")


def main() -> None:
    """メイン処理。"""
    args = parse_args()

    print("=" * 80)
    print("トレンドフィルター追加版 バックテスト開始")
    print("=" * 80)
    print(f"基本MA設定: MA({MA_SHORT}/{MA_LONG})")
    print(f"初期資金: {INITIAL_CAPITAL:,} USDT")
    print(f"ポジションサイズ: {POSITION_PERCENT * 100}%")
    print(f"損切りライン: {STOP_LOSS_PERCENT * 100}%")

    # 1時間足データ取得
    print("\n[1] 1時間足データ取得")
    df_1h = fetch_ohlcv_data(days=args.days, use_cache=not args.no_cache, verbose=args.verbose)
    print(f"  期間: {df_1h.index[0]} 〜 {df_1h.index[-1]}")
    print(f"  データ数: {len(df_1h)}本")

    all_results = []

    # ATRフィルター
    print("\n[2] ATRフィルター テスト")
    atr_results = []
    total = len(ATR_PERIODS) * len(ATR_THRESHOLDS)
    current = 0
    for period in ATR_PERIODS:
        for threshold in ATR_THRESHOLDS:
            current += 1
            print(f"\r  テスト中... {current}/{total} (ATR {period}, {threshold})", end="", flush=True)
            result = run_atr_filter_simulation(df_1h, period, threshold, args.verbose)
            atr_results.append(result)
            all_results.append(result)
    print()
    print_results(atr_results, "[ATRフィルター 結果]")

    # ADXフィルター
    print("\n[3] ADXフィルター テスト")
    adx_results = []
    total = len(ADX_PERIODS) * len(ADX_THRESHOLDS)
    current = 0
    for period in ADX_PERIODS:
        for threshold in ADX_THRESHOLDS:
            current += 1
            print(f"\r  テスト中... {current}/{total} (ADX {period}, {threshold})", end="", flush=True)
            result = run_adx_filter_simulation(df_1h, period, threshold, args.verbose)
            adx_results.append(result)
            all_results.append(result)
    print()
    print_results(adx_results, "[ADXフィルター 結果]")

    # 上位足フィルター
    print("\n[4] 上位足フィルター テスト")
    higher_tf_results = []

    for tf in HIGHER_TIMEFRAMES:
        print(f"\n  {tf}データ取得中...")
        df_higher = fetch_higher_timeframe_data(tf, args.days, use_cache=not args.no_cache)

        total = len(HIGHER_MA_SHORT) * len(HIGHER_MA_LONG)
        current = 0
        for ma_short in HIGHER_MA_SHORT:
            for ma_long in HIGHER_MA_LONG:
                if ma_short >= ma_long:
                    continue
                current += 1
                print(f"\r  テスト中... {current}/{total} ({tf} MA {ma_short}/{ma_long})", end="", flush=True)
                result = run_higher_tf_filter_simulation(
                    df_1h, df_higher, ma_short, ma_long, tf, args.verbose
                )
                higher_tf_results.append(result)
                all_results.append(result)
        print()

    print_results(higher_tf_results, "[上位足フィルター 結果]")

    # 全結果を表示
    print_results(all_results, "=== 全フィルター 総合結果 ===", top_n=10)

    # CSV保存
    save_results(all_results, "backtest_trend_filter_results.csv")

    print("\n" + "=" * 80)
    print("トレンドフィルター追加版 バックテスト完了")
    print("=" * 80)


if __name__ == "__main__":
    main()
