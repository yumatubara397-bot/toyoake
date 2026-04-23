"""
Phase 2 Worker - FastAPI メインエントリーポイント
Railway上で起動するHTTPサーバー
"""
import os
import logging
import tempfile
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, BackgroundTasks, Body
from fastapi.responses import JSONResponse, HTMLResponse

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


@app.get("/shukka/test-login", response_class=HTMLResponse)
async def test_login_form():
    """ブラウザで開くとID/PW入力フォームが表示される"""
    return """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>イロドリミドリ ログインテスト</title>
<style>
  body { font-family: sans-serif; max-width: 500px; margin: 40px auto; padding: 20px; }
  h1 { color: #2E75B6; }
  label { display: block; margin-top: 15px; font-weight: bold; }
  input { width: 100%; padding: 10px; font-size: 16px; margin-top: 5px; box-sizing: border-box; }
  button { margin-top: 20px; padding: 12px 24px; background: #2E75B6; color: white; border: 0; font-size: 16px; border-radius: 4px; cursor: pointer; }
  button:hover { background: #1F4E79; }
  #result { margin-top: 20px; padding: 15px; background: #f5f5f5; border-radius: 4px; white-space: pre-wrap; font-family: monospace; font-size: 13px; display: none; }
  #result.ok { background: #d4edda; color: #155724; }
  #result.err { background: #f8d7da; color: #721c24; }
  .shots a { display: inline-block; margin: 2px 5px 0 0; background: #2E75B6; color: white; padding: 4px 10px; border-radius: 3px; text-decoration: none; font-size: 12px; }
</style>
</head>
<body>
<h1>🔐 イロドリミドリ ログインテスト</h1>
<p>ID / パスワードは送信時のみ使われ、保存されません。</p>

<label>ユーザーID</label>
<input id="uid" type="text" placeholder="tensawa0" autocomplete="off">

<label>パスワード</label>
<input id="pw" type="password" placeholder="パスワードを入力" autocomplete="off">

<button onclick="doTest()">ログインテスト実行</button>

<div id="result"></div>

<script>
async function doTest() {
  const uid = document.getElementById('uid').value;
  const pw = document.getElementById('pw').value;
  const result = document.getElementById('result');
  result.style.display = 'block';
  result.className = '';
  result.textContent = '⏳ 実行中...ブラウザが起動してログイン操作中（最大60秒）';
  try {
    const r = await fetch('/shukka/test-login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user_id: uid, password: pw})
    });
    const j = await r.json();
    result.className = j.status === 'ok' ? 'ok' : 'err';
    let html = (j.status === 'ok' ? '✅ ' : '❌ ') + j.message + '\\n\\nスクリーンショット:\\n';
    result.textContent = html;
    if (j.screenshots && j.screenshots.length > 0) {
      const div = document.createElement('div');
      div.className = 'shots';
      j.screenshots.forEach(s => {
        const a = document.createElement('a');
        a.href = '/shot/' + s;
        a.target = '_blank';
        a.textContent = s;
        div.appendChild(a);
      });
      result.appendChild(div);
    }
  } catch(e) {
    result.className = 'err';
    result.textContent = '⚠ 通信エラー: ' + e.message;
  }
}
</script>
</body>
</html>
"""


@app.post("/shukka/test-login")
async def test_login(
    body: dict = Body(default_factory=dict),
    authorization: str | None = Header(None),
):
    """
    ログインのみテスト（POST版）
    ボディ: {"user_id": "xxx", "password": "yyy"}
    """
    _check_auth(authorization)

    user_id = body.get("user_id") or None
    password = body.get("password") or None

    # 一時的にconfigを上書き（このリクエスト中だけ）
    import config as _cfg
    original_user = _cfg.IM_USER_ID
    original_pw = _cfg.IM_PASSWORD
    if user_id:
        _cfg.IM_USER_ID = user_id
    if password:
        _cfg.IM_PASSWORD = password

    shots = []
    try:
        async with ShukkaWorker() as worker:
            ok = await worker.login()
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
    finally:
        _cfg.IM_USER_ID = original_user
        _cfg.IM_PASSWORD = original_pw


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
