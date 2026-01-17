"""ストレージ操作モジュール。

Supabase Storageを使用して学習データを保存する。
"""

from __future__ import annotations

import io
import logging
from datetime import datetime

import pandas as pd

from src.database import get_supabase_client

logger = logging.getLogger(__name__)

BUCKET_NAME = "trading-data"


def ensure_bucket_exists() -> None:
    """バケットが存在することを確認し、なければ作成する。"""
    client = get_supabase_client()

    try:
        client.storage.get_bucket(BUCKET_NAME)
        logger.debug(f"Bucket '{BUCKET_NAME}' exists")
    except Exception:
        client.storage.create_bucket(BUCKET_NAME, options={"public": False})
        logger.info(f"Bucket '{BUCKET_NAME}' created")


def save_ohlcv_data(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> str:
    """OHLCVデータをStorageに保存する。

    Args:
        df: OHLCVデータのDataFrame
        symbol: 通貨ペア（例: 'BTC/USDT'）
        timeframe: 時間足（例: '1h'）

    Returns:
        保存したファイルのパス
    """
    ensure_bucket_exists()
    client = get_supabase_client()

    # ファイル名を生成
    symbol_safe = symbol.replace("/", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = f"ohlcv/{symbol_safe}/{timeframe}/{timestamp}.csv"

    # DataFrameをCSVに変換
    csv_buffer = io.BytesIO()
    df.to_csv(csv_buffer, index=True)
    csv_buffer.seek(0)

    # アップロード
    client.storage.from_(BUCKET_NAME).upload(
        file_path,
        csv_buffer.getvalue(),
        {"content-type": "text/csv"},
    )

    logger.info(f"OHLCV data saved: {file_path}")
    return file_path


def load_ohlcv_data(file_path: str) -> pd.DataFrame:
    """OHLCVデータをStorageから読み込む。

    Args:
        file_path: ファイルパス

    Returns:
        OHLCVデータのDataFrame
    """
    client = get_supabase_client()

    response = client.storage.from_(BUCKET_NAME).download(file_path)

    df = pd.read_csv(io.BytesIO(response), index_col=0, parse_dates=True)
    logger.info(f"OHLCV data loaded: {file_path} ({len(df)} rows)")

    return df


def list_ohlcv_files(
    symbol: str | None = None,
    timeframe: str | None = None,
) -> list[dict]:
    """保存されているOHLCVファイルの一覧を取得する。

    Args:
        symbol: フィルタする通貨ペア
        timeframe: フィルタする時間足

    Returns:
        ファイル情報のリスト
    """
    client = get_supabase_client()

    # パスを構築
    path = "ohlcv"
    if symbol:
        symbol_safe = symbol.replace("/", "_")
        path = f"{path}/{symbol_safe}"
        if timeframe:
            path = f"{path}/{timeframe}"

    try:
        files = client.storage.from_(BUCKET_NAME).list(path)
        return files
    except Exception as e:
        logger.warning(f"Failed to list files: {e}")
        return []


def save_model(
    model_data: bytes,
    model_name: str,
    version: str | None = None,
) -> str:
    """学習済みモデルをStorageに保存する。

    Args:
        model_data: モデルのバイナリデータ
        model_name: モデル名
        version: バージョン（省略時は日時）

    Returns:
        保存したファイルのパス
    """
    ensure_bucket_exists()
    client = get_supabase_client()

    if version is None:
        version = datetime.now().strftime("%Y%m%d_%H%M%S")

    file_path = f"models/{model_name}/{version}.pkl"

    client.storage.from_(BUCKET_NAME).upload(
        file_path,
        model_data,
        {"content-type": "application/octet-stream"},
    )

    logger.info(f"Model saved: {file_path}")
    return file_path


def load_model(file_path: str) -> bytes:
    """学習済みモデルをStorageから読み込む。

    Args:
        file_path: ファイルパス

    Returns:
        モデルのバイナリデータ
    """
    client = get_supabase_client()

    response = client.storage.from_(BUCKET_NAME).download(file_path)
    logger.info(f"Model loaded: {file_path}")

    return response


def delete_file(file_path: str) -> None:
    """ファイルを削除する。

    Args:
        file_path: ファイルパス
    """
    client = get_supabase_client()
    client.storage.from_(BUCKET_NAME).remove([file_path])
    logger.info(f"File deleted: {file_path}")
