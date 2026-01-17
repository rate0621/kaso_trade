#!/usr/bin/env python3
"""RSI逆張り戦略バックテストスクリプト。

「売られすぎで買い、買われすぎで売る」逆張り戦略を検証する。

Usage:
    python scripts/backtest_rsi.py
    python scripts/backtest_rsi.py --days 365
    python scripts/backtest_rsi.py --verbose
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

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
RESULTS_DIR = Path(__file__).parent.parent / "results"

# RSIパラメータ
RSI_PERIODS = [7, 14, 21]
RSI_OVERSOLD_LEVELS = [20, 25, 30]
RSI_OVERBOUGHT_LEVELS = [70, 75, 80]


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
    rsi_period: int
    oversold: int
    overbought: int
    profit_rate: float
    win_rate: float
    trades: int
    max_drawdown: float
    profit_factor: float
    stop_loss_count: int
    final_capital: float


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(description="RSI逆張り戦略バックテスト")
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


def calculate_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """RSIを計算する。

    RSI = 100 - (100 / (1 + RS))
    RS = 平均上昇幅 / 平均下落幅

    Args:
        closes: 終値のSeries
        period: RSI計算期間

    Returns:
        RSI値のSeries
    """
    deltas = closes.diff()
    gains = deltas.where(deltas > 0, 0.0)
    losses = (-deltas).where(deltas < 0, 0.0)

    avg_gain = gains.rolling(window=period, min_periods=period).mean()
    avg_loss = losses.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def run_rsi_simulation(
    df: pd.DataFrame,
    rsi_period: int,
    oversold: int,
    overbought: int,
    verbose: bool = False,
) -> BacktestResult:
    """RSI逆張り戦略のシミュレーションを実行する。

    Args:
        df: OHLCVデータ
        rsi_period: RSI計算期間
        oversold: 売られすぎレベル（この値以下で買い）
        overbought: 買われすぎレベル（この値以上で売り）
        verbose: 詳細ログを出力するか

    Returns:
        バックテスト結果
    """
    # RSIを計算
    df = df.copy()
    df["rsi"] = calculate_rsi(df["close"], rsi_period)

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

        # RSIが計算できない期間はスキップ
        if pd.isna(row["rsi"]):
            continue

        current_price = row["close"]
        current_rsi = row["rsi"]

        # ポジションを持っている場合
        if btc_amount > 0:
            # 損切りチェック
            drop_percent = (entry_price - current_price) / entry_price
            if drop_percent >= STOP_LOSS_PERCENT:
                # 損切り売却
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

                if verbose:
                    print(f"  {row.name}: 損切り @ {current_price:,.0f} (損失: {profit:,.2f})")

            # 買われすぎで売り
            elif current_rsi > overbought:
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

                if verbose:
                    print(f"  {row.name}: 売却(RSI={current_rsi:.1f}) @ {current_price:,.0f} (利益: {profit:,.2f})")

        # ポジションを持っていない場合
        else:
            # 売られすぎで買い
            if current_rsi < oversold:
                usdt_to_use = capital * POSITION_PERCENT
                amount = usdt_to_use / current_price * (1 - TRADE_FEE_PERCENT)

                if amount >= MIN_TRADE_AMOUNT:
                    btc_amount = amount
                    entry_price = current_price
                    capital -= usdt_to_use

                    if verbose:
                        print(f"  {row.name}: 購入(RSI={current_rsi:.1f}) @ {current_price:,.0f} ({btc_amount:.6f} BTC)")

        # 資産推移を記録
        total_value = capital + btc_amount * current_price
        capital_history.append(total_value)

    # 最終的にポジションを持っていたら時価評価
    if btc_amount > 0:
        final_price = df.iloc[-1]["close"]
        capital += btc_amount * final_price * (1 - TRADE_FEE_PERCENT)

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

    # 最大ドローダウン
    max_drawdown = 0.0
    peak = capital_history[0]
    for value in capital_history:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return BacktestResult(
        rsi_period=rsi_period,
        oversold=oversold,
        overbought=overbought,
        profit_rate=profit_rate,
        win_rate=win_rate,
        trades=len(trades),
        max_drawdown=-max_drawdown,
        profit_factor=profit_factor,
        stop_loss_count=stop_loss_count,
        final_capital=capital,
    )


def run_rsi_backtest(
    df: pd.DataFrame,
    verbose: bool = False,
) -> list[BacktestResult]:
    """全パラメータ組み合わせでRSIバックテストを実行する。"""
    results = []
    total_combinations = len(RSI_PERIODS) * len(RSI_OVERSOLD_LEVELS) * len(RSI_OVERBOUGHT_LEVELS)
    current = 0

    for period in RSI_PERIODS:
        for oversold in RSI_OVERSOLD_LEVELS:
            for overbought in RSI_OVERBOUGHT_LEVELS:
                current += 1
                if not verbose:
                    print(f"\r  テスト中... {current}/{total_combinations} (RSI {period}, {oversold}/{overbought})", end="", flush=True)

                if verbose:
                    print(f"\n--- RSI({period}, {oversold}/{overbought}) ---")

                result = run_rsi_simulation(df, period, oversold, overbought, verbose=verbose)
                results.append(result)

    if not verbose:
        print()

    return results


def print_results(
    results: list[BacktestResult],
    title: str,
    top_n: int = 5,
) -> None:
    """結果を表示する。"""
    print(f"\n{title}")
    print("=" * 70)

    # 利益率でソート
    sorted_results = sorted(results, key=lambda r: r.profit_rate, reverse=True)

    for i, r in enumerate(sorted_results[:top_n], 1):
        pf_str = f"{r.profit_factor:.1f}" if r.profit_factor != float("inf") else "∞"
        print(
            f"{i}. RSI({r.rsi_period:2d}, {r.oversold:2d}/{r.overbought:2d}): "
            f"利益率 {r.profit_rate:+6.1f}%, "
            f"勝率 {r.win_rate:4.1f}%, "
            f"取引 {r.trades:3d}回, "
            f"最大DD {r.max_drawdown:5.1f}%, "
            f"PF {pf_str}, "
            f"損切り {r.stop_loss_count}回"
        )


def save_results(results: list[BacktestResult], filename: str) -> None:
    """結果をCSVに保存する。"""
    RESULTS_DIR.mkdir(exist_ok=True)
    filepath = RESULTS_DIR / filename

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "rsi_period", "oversold", "overbought", "profit_rate", "win_rate", "trades",
            "max_drawdown", "profit_factor", "stop_loss_count", "final_capital"
        ])
        for r in results:
            pf = r.profit_factor if r.profit_factor != float("inf") else 9999
            writer.writerow([
                r.rsi_period, r.oversold, r.overbought,
                f"{r.profit_rate:.2f}", f"{r.win_rate:.2f}",
                r.trades, f"{r.max_drawdown:.2f}", f"{pf:.2f}",
                r.stop_loss_count, f"{r.final_capital:.0f}"
            ])

    print(f"\n結果を保存: {filepath}")


def check_overfitting(
    train_results: list[BacktestResult],
    test_results: list[BacktestResult],
) -> None:
    """過学習の可能性をチェックする。"""
    print("\n=== 過学習チェック ===")

    # 訓練データでの上位5件
    train_sorted = sorted(train_results, key=lambda r: r.profit_rate, reverse=True)[:5]

    for tr in train_sorted:
        # 同じパラメータのテスト結果を探す
        test_result = next(
            (r for r in test_results
             if r.rsi_period == tr.rsi_period
             and r.oversold == tr.oversold
             and r.overbought == tr.overbought),
            None
        )
        if test_result:
            diff = abs(tr.profit_rate - test_result.profit_rate)
            flag = " ⚠️ 過学習の可能性" if diff > 10 else ""
            print(
                f"RSI({tr.rsi_period:2d}, {tr.oversold:2d}/{tr.overbought:2d}): "
                f"訓練 {tr.profit_rate:+6.1f}% → テスト {test_result.profit_rate:+6.1f}% "
                f"(差: {diff:.1f}%){flag}"
            )


def main() -> None:
    """メイン処理。"""
    args = parse_args()

    print("=" * 70)
    print("RSI逆張り戦略 バックテスト開始")
    print("=" * 70)
    print(f"RSI期間: {RSI_PERIODS}")
    print(f"売られすぎレベル: {RSI_OVERSOLD_LEVELS}")
    print(f"買われすぎレベル: {RSI_OVERBOUGHT_LEVELS}")
    print(f"初期資金: {INITIAL_CAPITAL:,} USDT")
    print(f"ポジションサイズ: {POSITION_PERCENT * 100}%")
    print(f"損切りライン: {STOP_LOSS_PERCENT * 100}%")

    # データ取得
    print("\n[1] データ取得")
    df = fetch_ohlcv_data(days=args.days, use_cache=not args.no_cache, verbose=args.verbose)

    print(f"  期間: {df.index[0]} 〜 {df.index[-1]}")
    print(f"  データ数: {len(df)}本")

    # データ分割（訓練: 75%, テスト: 25%）
    split_idx = int(len(df) * 0.75)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    print(f"\n  訓練データ: {train_df.index[0]} 〜 {train_df.index[-1]} ({len(train_df)}本)")
    print(f"  テストデータ: {test_df.index[0]} 〜 {test_df.index[-1]} ({len(test_df)}本)")

    # 訓練データでバックテスト
    print("\n[2] 訓練データでバックテスト実行")
    train_results = run_rsi_backtest(train_df, args.verbose)
    print_results(train_results, "=== 訓練期間の結果 ===")

    # テストデータでバックテスト
    print("\n[3] テストデータでバックテスト実行")
    test_results = run_rsi_backtest(test_df, args.verbose)
    print_results(test_results, "=== テスト期間の結果（検証用） ===")

    # 過学習チェック
    check_overfitting(train_results, test_results)

    # 全期間でのバックテスト
    print("\n[4] 全期間でバックテスト実行")
    all_results = run_rsi_backtest(df, args.verbose)
    print_results(all_results, "=== 全期間の結果 ===")

    # CSV保存
    save_results(all_results, "backtest_rsi_results.csv")

    print("\n" + "=" * 70)
    print("RSI逆張り戦略 バックテスト完了")
    print("=" * 70)


if __name__ == "__main__":
    main()
