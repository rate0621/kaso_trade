"""ダッシュボード - 資産状況と損益を表示。"""

import base64
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.database import get_trade_logs
from src.exchange import Exchange
from src.position import load_position
from src.trading import check_trend, get_crypto_currency, is_supabase_configured, Trend
from src.data import fetch_ohlcv_as_df


def check_auth(authorization: str | None) -> bool:
    """BASIC認証をチェックする。"""
    username = os.environ.get("DASHBOARD_USERNAME", "")
    password = os.environ.get("DASHBOARD_PASSWORD", "")

    if not username or not password:
        # 認証情報が設定されていない場合は認証をスキップ
        return True

    if not authorization:
        return False

    try:
        scheme, credentials = authorization.split(" ", 1)
        if scheme.lower() != "basic":
            return False

        decoded = base64.b64decode(credentials).decode("utf-8")
        input_user, input_pass = decoded.split(":", 1)

        return input_user == username and input_pass == password
    except Exception:
        return False


def get_dashboard_data() -> dict:
    """ダッシュボード用のデータを取得する。"""
    config = get_config()
    exchange = Exchange.from_config(config)

    # 残高取得
    balance = exchange.fetch_balance()
    jpy_balance = float(balance.get("JPY", {}).get("free", 0))
    btc_balance = float(balance.get("BTC", {}).get("free", 0))
    eth_balance = float(balance.get("ETH", {}).get("free", 0))

    # 現在価格取得
    btc_price = exchange.fetch_ticker("BTC/JPY")["last"]
    eth_price = exchange.fetch_ticker("ETH/JPY")["last"]

    # トレンド判定
    trends = {}
    for symbol_config in config.symbols:
        symbol = symbol_config.symbol
        try:
            df = fetch_ohlcv_as_df(exchange, symbol, config.timeframe, limit=100)
            trend = check_trend(df, ma_period=50, lookback=5)
            trends[symbol] = trend
        except Exception:
            trends[symbol] = "unknown"

    # 取引履歴から損益計算
    pnl_by_symbol = {}
    trade_count_by_symbol = {}

    if is_supabase_configured():
        logs = get_trade_logs(limit=500)

        # シンボルごとにグループ化
        for log in logs:
            symbol = log["symbol"]
            if symbol not in pnl_by_symbol:
                pnl_by_symbol[symbol] = 0
                trade_count_by_symbol[symbol] = 0

        # 買い→売りのペアで損益計算
        for symbol in set(log["symbol"] for log in logs):
            symbol_logs = sorted(
                [l for l in logs if l["symbol"] == symbol],
                key=lambda x: x["timestamp"]
            )

            buy_price = None
            buy_amount = None

            for log in symbol_logs:
                if log["action"] == "buy":
                    buy_price = log["price"]
                    buy_amount = float(log["amount"])
                elif log["action"] == "sell" and buy_price is not None:
                    sell_price = log["price"]
                    sell_amount = float(log["amount"])
                    pnl = (sell_price - buy_price) * min(buy_amount, sell_amount)
                    pnl_by_symbol[symbol] = pnl_by_symbol.get(symbol, 0) + pnl
                    trade_count_by_symbol[symbol] = trade_count_by_symbol.get(symbol, 0) + 1
                    buy_price = None

    # ポジション情報を取得
    positions = {}
    for symbol_config in config.symbols:
        symbol = symbol_config.symbol
        crypto = get_crypto_currency(symbol)
        position = load_position(symbol)

        if position is not None:
            current_price = btc_price if crypto == "BTC" else eth_price
            crypto_balance_now = btc_balance if crypto == "BTC" else eth_balance
            unrealized_pnl = (current_price - position.entry_price) * crypto_balance_now
            unrealized_pnl_pct = (current_price - position.entry_price) / position.entry_price * 100

            positions[symbol] = {
                "entry_price": position.entry_price,
                "entry_time": position.entry_time,
                "amount": position.amount,
                "current_price": current_price,
                "current_amount": crypto_balance_now,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
            }

    return {
        "timestamp": datetime.now().isoformat(),
        "balances": {
            "jpy": jpy_balance,
            "btc": btc_balance,
            "eth": eth_balance,
        },
        "prices": {
            "btc": btc_price,
            "eth": eth_price,
        },
        "values": {
            "btc_jpy": btc_balance * btc_price,
            "eth_jpy": eth_balance * eth_price,
            "total_jpy": jpy_balance + btc_balance * btc_price + eth_balance * eth_price,
        },
        "trends": trends,
        "positions": positions,
        "pnl": pnl_by_symbol,
        "trade_counts": trade_count_by_symbol,
        "total_pnl": sum(pnl_by_symbol.values()),
    }


