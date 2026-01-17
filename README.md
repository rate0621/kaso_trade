# 仮想通貨自動取引Bot

bitFlyer取引所でBTC/JPYを自動売買するトレーディングBot。

## 機能

- **移動平均クロスオーバー戦略**: 短期・長期移動平均の交差でシグナルを生成
- **損切り機能**: 設定した下落率で自動的に損切り売却
- **複数環境対応**: ローカル実行 / Vercel Cron
- **ログ記録**: CSV（ローカル）/ Supabase（クラウド）

## 必要条件

- Python 3.10+
- bitFlyer アカウント + APIキー
- （オプション）Supabase アカウント
- （オプション）Vercel アカウント

## インストール

```bash
# リポジトリをクローン
git clone <repository-url>
cd kaso_trade

# 仮想環境を作成
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存パッケージをインストール
pip install -r requirements.txt

# 環境変数を設定
cp .env.example .env
# .env を編集してAPIキーを設定
```

## 設定

### 環境変数（.env）

```bash
# 必須
BITFLYER_API_KEY=your_api_key_here
BITFLYER_API_SECRET=your_api_secret_here
CONFIRM_TRADING=yes  # 取引を有効化する安全確認

# 取引設定
SYMBOL=BTC/JPY
TIMEFRAME=1h

# リスク管理
MAX_POSITION_PERCENT=0.35  # 1回の取引で使う資金割合（35%）
STOP_LOSS_PERCENT=0.10     # 損切りライン（10%下落）

# 移動平均設定
MA_SHORT_PERIOD=10
MA_LONG_PERIOD=20

# Supabase（オプション）
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key_here
```

### Supabase テーブル（オプション）

Supabaseを使用する場合、以下のテーブルを作成してください：

```sql
-- 取引ログ
CREATE TABLE trade_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    environment VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 2) NOT NULL,
    balance_usdt DECIMAL(20, 2),
    balance_btc DECIMAL(20, 8),
    signal VARCHAR(20),
    order_id VARCHAR(100)
);

-- ポジション管理
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL UNIQUE,
    entry_price DECIMAL(20, 8) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    entry_time TIMESTAMP NOT NULL
);
```

## 使い方

### 接続確認

```bash
python scripts/check_connection.py
```

### ローカル実行

```bash
python src/bot.py
```

1時間ごとに自動で取引判定を行います。停止は `Ctrl+C`。

### Vercel Cron

1. Vercel にデプロイ
2. 環境変数を Vercel のダッシュボードで設定
3. `vercel.json` の cron 設定で定期実行

```json
{
  "crons": [
    {
      "path": "/api/trade",
      "schedule": "0 * * * *"
    }
  ]
}
```

## 取引戦略

### 移動平均クロスオーバー

| シグナル | 条件 | アクション |
|----------|------|------------|
| BUY | 短期MAが長期MAを下から上に抜けた | 資金の35%で買い |
| SELL | 短期MAが長期MAを上から下に抜けた | 全BTC売却 |
| HOLD | 上記以外 | 何もしない |

### 損切り

購入価格から10%以上下落した場合、シグナルに関係なく即座に売却。

```
例: 購入価格 1,000,000円 → 現在価格 890,000円（11%下落）→ 損切り発動
```

## プロジェクト構成

```
kaso_trade/
├── api/
│   └── trade.py          # Vercel Cron エンドポイント
├── src/
│   ├── config.py         # 設定管理
│   ├── exchange.py       # bitFlyer 接続
│   ├── data.py           # OHLCV データ取得（bitbank経由）
│   ├── indicators.py     # テクニカル指標
│   ├── strategy.py       # 売買戦略
│   ├── position.py       # ポジション管理・損切り
│   ├── bot.py            # メインループ
│   └── database.py       # Supabase 連携
├── tests/
│   ├── test_strategy.py
│   └── test_position.py
├── scripts/
│   └── check_connection.py
├── logs/                  # 取引ログ（gitignore対象）
├── .env.example
├── requirements.txt
└── vercel.json
```

## テスト

```bash
pip install pytest
python -m pytest tests/ -v
```

## 技術的な注意事項

### OHLCVデータについて

bitFlyer は OHLCV（ローソク足）API を提供していないため、同じ日本市場の **bitbank** から取得しています。両取引所は同じ BTC/JPY を扱っており、アービトラージにより価格差は僅少です。

### 損切り判定のタイミング

損切りチェックは Bot の実行間隔（デフォルト1時間）ごとに行われます。急激な価格変動には即時対応できません。

### ポジション管理

- ローカル実行: `logs/position.json` に保存
- Vercel: Supabase の `positions` テーブルに保存

Supabase を設定しない場合、Vercel 環境ではポジション情報が失われる可能性があります。

## 免責事項

- 本ソフトウェアは投資助言を目的としたものではありません
- bitFlyer にはテストネットがないため、全ての取引は実際の資金を使用します
- 取引による損失について、開発者は一切の責任を負いません
- 十分なリスク管理と自己責任のもとでご使用ください

## ライセンス

MIT License
