#!/usr/bin/env python3
"""バックテストスクリプト。

移動平均クロスオーバー戦略のパラメータ最適化を行う。

Usage:
    python scripts/backtest.py
    python scripts/backtest.py --days 365
    python scripts/backtest.py --short 10,20 --long 20,50
    python scripts/backtest.py --verbose
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
import pandas as pd

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

# ディレクトリ設定
DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
CACHE_FILE = DATA_DIR / "btc_usdt_1h.csv"

# デフォルトパラメータ
DEFAULT_MA_SHORT_PERIODS = [5, 10, 15, 20, 25]
DEFAULT_MA_LONG_PERIODS = [20, 30, 40, 50, 75, 100]

# シミュレーション条件
INITIAL_CAPITAL = 500  # 初期資金（USDT）
POSITION_PERCENT = 0.35  # 1回の取引で使う資金割合
MIN_TRADE_AMOUNT = 0.0001  # 最小取引量（BTC）
STOP_LOSS_PERCENT = 0.10  # 損切りライン
TRADE_FEE_PERCENT = 0.001  # 取引手数料（0.1% Binance標準）


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
    ma_short: int
    ma_long: int
    profit_rate: float
    win_rate: float
    trades: int
    max_drawdown: float
    profit_factor: float
    stop_loss_count: int
    final_capital: float


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(description="バックテストスクリプト")
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="取得する日数（デフォルト: 365）",
    )
    parser.add_argument(
        "--short",
        type=str,
        default=None,
        help="短期MA期間（カンマ区切り、例: 10,20）",
    )
    parser.add_argument(
        "--long",
        type=str,
        default=None,
        help="長期MA期間（カンマ区切り、例: 20,50）",
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


def fetch_ohlcv_data(days: int = 365, use_cache: bool = True, verbose: bool = False) -> pd.DataFrame:
    """OHLCVデータを取得する。

    Args:
        days: 取得する日数
        use_cache: キャッシュを使用するか
        verbose: 詳細ログを出力するか

    Returns:
        OHLCVデータのDataFrame
    """
    # キャッシュ確認
    if use_cache and CACHE_FILE.exists():
        if verbose:
            print(f"キャッシュからデータを読み込み: {CACHE_FILE}")
        df = pd.read_csv(CACHE_FILE, parse_dates=["datetime"])
        df.set_index("datetime", inplace=True)

        # キャッシュが十分な期間をカバーしているか確認
        cache_days = (df.index[-1] - df.index[0]).days
        if cache_days >= days - 1:
            return df

        if verbose:
            print(f"キャッシュが不十分（{cache_days}日分）、新規取得します")

    # Binanceからデータを取得（bitbankはデータ取得に制限があるため）
    # 注意: BTC/USDTのデータを使用。価格の動きはBTC/JPYとほぼ同じ
    print("  BinanceからOHLCVデータを取得中...")
    print("  ※ BTC/USDTデータを使用（価格変動パターンはBTC/JPYと同等）")

    exchange = ccxt.binance({"enableRateLimit": True})
    symbol = "BTC/USDT"
    timeframe = "1h"

    all_ohlcv = []
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    since = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    limit = 500  # bitbankの制限に合わせる

    total_expected = days * 24

    while since < end_ms:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except Exception as e:
            print(f"\n  警告: データ取得エラー: {e}")
            break

        if not ohlcv:
            break

        all_ohlcv.extend(ohlcv)
        fetched = len(all_ohlcv)

        progress = min(100, fetched / total_expected * 100)
        print(f"\r  取得中... {fetched}本 ({progress:.1f}%)", end="", flush=True)

        # 次のリクエストの開始位置を設定
        since = ohlcv[-1][0] + 1

        # レート制限対策
        time.sleep(0.2)

        # データが取得できなくなったら終了
        if len(ohlcv) < limit:
            break

    print(f"\n  完了: {len(all_ohlcv)}本取得")

    # DataFrameに変換
    df = pd.DataFrame(
        all_ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("datetime", inplace=True)

    # キャッシュに保存
    DATA_DIR.mkdir(exist_ok=True)
    df.reset_index().to_csv(CACHE_FILE, index=False)
    if verbose:
        print(f"  キャッシュに保存: {CACHE_FILE}")

    return df


def calculate_ma(df: pd.DataFrame, short_period: int, long_period: int) -> pd.DataFrame:
    """移動平均を計算する。"""
    df = df.copy()
    df[f"ma_short"] = df["close"].rolling(window=short_period).mean()
    df[f"ma_long"] = df["close"].rolling(window=long_period).mean()
    return df


def run_simulation(
    df: pd.DataFrame,
    ma_short: int,
    ma_long: int,
    verbose: bool = False,
) -> BacktestResult:
    """シミュレーションを実行する。

    Args:
        df: OHLCVデータ
        ma_short: 短期MA期間
        ma_long: 長期MA期間
        verbose: 詳細ログを出力するか

    Returns:
        バックテスト結果
    """
    # 移動平均を計算
    df = calculate_ma(df, ma_short, ma_long)

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

        # MAが計算できない期間はスキップ
        if pd.isna(row["ma_short"]) or pd.isna(row["ma_long"]):
            continue

        current_price = row["close"]

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
                    print(f"  {row.name}: 損切り @ {current_price:,.0f} (損失: {profit:,.0f}円)")

            # デッドクロスチェック
            elif (prev_row["ma_short"] >= prev_row["ma_long"] and
                  row["ma_short"] < row["ma_long"]):
                # 通常売却
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
                    print(f"  {row.name}: 売却 @ {current_price:,.0f} (利益: {profit:,.0f}円)")

        # ポジションを持っていない場合
        else:
            # ゴールデンクロスチェック
            if (prev_row["ma_short"] <= prev_row["ma_long"] and
                row["ma_short"] > row["ma_long"]):
                # 買い注文
                jpy_to_use = capital * POSITION_PERCENT
                amount = jpy_to_use / current_price * (1 - TRADE_FEE_PERCENT)

                if amount >= MIN_TRADE_AMOUNT:
                    btc_amount = amount
                    entry_price = current_price
                    capital -= jpy_to_use

                    if verbose:
                        print(f"  {row.name}: 購入 @ {current_price:,.0f} ({btc_amount:.6f} BTC)")

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
        ma_short=ma_short,
        ma_long=ma_long,
        profit_rate=profit_rate,
        win_rate=win_rate,
        trades=len(trades),
        max_drawdown=-max_drawdown,
        profit_factor=profit_factor,
        stop_loss_count=stop_loss_count,
        final_capital=capital,
    )


def run_backtest(
    df: pd.DataFrame,
    ma_short_periods: list[int],
    ma_long_periods: list[int],
    verbose: bool = False,
) -> list[BacktestResult]:
    """全パラメータ組み合わせでバックテストを実行する。"""
    results = []
    total_combinations = sum(
        1 for s in ma_short_periods for l in ma_long_periods if s < l
    )
    current = 0

    for ma_short in ma_short_periods:
        for ma_long in ma_long_periods:
            # 短期MA >= 長期MA はスキップ
            if ma_short >= ma_long:
                continue

            current += 1
            if not verbose:
                print(f"\r  テスト中... {current}/{total_combinations} (MA {ma_short}/{ma_long})", end="", flush=True)

            if verbose:
                print(f"\n--- MA({ma_short}/{ma_long}) ---")

            result = run_simulation(df, ma_short, ma_long, verbose=verbose)
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
    print("=" * 60)

    # 利益率でソート
    sorted_results = sorted(results, key=lambda r: r.profit_rate, reverse=True)

    for i, r in enumerate(sorted_results[:top_n], 1):
        pf_str = f"{r.profit_factor:.1f}" if r.profit_factor != float("inf") else "∞"
        print(
            f"{i}. MA({r.ma_short:2d}/{r.ma_long:3d}): "
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
            "ma_short", "ma_long", "profit_rate", "win_rate", "trades",
            "max_drawdown", "profit_factor", "stop_loss_count", "final_capital"
        ])
        for r in results:
            pf = r.profit_factor if r.profit_factor != float("inf") else 9999
            writer.writerow([
                r.ma_short, r.ma_long, f"{r.profit_rate:.2f}", f"{r.win_rate:.2f}",
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
            (r for r in test_results if r.ma_short == tr.ma_short and r.ma_long == tr.ma_long),
            None
        )
        if test_result:
            diff = abs(tr.profit_rate - test_result.profit_rate)
            flag = " ⚠️ 過学習の可能性" if diff > 10 else ""
            print(
                f"MA({tr.ma_short:2d}/{tr.ma_long:3d}): "
                f"訓練 {tr.profit_rate:+6.1f}% → テスト {test_result.profit_rate:+6.1f}% "
                f"(差: {diff:.1f}%){flag}"
            )


def main() -> None:
    """メイン処理。"""
    args = parse_args()

    # パラメータ設定
    if args.short:
        ma_short_periods = [int(x) for x in args.short.split(",")]
    else:
        ma_short_periods = DEFAULT_MA_SHORT_PERIODS

    if args.long:
        ma_long_periods = [int(x) for x in args.long.split(",")]
    else:
        ma_long_periods = DEFAULT_MA_LONG_PERIODS

    print("=" * 60)
    print("バックテスト開始")
    print("=" * 60)
    print(f"短期MA期間: {ma_short_periods}")
    print(f"長期MA期間: {ma_long_periods}")
    print(f"初期資金: {INITIAL_CAPITAL:,} USDT")
    print(f"ポジションサイズ: {POSITION_PERCENT * 100}%")
    print(f"損切りライン: {STOP_LOSS_PERCENT * 100}%")
    print(f"取引手数料: {TRADE_FEE_PERCENT * 100}%")

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
    train_results = run_backtest(train_df, ma_short_periods, ma_long_periods, args.verbose)
    print_results(train_results, "=== 訓練期間の結果 ===")

    # テストデータでバックテスト
    print("\n[3] テストデータでバックテスト実行")
    test_results = run_backtest(test_df, ma_short_periods, ma_long_periods, args.verbose)
    print_results(test_results, "=== テスト期間の結果（検証用） ===")

    # 過学習チェック
    check_overfitting(train_results, test_results)

    # 全期間でのバックテスト
    print("\n[4] 全期間でバックテスト実行")
    all_results = run_backtest(df, ma_short_periods, ma_long_periods, args.verbose)
    print_results(all_results, "=== 全期間の結果 ===")

    # CSV保存
    save_results(all_results, "backtest_results.csv")

    print("\n" + "=" * 60)
    print("バックテスト完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