def render_html(data: dict) -> str:
    """HTMLをレンダリングする。"""
    # トレンドの表示
    def trend_badge(trend: str) -> str:
        if trend == Trend.UPTREND:
            return '<span style="color: #22c55e;">上昇</span>'
        elif trend == Trend.DOWNTREND:
            return '<span style="color: #ef4444;">下降</span>'
        else:
            return '<span style="color: #eab308;">横ばい</span>'

    # 損益の表示
    def pnl_color(pnl: float) -> str:
        if pnl > 0:
            return "color: #22c55e;"
        elif pnl < 0:
            return "color: #ef4444;"
        return ""

    trends_html = ""
    for symbol, trend in data["trends"].items():
        crypto = get_crypto_currency(symbol)
        status = "取引停止中" if trend == Trend.DOWNTREND and crypto == "BTC" else ""
        trends_html += f"""
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #333;">
            <span>{symbol}</span>
            <span>{trend_badge(trend)} {status}</span>
        </div>
        """

    pnl_html = ""
    for symbol, pnl in data["pnl"].items():
        count = data["trade_counts"].get(symbol, 0)
        pnl_html += f"""
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #333;">
            <span>{symbol}</span>
            <span style="{pnl_color(pnl)}">{pnl:+,.0f}円 ({count}取引)</span>
        </div>
        """

    if not pnl_html:
        pnl_html = '<div style="padding: 8px 0; color: #888;">取引履歴なし</div>'

    total_pnl = data["total_pnl"]

    # ポジション情報の表示（テーブル形式）
    if data["positions"]:
        positions_rows = ""
        for symbol, pos in data["positions"].items():
            crypto = get_crypto_currency(symbol)
            entry_time = pos["entry_time"][:16].replace("T", " ") if pos["entry_time"] else "-"
            # 購入時の総額と現在の評価額（購入数量ベースで計算）
            entry_total = pos["entry_price"] * pos["amount"]
            current_total = pos["current_price"] * pos["amount"]
            diff = current_total - entry_total
            positions_rows += f"""
            <tr style="border-bottom: 1px solid #333;">
                <td style="padding: 10px 4px;">{crypto}</td>
                <td style="text-align: right; padding: 10px 4px;">¥{entry_total:,.0f}</td>
                <td style="text-align: right; padding: 10px 4px;">¥{current_total:,.0f}</td>
                <td style="text-align: right; padding: 10px 4px; {pnl_color(diff)}">{diff:+,.0f}</td>
                <td style="text-align: right; padding: 10px 4px; font-size: 12px; color: #aaa;">{entry_time}</td>
            </tr>
            """
        positions_html = f"""
        <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
            <thead>
                <tr style="border-bottom: 1px solid #444; color: #888;">
                    <th style="text-align: left; padding: 8px 4px;">通貨</th>
                    <th style="text-align: right; padding: 8px 4px;">エントリー</th>
                    <th style="text-align: right; padding: 8px 4px;">現在</th>
                    <th style="text-align: right; padding: 8px 4px;">差額</th>
                    <th style="text-align: right; padding: 8px 4px;">購入日時</th>
                </tr>
            </thead>
            <tbody>
                {positions_rows}
            </tbody>
        </table>
        """
    else:
        positions_html = '<div style="padding: 8px 0; color: #888;">ポジションなし</div>'

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #111;
            color: #fff;
            padding: 20px;
            max-width: 600px;
            margin: 0 auto;
        }}
        .card {{
            background: #1a1a1a;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }}
        .card-title {{
            font-size: 14px;
            color: #888;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .balance-item {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #333;
        }}
        .balance-item:last-child {{
            border-bottom: none;
        }}
        .balance-value {{
            font-weight: 600;
        }}
        .balance-sub {{
            color: #888;
            font-size: 12px;
        }}
        .total {{
            font-size: 24px;
            font-weight: 700;
            padding-top: 12px;
        }}
        .updated {{
            text-align: center;
            color: #666;
            font-size: 12px;
            margin-top: 20px;
        }}
        .refresh-btn {{
            background: #333;
            border: none;
            color: #fff;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            margin-top: 10px;
        }}
        .refresh-btn:hover {{
            background: #444;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="card-title">資産状況</div>
        <div class="balance-item">
            <span>JPY</span>
            <div style="text-align: right;">
                <div class="balance-value">¥{data["balances"]["jpy"]:,.0f}</div>
            </div>
        </div>
        <div class="balance-item">
            <span>BTC</span>
            <div style="text-align: right;">
                <div class="balance-value">¥{data["values"]["btc_jpy"]:,.0f}</div>
                <div class="balance-sub">{data["balances"]["btc"]:.8f} BTC</div>
            </div>
        </div>
        <div class="balance-item">
            <span>ETH</span>
            <div style="text-align: right;">
                <div class="balance-value">¥{data["values"]["eth_jpy"]:,.0f}</div>
                <div class="balance-sub">{data["balances"]["eth"]:.8f} ETH</div>
            </div>
        </div>
        <div class="balance-item total">
            <span>合計</span>
            <span>¥{data["values"]["total_jpy"]:,.0f}</span>
        </div>
    </div>

    <div class="card">
        <div class="card-title">損益</div>
        {pnl_html}
        <div style="display: flex; justify-content: space-between; padding: 12px 0 0; font-weight: 600; font-size: 18px;">
            <span>合計</span>
            <span style="{pnl_color(total_pnl)}">{total_pnl:+,.0f}円</span>
        </div>
    </div>

    <div class="card">
        <div class="card-title">保有ポジション</div>
        {positions_html}
    </div>

    <div class="card">
        <div class="card-title">トレンド</div>
        {trends_html}
    </div>

    <div class="updated">
        最終更新: {data["timestamp"][:19].replace("T", " ")}
        <br>
        <button class="refresh-btn" onclick="location.reload()">更新</button>
    </div>
</body>
</html>"""


class handler(BaseHTTPRequestHandler):
    """ダッシュボードのハンドラー。"""

    def do_GET(self):
        # BASIC認証チェック
        auth = self.headers.get("Authorization")
        if not check_auth(auth):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Dashboard"')
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        try:
            data = get_dashboard_data()
            html = render_html(data)

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode())
