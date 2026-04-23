"""
Phase 2 Worker - FastAPI メインエントリーポイント
Railway上で起動するHTTPサーバー
"""
import os
import logging
import tempfile
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, BackgroundTasks
from fastapi.responses import JSONResponse

from shukka import ShukkaWorker, ShukkaItem
from config import DEFAULT_SIZE, SCREENSHOT_DIR

log = logging.getLogger(__name__)

app = FastAPI(title="Toyoake Shukka Worker")

# 共有シークレット（GASから呼ぶときの認証）
SHARED_SECRET = os.getenv("SHUKKA_SHARED_SECRET", "")

# 簡易的な進捗保持（メモリ上）
_status = {
    "running": False,
    "done": 0,
    "total": 0,
    "errors": 0,
    "last_message": "",
}


def _check_auth(auth: str | None):
    if not SHARED_SECRET:
        return  # 開発中は認証スキップ
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    token = auth.removeprefix("Bearer ").strip()
    if token != SHARED_SECRET:
        raise HTTPException(status_code=403, detail="Invalid token")


@app.get("/")
async def root():
    return {"status": "ok", "service": "toyoake-shukka-worker"}


@app.get("/shukka/status")
async def get_status():
    return _status


@app.post("/shukka/start")
async def start_shukka(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(None),
):
    """
    出品処理開始エンドポイント
    Step 2 段階では、ハードコードされた BB54 クラッスラ1件を登録する
    """
    _check_auth(authorization)

    if _status["running"]:
        return JSONResponse(
            status_code=409,
            content={"status": "already_running", "message": "既に実行中です"},
        )

    background_tasks.add_task(_run_test_one)
    return {"status": "accepted", "message": "テスト1件の登録を開始しました"}


@app.get("/shukka/test-login")
@app.post("/shukka/test-login")
async def test_login(authorization: str | None = Header(None)):
    """
    ログインのみテスト（Step 2 最初の確認用）
    """
    _check_auth(authorization)

    shots = []
    try:
        async with ShukkaWorker() as worker:
            ok = await worker.login()
            # スクショの一覧を返す
            import os as _os
            if _os.path.exists(SCREENSHOT_DIR):
                shots = sorted(_os.listdir(SCREENSHOT_DIR))
            if ok:
                return {"status": "ok", "message": "ログイン成功", "screenshots": shots}
            else:
                return JSONResponse(
                    status_code=500,
                    content={"status": "error", "message": "ログイン失敗", "screenshots": shots},
                )
    except Exception as e:
        log.error(f"ログインテストエラー: {e}", exc_info=True)
        import os as _os
        if _os.path.exists(SCREENSHOT_DIR):
            shots = sorted(_os.listdir(SCREENSHOT_DIR))
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e), "screenshots": shots}
        )


@app.get("/shot/{filename}")
async def get_screenshot(filename: str):
    """スクリーンショットをブラウザで確認できるエンドポイント"""
    from fastapi.responses import FileResponse
    import os as _os
    # セキュリティ: パス・トラバーサル防止
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = _os.path.join(SCREENSHOT_DIR, filename)
    if not _os.path.exists(path):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)


async def _run_test_one():
    """Step 2 テスト: BB54クラッスラ1件を登録"""
    global _status
    _status.update({"running": True, "done": 0, "total": 1, "errors": 0, "last_message": ""})

    # TODO: Step 3以降でスプレッドシートから画像URLを取得してダウンロードする
    # Step 2 は仮のダミー画像を使う（要、事前準備）

    # ダミー画像の用意（Step 2テスト用）
    zentai_path = "/tmp/test_zentai.jpg"
    up_path = "/tmp/test_up.jpg"

    # もしダミー画像が存在しない場合は、簡単な画像を作る
    if not Path(zentai_path).exists() or not Path(up_path).exists():
        try:
            from PIL import Image
            Path("/tmp").mkdir(exist_ok=True)
            # 100x100の緑色の画像を2枚作る
            img = Image.new("RGB", (100, 100), color=(100, 180, 100))
            img.save(zentai_path, "JPEG")
            img.save(up_path, "JPEG")
            log.info("ダミー画像を生成しました")
        except ImportError:
            _status["last_message"] = "PIL がインストールされていません"
            _status["running"] = False
            return

    item = ShukkaItem(
        box_number="BB54",
        hinshu="クラッスラ",
        size=DEFAULT_SIZE,
        nyusu=105,
        kuchisuu=1,
        kibou_tanka=47,
        zentai_image_path=zentai_path,
        up_image_path=up_path,
    )

    try:
        async with ShukkaWorker() as worker:
            if not await worker.login():
                _status["errors"] = 1
                _status["last_message"] = "ログイン失敗"
                _status["running"] = False
                return

            await worker.goto_okuri_page()
            success, msg = await worker.register_one(item)
            if success:
                _status["done"] = 1
                _status["last_message"] = f"成功: {msg}"
            else:
                _status["errors"] = 1
                _status["last_message"] = f"エラー: {msg}"
    except Exception as e:
        log.error(f"テスト実行エラー: {e}", exc_info=True)
        _status["errors"] = 1
        _status["last_message"] = f"例外: {e}"
    finally:
        _status["running"] = False


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
