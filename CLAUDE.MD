# 仮想通貨自動取引Bot

## プロジェクト概要

仮想通貨の自動取引Bot。テストネット（ペーパートレード）と本番環境の両方に対応。

## 技術スタック

- Python 3.10+
- ccxt: 取引所API統一ライブラリ
- pandas: データ操作
- ta: テクニカル指標計算
- python-dotenv: 環境変数管理

## 取引所

- **Sandbox（テストネット）**: https://testnet.binance.vision/
- **Production（本番）**: https://www.binance.com/

## ディレクトリ構成

```
kaso_trade/
├── api/
│   └── trade.py          # Vercel Cron用エンドポイント
├── src/
│   ├── __init__.py
│   ├── config.py         # 設定管理（環境変数から読み込み）
│   ├── exchange.py       # 取引所接続・注文
│   ├── data.py           # データ取得・加工
│   ├── indicators.py     # テクニカル指標
│   ├── strategy.py       # 売買戦略
│   └── bot.py            # ローカル実行用メインループ
├── scripts/
│   └── check_connection.py  # 接続確認
├── tests/
│   └── test_strategy.py
├── logs/
│   └── trades.csv        # 取引履歴
├── .env.example          # 環境変数サンプル
├── .env                  # 環境変数（.gitignore対象）
├── .gitignore
├── requirements.txt
├── vercel.json           # Vercel設定
└── CLAUDE.md
```

## 環境設定

### 1. 環境変数ファイルの作成

```bash
cp .env.example .env
```

### 2. .envを編集

```bash
# 環境設定
ENVIRONMENT=sandbox  # または production

# 本番環境の場合は必須（安全対策）
# CONFIRM_PRODUCTION=yes

# Binance APIキー
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# 取引設定
SYMBOL=BTC/USDT
TIMEFRAME=1h
MAX_POSITION_PERCENT=0.02

# 移動平均設定
MA_SHORT_PERIOD=10
MA_LONG_PERIOD=20
```

## 実行方法

### ローカル実行

```bash
# 接続確認
python scripts/check_connection.py

# Bot起動（1時間ごとにチェック）
python src/bot.py
```

### Vercelデプロイ

1. GitHubにプッシュ
2. Vercelでインポート
3. Environment Variablesを設定
4. デプロイ

Cronは毎時0分に実行（`vercel.json`で設定）

## 環境の切り替え

### テストネット（デフォルト）
```
ENVIRONMENT=sandbox
```

### 本番環境
```
ENVIRONMENT=production
CONFIRM_PRODUCTION=yes  # 必須（安全対策）
```

**本番環境の注意事項:**
- `CONFIRM_PRODUCTION=yes`を設定しないと起動しない
- 起動時に10秒の待機時間あり（キャンセル猶予）
- ログに「PRODUCTION MODE」の警告が出る

## コーディング規約

- 型ヒントを使用する
- docstringはGoogle形式
- ログ出力は`logging`モジュールを使用
- 金額・数量は`Decimal`で扱う

## リスク管理

- 1回の取引で使う金額は総資金の1-2%以下（`MAX_POSITION_PERCENT`）
- 本番環境では必ず少額から開始
- ペーパートレードで十分検証してから本番へ

## 開発フェーズ

### Phase 1: 基盤構築 ✅
- [x] テストネット接続確認
- [x] 価格データ取得
- [x] 注文実行（成行買い・売り）
- [x] 残高確認

### Phase 2: シンプル戦略 ✅
- [x] 移動平均クロスオーバー戦略の実装
- [x] 定期実行ループ
- [x] 取引ログの記録

### Phase 3: 本番対応 ✅
- [x] 環境変数による設定管理
- [x] 本番/テストネット切り替え
- [x] 安全対策の実装
- [x] Vercel Cron対応

### Phase 4: 分析・改善（TODO）
- [ ] バックテスト環境構築
- [ ] パフォーマンス分析
- [ ] 戦略パラメータの最適化
- [ ] 損切り・利確機能

### Phase 5: ML導入（将来）
- [ ] 特徴量エンジニアリング
- [ ] LightGBMによる価格予測モデル
- [ ] シグナル生成への組み込み

## 参考リンク

- ccxt公式ドキュメント: https://docs.ccxt.com/
- Binance Testnet: https://testnet.binance.vision/
- Binance本番: https://www.binance.com/
- taライブラリ: https://technical-analysis-library-in-python.readthedocs.io/
