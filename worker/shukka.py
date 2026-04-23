"""
Phase 2 Worker - Playwright自動化ロジック
イロドリミドリ (im.toyoake.jp) への自動出品処理
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError

from config import (
    IM_LOGIN_URL, IM_USER_ID, IM_PASSWORD,
    IM_OKURI_URL, IM_SEARCH_URL,
    HINMEI_CODE_MAP, DEFAULT_SIZE,
    get_next_market_date,
    DEFAULT_TIMEOUT, SCREENSHOT_DIR,
    SHUKKA_DRY_RUN,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# スクリーンショット保存先の準備
Path(SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)


async def _shot(page: Page, name: str):
    """ステップごとにスクリーンショットを保存（デバッグ用）"""
    path = f"{SCREENSHOT_DIR}/{name}.png"
    try:
        await page.screenshot(path=path, full_page=True)
        log.info(f"📸 Screenshot saved: {path}")
    except Exception as e:
        log.warning(f"Screenshot failed ({name}): {e}")


class ShukkaItem:
    """出品対象1件分のデータ"""
    def __init__(
        self,
        box_number: str,       # 箱番号（デバッグ用）
        hinshu: str,           # 品種（例: "クラッスラ"）
        size: str,             # サイズ（例: "99.0"）
        nyusu: int,            # 入数（例: 105）
        kuchisuu: int,         # 口数（例: 1）
        kibou_tanka: int,      # 希望単価（例: 47）
        zentai_image_path: str, # 全体画像のローカルパス
        up_image_path: str,    # アップ画像のローカルパス
    ):
        self.box_number = box_number
        self.hinshu = hinshu
        self.size = size
        self.nyusu = nyusu
        self.kuchisuu = kuchisuu
        self.kibou_tanka = kibou_tanka
        self.zentai_image_path = zentai_image_path
        self.up_image_path = up_image_path

    def __repr__(self):
        return (
            f"ShukkaItem(box={self.box_number}, 品種={self.hinshu}, "
            f"サイズ={self.size}, 入数={self.nyusu}, 口数={self.kuchisuu}, "
            f"希望単価={self.kibou_tanka})"
        )


class ShukkaWorker:
    """イロドリミドリへの自動出品ワーカー"""

    def __init__(self):
        self.browser = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._pw = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        # headless=True（Railway上で動かすため）
        # 1件テスト時に false にしたい場合は環境変数で切り替え可能に
        headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
        self.browser = await self._pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        self.context.set_default_timeout(DEFAULT_TIMEOUT)
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
        finally:
            if self._pw:
                await self._pw.stop()

    # ==================== ログイン ====================
    async def login(self) -> bool:
        """イロドリミドリへログイン"""
        log.info(f"🔐 Loading login page: {IM_LOGIN_URL}")
        await self.page.goto(IM_LOGIN_URL)
        await _shot(self.page, "01_login_before")

        # ログインフォームのセレクタは実際の画面を見て調整が必要
        # 一般的な name 属性で探す
        try:
            # ユーザーID入力（name="userid" や "username" の可能性）
            user_input = self.page.locator(
                'input[name="userid"], input[name="username"], input[name="user_id"], input[type="text"]'
            ).first
            await user_input.fill(IM_USER_ID)

            # パスワード入力
            pw_input = self.page.locator('input[type="password"]').first
            await pw_input.fill(IM_PASSWORD)

            await _shot(self.page, "02_login_filled")

            # ログインボタン
            submit_btn = self.page.locator(
                'input[type="submit"], button[type="submit"], button:has-text("ログイン"), input[value*="ログイン"]'
            ).first
            await submit_btn.click()

            # トップページへの遷移を待つ
            await self.page.wait_for_url("**/shukka/top/**", timeout=DEFAULT_TIMEOUT)
            await _shot(self.page, "03_login_after")
            log.info("✅ ログイン成功")
            return True
        except PlaywrightTimeoutError:
            log.error("❌ ログイン失敗（タイムアウト）")
            await _shot(self.page, "99_login_error")
            return False
        except Exception as e:
            log.error(f"❌ ログイン失敗: {e}")
            await _shot(self.page, "99_login_error")
            return False

    # ==================== 送り状入力ページへ遷移 ====================
    async def goto_okuri_page(self):
        """送り状入力ページへ遷移"""
        log.info("📝 送り状入力ページへ遷移")
        await self.page.goto(IM_OKURI_URL)
        await self.page.wait_for_load_state("networkidle")
        await _shot(self.page, "04_okuri_page")

    # ==================== 1件登録 ====================
    async def register_one(self, item: ShukkaItem) -> tuple[bool, str]:
        """
        1件だけ登録する
        戻り値: (成功フラグ, メッセージ)
        """
        log.info(f"--- 登録開始: {item} ---")

        # 品種コードの取得
        hinmei_code = HINMEI_CODE_MAP.get(item.hinshu)
        if not hinmei_code:
            return False, f"品種コード未定義: {item.hinshu}"

        try:
            # ステップA: 開市日（既に初期値で月曜が入っているケースが多いので、現状は自動入力済みを前提）
            # 必要なら日付ピッカーを操作するコードを追加

            # ステップB: 品名検索ポップアップを開く
            # 品名欄の右にある 🔍 アイコンをクリック
            log.info("🔎 品名検索ポップアップを開く")
            search_icon = self.page.locator('img[src*="btn_search"], img[alt*="検索"]').first
            async with self.context.expect_page() as popup_info:
                await search_icon.click()
            popup = await popup_info.value
            await popup.wait_for_load_state()
            await _shot(popup, "05_popup_opened")

            # ステップC: ポップアップでカナ名称検索欄に品種名を入力
            kana_input = popup.locator('input[type="text"]').first
            await kana_input.fill(item.hinshu)
            # 検索ボタンをクリック
            search_btn = popup.locator('input[type="button"], button').filter(has_text="検索").first
            await search_btn.click()
            await popup.wait_for_load_state("networkidle")
            await _shot(popup, "06_popup_searched")

            # ステップD: 品名コードで一致する行の「選択」ボタンを押す
            # 品名コード列（2列目）に一致する行を特定
            log.info(f"🎯 品名コード {hinmei_code} の行を選択")

            # テーブル内のすべての行を検索し、品名コードセルが一致する行の「選択」ボタンを押す
            target_row = popup.locator(f'tr:has(td:has-text("{hinmei_code}"))').first

            # 選択ボタンをクリック（ポップアップはこの操作で閉じる）
            select_btn = target_row.locator('input[type="button"], button').filter(has_text="選択").first
            await select_btn.click()

            # ポップアップが閉じて元のページに戻るのを待つ
            try:
                await popup.wait_for_event("close", timeout=10000)
            except PlaywrightTimeoutError:
                log.warning("ポップアップが自動で閉じなかった")

            await self.page.wait_for_load_state("networkidle")
            await _shot(self.page, "07_hinmei_filled")

            # ステップE: サイズ（プルダウン）
            log.info(f"📏 サイズ: {item.size}")
            # name属性は不明なので、label「サイズ」の近くの select を探す
            size_select = self.page.locator('select').first  # 最初のselectがサイズと仮定
            await size_select.select_option(label=item.size)

            # ステップF: 入数
            log.info(f"📦 入数: {item.nyusu}")
            # 入数欄は「入数」ラベルの後の input
            nyusu_input = self.page.locator('input[type="text"]').nth(1)  # 品名=0, 入数=?位置は要調整
            await nyusu_input.fill(str(item.nyusu))

            # ステップG: 口数
            log.info(f"🔢 口数: {item.kuchisuu}")
            kuchi_input = self.page.locator('input[type="text"]').nth(2)
            await kuchi_input.fill(str(item.kuchisuu))

            # ステップH: 希望単価
            log.info(f"💰 希望単価: {item.kibou_tanka}")
            tanka_input = self.page.locator('input[name*="Kibou"], input[name*="tanka"]').first
            await tanka_input.fill(str(item.kibou_tanka))

            await _shot(self.page, "08_fields_filled")

            # ステップI: 画像アップロード（全体・アップ）
            log.info(f"🖼 全体画像: {item.zentai_image_path}")
            # カメラアイコン＝画像アップロード用のinput[type=file]
            # クリックで開くよりも、setInputFiles の方が確実
            zentai_input = self.page.locator('input[type="file"]').nth(0)
            await zentai_input.set_input_files(item.zentai_image_path)

            log.info(f"🖼 アップ画像: {item.up_image_path}")
            up_input = self.page.locator('input[type="file"]').nth(1)
            await up_input.set_input_files(item.up_image_path)

            await self.page.wait_for_timeout(2000)  # アップロード処理待ち
            await _shot(self.page, "09_images_uploaded")

            # ステップJ: 一覧に登録
            if SHUKKA_DRY_RUN:
                log.warning("⚠ DRY_RUN モード: 「一覧に登録」は押しません")
                await _shot(self.page, "10_before_submit_DRYRUN")
                return True, "dry_run_completed"
            else:
                log.info("🚀 「一覧に登録」クリック")
                submit_btn = self.page.locator('input[value*="一覧に登録"], button:has-text("一覧に登録")').first
                await submit_btn.click()
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(2000)
                await _shot(self.page, "10_after_submit")

                # 成功判定：フォームの品名欄が空になっていれば成功
                hinmei_field = self.page.locator('input[name*="Hinmei"], input[name="TextName"]').first
                try:
                    val = await hinmei_field.input_value()
                    if not val:
                        log.info("✅ 登録成功（フォームがクリアされた）")
                        return True, "success"
                    else:
                        log.warning("⚠ フォームがクリアされていない")
                        return False, "form_not_cleared"
                except Exception as e:
                    log.warning(f"成功判定できず: {e}")
                    return True, "submitted_but_unknown"

        except Exception as e:
            log.error(f"❌ 登録エラー: {e}", exc_info=True)
            await _shot(self.page, "99_register_error")
            return False, f"exception: {e}"


# ==================== テスト実行用 エントリーポイント ====================
async def test_one_item():
    """
    Step 2 テスト: BB54のクラッスラ1件を登録
    使い方: python shukka.py
    """
    # テスト用データ（BB54 クラッスラ）
    item = ShukkaItem(
        box_number="BB54",
        hinshu="クラッスラ",
        size=DEFAULT_SIZE,  # 99.0
        nyusu=105,
        kuchisuu=1,
        kibou_tanka=47,
        zentai_image_path="/tmp/test_zentai.jpg",  # 実際のパスに置き換え
        up_image_path="/tmp/test_up.jpg",
    )

    async with ShukkaWorker() as worker:
        # ログイン
        if not await worker.login():
            log.error("ログインに失敗したため終了")
            return

        # 送り状入力ページへ
        await worker.goto_okuri_page()

        # 1件登録
        success, msg = await worker.register_one(item)
        log.info(f"結果: success={success}, msg={msg}")


if __name__ == "__main__":
    asyncio.run(test_one_item())
