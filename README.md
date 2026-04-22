# 花出品 Telegramボット

現場で撮った花の写真と出品情報を、Telegramから Googleスプレッドシート + Google Drive に自動記録するボットです。

## ファイル構成

| ファイル | 役割 |
|----------|------|
| `bot.py` | メイン。会話フロー管理 |
| `claude_vision.py` | Claude APIで箱番号OCR |
| `google_services.py` | Sheets / Drive 連携 |
| `config.py` | 環境変数読み込み |
| `requirements.txt` | 依存パッケージ |
| `Procfile` | Railway起動用 |
| `runtime.txt` | Pythonバージョン |
| `.env.example` | 環境変数サンプル |

## 使い方（ユーザー視点）

1. Telegramで `/start` を送る
2. 箱番号の写真を撮って送る
3. OCR結果を確認（OK / 修正）
4. 花の全体写真（1枚目）を送る
5. 花のアップ写真（2枚目）を送る
6. 品種 → サイズ → 値段 → 入数 → 口数 を選択
7. 内容確認 → 完了
8. 「同じ箱で次の花」「新しい箱へ」「終了」から選択

## ローカルで動作確認する方法

```bash
# 1. 仮想環境（任意）
python3 -m venv .venv
source .venv/bin/activate  # Windowsは .venv\Scripts\activate

# 2. インストール
pip install -r requirements.txt

# 3. .envを作る（.env.example をコピーして値を入れる）
cp .env.example .env
# エディタで .env を編集

# 4. 環境変数を読み込んで起動（Linux/Mac）
export $(cat .env | xargs)
python bot.py

# Windowsの場合は、.envを読み込むpython-dotenvを入れるか、
# set コマンドで環境変数を一つずつ設定してください
```

## Railwayでのデプロイ

別紙「Railway デプロイ手順書」を参照してください。

## トラブル対応

| 症状 | 原因候補 |
|------|----------|
| ボットから返信が来ない | Railway側でプロセスが落ちている。ログを確認 |
| 「権限がありません」と出る | `TELEGRAM_USER_ID` が違う |
| OCRが毎回失敗する | `ANTHROPIC_API_KEY` が無効 or クレジット切れ |
| スプレッドシートに書かれない | サービスアカウントに編集権限が付いてない |
| Driveに保存されない | 同上、親フォルダの共有設定 |

## 修正したいときに触るファイル

- **選択肢（品種・値段・入数など）を変えたい** → `config.py` の `HINSHU_LIST` などを編集
- **OCRのプロンプトを変えたい** → `claude_vision.py` の `_PROMPT`
- **スプレッドシートの列を増やしたい** → `google_services.py` の `append_row` とシートの見出し両方を更新
- **会話フローを変えたい** → `bot.py`
