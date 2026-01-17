# 追加戦略バックテスト指示書

## 概要

移動平均クロスオーバー戦略が過去1年間で負けていたため、以下2つの代替戦略を検証する。

- **戦略A**: 逆張り（RSI）戦略
- **戦略B**: トレンドフィルター追加版（既存戦略の改良）

## ファイル構成

```
scripts/
├── backtest.py              # 既存（そのまま）
├── backtest_rsi.py          # 戦略A: RSI逆張り
└── backtest_trend_filter.py # 戦略B: トレンドフィルター追加
```

---

# 戦略A: 逆張り（RSI）戦略

## コンセプト

「売られすぎで買い、買われすぎで売る」

レンジ相場では価格が平均に回帰する傾向があるため、極端に動いたときに逆方向にエントリーする。

## RSIの計算

```python
def calculate_rsi(closes, period=14):
    """
    RSI = 100 - (100 / (1 + RS))
    RS = 平均上昇幅 / 平均下落幅
    """
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = pd.Series(gains).rolling(window=period).mean()
    avg_loss = pd.Series(losses).rolling(window=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi
```

## 売買ルール

| シグナル | 条件 | アクション |
|----------|------|------------|
| BUY | RSI < RSI_OVERSOLD（売られすぎ） | 買い |
| SELL | RSI > RSI_OVERBOUGHT（買われすぎ） | 売り |
| HOLD | 上記以外 | 何もしない |

## テストするパラメータ

```python
RSI_PERIODS = [7, 14, 21]
RSI_OVERSOLD_LEVELS = [20, 25, 30]      # この値以下で買い
RSI_OVERBOUGHT_LEVELS = [70, 75, 80]    # この値以上で売り
```

全組み合わせ: 3 × 3 × 3 = 27パターン

## シミュレーション条件

既存のバックテストと同じ：

| 項目 | 値 |
|------|-----|
| 初期資金 | 500 USDT |
| 1回の取引額 | 資金の35% |
| 最小取引量 | 0.001 BTC |
| 損切りライン | 10% |
| 取引手数料 | 0.1% |

## 出力形式

```
=== RSI逆張り戦略 バックテスト結果 ===
期間: 2024-01-01 〜 2025-01-01

[訓練期間 上位5件]
1. RSI(14, 25/75): 利益率 +8.2%, 勝率 52%, 取引 28回, 最大DD -6.1%
2. RSI(14, 30/70): 利益率 +5.1%, 勝率 48%, 取引 42回, 最大DD -7.3%
...

[テスト期間 上位5件]
...
```

CSV出力: `results/backtest_rsi_results.csv`

---

# 戦略B: トレンドフィルター追加版

## コンセプト

「トレンドが出ているときだけ、既存の移動平均クロス戦略を使う」

レンジ相場での無駄な取引を減らし、トレンド発生時のみエントリーする。

## トレンド判定方法

### 方法1: ATR（Average True Range）フィルター

ボラティリティが高いとき = トレンドが出やすいとき

```python
def calculate_atr(high, low, close, period=14):
    """
    TR = max(高値-安値, |高値-前日終値|, |安値-前日終値|)
    ATR = TRのperiod期間移動平均
    """
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr
```

**エントリー条件**:
- 既存のゴールデンクロス発生
- かつ ATR > ATRの20期間移動平均 × ATR_THRESHOLD

### 方法2: ADX（Average Directional Index）フィルター

トレンドの強さを直接測定

```python
def calculate_adx(high, low, close, period=14):
    """
    ADX = DMIの強さを示す（0-100）
    25以上: トレンドあり
    25未満: レンジ相場
    """
    # +DM, -DM, TR から +DI, -DI を計算
    # DX = |+DI - -DI| / (+DI + -DI) × 100
    # ADX = DXのperiod期間移動平均
    ...
```

**エントリー条件**:
- 既存のゴールデンクロス発生
- かつ ADX > ADX_THRESHOLD

### 方法3: 上位足トレンド確認

1時間足でエントリーする前に、4時間足や日足のトレンド方向を確認

**エントリー条件**:
- 1時間足でゴールデンクロス発生
- かつ 日足の短期MA > 日足の長期MA（上昇トレンド中）

## テストするパラメータ

```python
# 既存のMA設定（最良だったものを使用）
MA_SHORT = 25
MA_LONG = 75

# ATRフィルター
ATR_PERIODS = [14, 20]
ATR_THRESHOLDS = [1.0, 1.2, 1.5]  # ATR移動平均の何倍以上でトレンドと判定

# ADXフィルター
ADX_PERIODS = [14, 20]
ADX_THRESHOLDS = [20, 25, 30]  # この値以上でトレンドと判定

# 上位足フィルター
HIGHER_TIMEFRAMES = ['4h', '1d']
HIGHER_MA_SHORT = [10, 20]
HIGHER_MA_LONG = [20, 50]
```

## シミュレーション条件

既存のバックテストと同じ

## 出力形式

```
=== トレンドフィルター追加版 バックテスト結果 ===
期間: 2024-01-01 〜 2025-01-01

[ATRフィルター 上位5件]
1. MA(25/75) + ATR(14, 1.2): 利益率 +3.2%, 勝率 38%, 取引 18回, 最大DD -5.1%
...

[ADXフィルター 上位5件]
1. MA(25/75) + ADX(14, 25): 利益率 +4.1%, 勝率 42%, 取引 22回, 最大DD -4.8%
...

[上位足フィルター 上位5件]
1. MA(25/75) + 日足MA(20/50): 利益率 +5.8%, 勝率 45%, 取引 15回, 最大DD -4.2%
...
```

CSV出力: `results/backtest_trend_filter_results.csv`

---

# 共通事項

## データ

既存のバックテストでキャッシュした `data/btc_jpy_1h.csv` を再利用する。
上位足フィルター用に `4h` と `1d` のデータも必要であれば追加取得。

## 比較出力

最後に3つの戦略を比較するサマリーを出力：

```
=== 戦略比較サマリー ===

| 戦略 | 最良パラメータ | 訓練利益率 | テスト利益率 | 勝率 | 取引回数 |
|------|----------------|------------|--------------|------|----------|
| MAクロス | MA(25/75) | -3.7% | -0.8% | 25% | 55 |
| RSI逆張り | RSI(14,25/75) | +8.2% | +5.1% | 52% | 28 |
| MA+ADX | MA(25/75)+ADX(14,25) | +4.1% | +3.2% | 42% | 22 |

推奨: RSI逆張り（テスト期間でもプラス維持）
```

## 実行方法

```bash
# RSI逆張り戦略
python scripts/backtest_rsi.py

# トレンドフィルター追加版
python scripts/backtest_trend_filter.py

# 両方実行して比較（オプション）
python scripts/backtest_rsi.py && python scripts/backtest_trend_filter.py
```

## 注意事項

- RSI戦略では「ポジションを持っていないときだけ買い」「ポジションを持っているときだけ売り」を徹底する
- 上位足データ取得時はAPIレート制限に注意
- 全パターンの検証には時間がかかるため、プログレス表示を入れる
