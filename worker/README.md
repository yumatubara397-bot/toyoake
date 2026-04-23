# Toyoake Shukka Worker (Phase 2)

イロドリミドリへの自動出品ワーカー。Phase 1 のTelegramボットとは別サービスとしてRailwayに追加デプロイする。

## Step 2 テスト内容

現在のコードは「Step 2: 1件だけテスト登録」です。
- エンドポイント `POST /shukka/start` を叩くと、ハードコードされた BB54 クラッスラ1件を登録します
- ダミー画像（緑の100x100px）を自動生成して使用します
- 動作確認後、Step 3 以降でスプレッドシート連携に拡張していきます

## Railway にデプロイする方法（Phase 1 と同じリポジトリに追加）

### 1. このworker/フォルダをphase 1 リポジトリに追加
```
toyoake/
├── bot.py              (既存)
├── google_services.py  (既存)
├── ...
└── worker/             (このフォルダを追加)
    ├── main.py
    ├── shukka.py
    ├── config.py
    ├── requirements.txt
    ├── Dockerfile
    └── ...
```

### 2. GitHub に push
```bash
git add worker
git commit -m "Phase 2 worker initial commit"
git push
```

### 3. Railway で新サービス追加
- Railway の `supportive-clarity` (toyoake) プロジェクトを開く
- 「+ New」→「GitHub Repo」→ 同じリポジトリを選択
- 「Root Directory」を `worker` に設定
- Dockerfile を自動検出してビルド

### 4. 環境変数を設定
Railway の新サービス設定 → Variables で以下を追加:

| 変数名 | 値 |
|---|---|
| IM_USER_ID | tensawa0 |
| IM_PASSWORD | tensawa3350002 |
| SHUKKA_SHARED_SECRET | （ランダムな32文字） |
| SHUKKA_DRY_RUN | false |

### 5. デプロイ完了を待つ
Railway のログで「Uvicorn running on http://0.0.0.0:xxxx」を確認。

### 6. テスト実行
Railway の生成URL（例: toyoake-worker-xxxx.up.railway.app）に対して:

```bash
# ログインのみテスト
curl -X POST https://your-app.up.railway.app/shukka/test-login \
  -H "Authorization: Bearer YOUR_SECRET"

# 1件登録テスト
curl -X POST https://your-app.up.railway.app/shukka/start \
  -H "Authorization: Bearer YOUR_SECRET"

# 進捗確認
curl https://your-app.up.railway.app/shukka/status
```

## 成功 / 失敗の確認方法

1. **Railway のログ** を見る（各ステップにログ出力あり）
2. **スクリーンショット** が `/tmp/shukka_shots/` に保存される
3. **イロドリミドリにログイン** して送り状入力データ一覧にBB54 クラッスラが追加されているか確認

## Step 2 で確認すべきこと

- [ ] Playwright が Railway 上で動く
- [ ] イロドリミドリへのログインが成功する
- [ ] 品名検索ポップアップが開いて、「クラッスラ」で検索できる
- [ ] 品名コード `020943` の行の「選択」を押せる
- [ ] サイズ、入数、口数、希望単価が入る
- [ ] 画像アップロードが成功する
- [ ] 「一覧に登録」が正しく動く

## 問題が出たら

- Railway の Deploy Logs を確認
- スクリーンショット（`/tmp/shukka_shots/99_*_error.png`）を確認
- `SHUKKA_DRY_RUN=true` に変更して「登録直前まで」のテストに切り替え
