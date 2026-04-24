"""
花出品 Telegramボット メイン

会話フロー:
  /start → 箱番号の写真要求 → OCR → 確認
  → (花ループ開始) 全体写真 → アップ写真
  → 品種 → サイズ → 値段 → 入数 → 口数
  → 確認 → 完了 → Google保存（ユーザー別シート）
  → 次の花 or 新しい箱 or 終了

各ステップに「⬅ 戻る」ボタン付き。
"""
import logging
from io import BytesIO
from math import floor

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

import config
import claude_vision
import google_services as gs

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ============================================================
# ステート定義
# ============================================================
(
    WAIT_BOX_PHOTO,       # 箱番号の写真待ち
    CONFIRM_BOX,          # OCR結果の確認
    INPUT_BOX_MANUAL,     # 箱番号の手入力
    WAIT_FLOWER_1,        # 全体写真待ち
    WAIT_FLOWER_2,        # アップ写真待ち
    CHOOSE_HINSHU,        # 品種選択
    CHOOSE_SIZE,          # サイズ選択
    INPUT_SIZE_MANUAL,    # サイズ手入力
    CHOOSE_NEDAN,         # 値段選択
    INPUT_NEDAN_MANUAL,   # 値段手入力
    CHOOSE_IRISU,         # 入数選択
    INPUT_IRISU_MANUAL,   # 入数手入力
    CHOOSE_KUCHISU,       # 口数選択
    INPUT_KUCHISU_MANUAL, # 口数手入力
    CONFIRM_FLOWER,       # 最終確認
    AFTER_SAVE,           # 保存後、次どうするか
) = range(16)


# ============================================================
# 認証＆ヘルパー
# ============================================================

def _is_authorized(update: Update) -> bool:
    """TELEGRAM_USER_ID が設定されていない場合は誰でも通過、設定されていればそのIDだけ通過"""
    if config.TELEGRAM_USER_ID is None:
        return True
    user = update.effective_user
    return user is not None and user.id == config.TELEGRAM_USER_ID


async def _guard(update: Update) -> bool:
    if _is_authorized(update):
        return True
    if update.message:
        await update.message.reply_text("このボットは許可されたユーザー専用です。")
    elif update.callback_query:
        await update.callback_query.answer("権限がありません", show_alert=True)
    return False


def _buttons(options, prefix: str, per_row: int = 3, extra=None, with_back: bool = False):
    """オプションリストからインラインボタン配列を組み立て"""
    buttons = []
    row = []
    for opt in options:
        row.append(InlineKeyboardButton(str(opt), callback_data=f"{prefix}:{opt}"))
        if len(row) == per_row:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if extra:
        for e in extra:
            buttons.append([InlineKeyboardButton(e[0], callback_data=e[1])])
    if with_back:
        buttons.append([InlineKeyboardButton("⬅ 戻る", callback_data=f"{prefix}_back")])
    return InlineKeyboardMarkup(buttons)


async def _send_or_edit(source, text: str, **kwargs):
    """
    source が callback_query なら edit、message/update なら reply_text。
    キーボード付きメッセージを送るのに使う。
    """
    if hasattr(source, "edit_message_text"):
        try:
            await source.edit_message_text(text, **kwargs)
        except Exception:
            # 元がメディアメッセージだと編集できないことがあるので reply で補完
            if hasattr(source, "message") and source.message:
                await source.message.reply_text(text, **kwargs)
    elif hasattr(source, "reply_text"):
        await source.reply_text(text, **kwargs)


# ============================================================
# /start
# ============================================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    ctx.user_data.clear()
    # 認証通過したら username を覚えておく
    user = update.effective_user
    if user:
        ctx.user_data["_username"] = user.username
        ctx.user_data["_user_id"] = user.id

    await update.message.reply_text(
        "花出品ボットへようこそ。\n\n"
        "まず、箱番号の写真を撮って送ってください。",
        reply_markup=ReplyKeyboardRemove(),
    )
    return WAIT_BOX_PHOTO


# ============================================================
# 箱番号の写真 → OCR
# ============================================================

async def handle_box_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    photo = update.message.photo[-1]
    file = await photo.get_file()
    buf = BytesIO()
    await file.download_to_memory(buf)
    buf.seek(0)

    await update.message.reply_text("箱番号を読み取り中…")
    box_number = claude_vision.read_box_number(buf.getvalue())

    if not box_number:
        await update.message.reply_text(
            "読み取れませんでした。箱番号を手入力してください（最大8桁の英数字）。"
        )
        return INPUT_BOX_MANUAL

    ctx.user_data["box_number"] = box_number
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ OK", callback_data="box_ok"),
            InlineKeyboardButton("✏️ 修正", callback_data="box_fix"),
        ]
    ])
    await update.message.reply_text(
        f"箱番号を「{box_number}」と読み取りました。よろしいですか?",
        reply_markup=kb,
    )
    return CONFIRM_BOX


async def handle_confirm_box(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "box_ok":
        await q.edit_message_text(
            f"箱番号: {ctx.user_data['box_number']} で確定しました。\n\n"
            "花の全体写真を撮って送ってください（1枚目）。"
        )
        # 戻るボタンは写真送信中は使えないので、メッセージでの案内のみ
        return WAIT_FLOWER_1
    else:  # box_fix
        await q.edit_message_text(
            "箱番号を手入力してください（最大8桁の英数字）。"
        )
        return INPUT_BOX_MANUAL


async def handle_box_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    text = update.message.text.strip().upper()
    cleaned = "".join(c for c in text if c.isalnum())
    if not cleaned or len(cleaned) > 8:
        await update.message.reply_text(
            "箱番号は最大8桁の英数字です。もう一度入力してください。"
        )
        return INPUT_BOX_MANUAL

    ctx.user_data["box_number"] = cleaned
    await update.message.reply_text(
        f"箱番号: {cleaned} で確定しました。\n\n"
        "花の全体写真を撮って送ってください（1枚目）。"
    )
    return WAIT_FLOWER_1


# ============================================================
# 花の写真 2枚（戻るボタンは写真送信中のみ「/cancel」で代替）
# ============================================================

async def handle_flower_1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    photo = update.message.photo[-1]
    file = await photo.get_file()
    buf = BytesIO()
    await file.download_to_memory(buf)
    ctx.user_data["photo_zentai"] = buf.getvalue()

    # 戻るボタン付きで次へ誘導
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ 戻って1枚目を撮り直す", callback_data="flower1_back")]
    ])
    await update.message.reply_text(
        "1枚目を受け取りました。次はアップ写真（2枚目）を送ってください。",
        reply_markup=kb,
    )
    return WAIT_FLOWER_2


async def handle_flower1_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """2枚目待ち中に戻る → 1枚目から撮り直し"""
    if not await _guard(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("photo_zentai", None)
    await q.edit_message_text("1枚目を撮り直してください（全体写真）。")
    return WAIT_FLOWER_1


async def handle_flower_2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    photo = update.message.photo[-1]
    file = await photo.get_file()
    buf = BytesIO()
    await file.download_to_memory(buf)
    ctx.user_data["photo_up"] = buf.getvalue()

    return await _ask_hinshu(update.message, ctx)


# ============================================================
# 品種
# ============================================================

async def _ask_hinshu(msg_obj, ctx):
    text = "2枚目を受け取りました。品種を選んでください。"
    kb = _buttons(
        config.HINSHU_LIST, "hinshu", per_row=2,
        extra=[("⬅ 戻って2枚目を撮り直す", "hinshu_back_photo")],
    )
    await _send_or_edit(msg_obj, text, reply_markup=kb)
    return CHOOSE_HINSHU


async def handle_hinshu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "hinshu_back_photo":
        # 2枚目を撮り直し
        ctx.user_data.pop("photo_up", None)
        await q.edit_message_text("2枚目のアップ写真を撮り直してください。")
        return WAIT_FLOWER_2

    _, value = q.data.split(":", 1)
    ctx.user_data["hinshu"] = value
    return await _ask_size(q, ctx)


# ============================================================
# サイズ
# ============================================================

async def _ask_size(msg_obj, ctx):
    text = f"品種: {ctx.user_data['hinshu']}\n\nサイズを選んでください。"
    kb = _buttons(
        config.SIZE_OPTIONS, "size", per_row=3,
        extra=[
            ("✏️ 手入力", "size_manual"),
            ("⬅ 戻る（品種の選び直し）", "size_back"),
        ],
    )
    await _send_or_edit(msg_obj, text, reply_markup=kb)
    return CHOOSE_SIZE


async def handle_size(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "size_back":
        ctx.user_data.pop("hinshu", None)
        return await _ask_hinshu(q, ctx)

    if q.data == "size_manual":
        await q.edit_message_text(
            "サイズを手入力してください（数値）。\n（前に戻る場合は /back と送信）"
        )
        return INPUT_SIZE_MANUAL

    _, value = q.data.split(":", 1)
    ctx.user_data["size"] = value
    return await _ask_nedan(q, ctx)


async def handle_size_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text == "/back":
        return await _ask_size(update.message, ctx)
    ctx.user_data["size"] = text
    return await _ask_nedan(update.message, ctx)


# ============================================================
# 値段
# ============================================================

async def _ask_nedan(msg_obj, ctx):
    text = f"サイズ: {ctx.user_data['size']}\n\n値段を選んでください。"
    kb = _buttons(
        config.NEDAN_OPTIONS, "nedan", per_row=3,
        extra=[
            ("✏️ 手入力", "nedan_manual"),
            ("⬅ 戻る（サイズの選び直し）", "nedan_back"),
        ],
    )
    await _send_or_edit(msg_obj, text, reply_markup=kb)
    return CHOOSE_NEDAN


async def handle_nedan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "nedan_back":
        ctx.user_data.pop("size", None)
        return await _ask_size(q, ctx)

    if q.data == "nedan_manual":
        await q.edit_message_text(
            "値段を手入力してください（円、数値のみ）。\n（前に戻る場合は /back と送信）"
        )
        return INPUT_NEDAN_MANUAL

    _, value = q.data.split(":", 1)
    ctx.user_data["nedan"] = int(value)
    return await _ask_irisu(q, ctx)


async def handle_nedan_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text == "/back":
        return await _ask_nedan(update.message, ctx)
    try:
        value = int(text)
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("正の整数で入力してください（または /back で戻る）。")
        return INPUT_NEDAN_MANUAL
    ctx.user_data["nedan"] = value
    return await _ask_irisu(update.message, ctx)


# ============================================================
# 入数
# ============================================================

async def _ask_irisu(msg_obj, ctx):
    text = f"値段: {ctx.user_data['nedan']}円\n\n入数を選んでください。"
    kb = _buttons(
        config.IRISU_OPTIONS, "irisu", per_row=3,
        extra=[
            ("✏️ 手入力", "irisu_manual"),
            ("⬅ 戻る(値段の選び直し)", "irisu_back"),
        ],
    )
    await _send_or_edit(msg_obj, text, reply_markup=kb)
    return CHOOSE_IRISU


async def handle_irisu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "irisu_back":
        ctx.user_data.pop("nedan", None)
        return await _ask_nedan(q, ctx)

    if q.data == "irisu_manual":
        await q.edit_message_text(
            "入数を手入力してください（整数）。\n（前に戻る場合は /back と送信）"
        )
        return INPUT_IRISU_MANUAL

    _, value = q.data.split(":", 1)
    ctx.user_data["irisu"] = int(value)
    return await _ask_kuchisu(q, ctx)


async def handle_irisu_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text == "/back":
        return await _ask_irisu(update.message, ctx)
    try:
        value = int(text)
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("正の整数で入力してください（または /back で戻る）。")
        return INPUT_IRISU_MANUAL
    ctx.user_data["irisu"] = value
    return await _ask_kuchisu(update.message, ctx)


# ============================================================
# 口数
# ============================================================

async def _ask_kuchisu(msg_obj, ctx):
    nedan = ctx.user_data["nedan"]
    irisu = ctx.user_data["irisu"]
    tanka = floor(nedan / irisu)
    ctx.user_data["kibou_tanka"] = tanka

    text = (
        f"入数: {irisu}\n"
        f"希望単価: {tanka}円 (= {nedan}÷{irisu}、小数点切り捨て)\n\n"
        "口数を選んでください。"
    )
    kb = _buttons(
        config.KUCHISU_OPTIONS, "kuchisu", per_row=3,
        extra=[
            ("✏️ 手入力", "kuchisu_manual"),
            ("⬅ 戻る(入数の選び直し)", "kuchisu_back"),
        ],
    )
    await _send_or_edit(msg_obj, text, reply_markup=kb)
    return CHOOSE_KUCHISU


async def handle_kuchisu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "kuchisu_back":
        ctx.user_data.pop("irisu", None)
        ctx.user_data.pop("kibou_tanka", None)
        return await _ask_irisu(q, ctx)

    if q.data == "kuchisu_manual":
        await q.edit_message_text(
            "口数を手入力してください（整数）。\n（前に戻る場合は /back と送信）"
        )
        return INPUT_KUCHISU_MANUAL

    _, value = q.data.split(":", 1)
    ctx.user_data["kuchisu"] = int(value)
    return await _show_confirm(q, ctx)


async def handle_kuchisu_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text == "/back":
        return await _ask_kuchisu(update.message, ctx)
    try:
        value = int(text)
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("正の整数で入力してください（または /back で戻る）。")
        return INPUT_KUCHISU_MANUAL
    ctx.user_data["kuchisu"] = value
    return await _show_confirm(update.message, ctx)


# ============================================================
# 確認 → 保存
# ============================================================

async def _show_confirm(msg_obj, ctx):
    d = ctx.user_data
    summary = (
        "【入力内容の確認】\n"
        f"箱番号: {d['box_number']}\n"
        f"品種: {d['hinshu']}\n"
        f"サイズ: {d['size']}\n"
        f"値段: {d['nedan']}円\n"
        f"入数: {d['irisu']}\n"
        f"希望単価: {d['kibou_tanka']}円\n"
        f"口数: {d['kuchisu']}\n"
        "\nこの内容で保存しますか？"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 完了", callback_data="save_ok"),
            InlineKeyboardButton("⬅ 戻る(口数の選び直し)", callback_data="save_back"),
        ],
        [
            InlineKeyboardButton("❌ キャンセル", callback_data="save_cancel"),
        ],
    ])
    await _send_or_edit(msg_obj, summary, reply_markup=kb)
    return CONFIRM_FLOWER


async def handle_confirm_flower(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "save_back":
        ctx.user_data.pop("kuchisu", None)
        return await _ask_kuchisu(q, ctx)

    if q.data == "save_cancel":
        await q.edit_message_text(
            "キャンセルしました。\n\n/start で最初からやり直してください。"
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    # save_ok
    await q.edit_message_text("保存中…")
    d = ctx.user_data
    try:
        folder_id = gs.get_or_create_box_folder(d["box_number"])

        flower_count = d.get("flower_count_in_box", 0) + 1
        d["flower_count_in_box"] = flower_count

        zentai_name = f"flower{flower_count}_zentai.jpg"
        up_name = f"flower{flower_count}_up.jpg"

        zentai_url = gs.upload_photo(folder_id, zentai_name, d["photo_zentai"])
        up_url = gs.upload_photo(folder_id, up_name, d["photo_up"])

        sheet_name = gs.append_row(
            {
                "box_number": d["box_number"],
                "hinshu": d["hinshu"],
                "size": d["size"],
                "nedan": d["nedan"],
                "irisu": d["irisu"],
                "kibou_tanka": d["kibou_tanka"],
                "kuchisu": d["kuchisu"],
                "zentai_url": zentai_url,
                "up_url": up_url,
            },
            username=d.get("_username"),
            user_id=d.get("_user_id"),
        )
    except Exception as e:
        logger.exception("保存失敗: %s", e)
        await q.message.reply_text(
            f"⚠ 保存中にエラーが発生しました:\n{e}\n\n"
            "/start でやり直してください。"
        )
        return ConversationHandler.END

    # 次どうするか
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌸 同じ箱で次の花", callback_data="next_flower")],
        [InlineKeyboardButton("📦 新しい箱へ", callback_data="new_box")],
        [InlineKeyboardButton("🏁 終了", callback_data="finish")],
    ])
    await q.message.reply_text(
        f"✅ 保存しました（シート: {sheet_name} / 箱 {d['box_number']} / 花 {flower_count}枚目）",
        reply_markup=kb,
    )
    return AFTER_SAVE


async def handle_after_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "next_flower":
        # 写真情報だけクリアして続行
        for k in ["photo_zentai", "photo_up", "hinshu", "size",
                  "nedan", "irisu", "kibou_tanka", "kuchisu"]:
            ctx.user_data.pop(k, None)
        await q.edit_message_text(
            f"同じ箱（{ctx.user_data['box_number']}）で続けます。\n\n"
            "次の花の全体写真を送ってください。"
        )
        return WAIT_FLOWER_1

    elif q.data == "new_box":
        # username/user_id は残す
        username = ctx.user_data.get("_username")
        user_id = ctx.user_data.get("_user_id")
        ctx.user_data.clear()
        if username:
            ctx.user_data["_username"] = username
        if user_id:
            ctx.user_data["_user_id"] = user_id
        await q.edit_message_text(
            "新しい箱を始めます。\n\n箱番号の写真を撮って送ってください。"
        )
        return WAIT_BOX_PHOTO

    else:  # finish
        ctx.user_data.clear()
        await q.edit_message_text(
            "🏁 お疲れさまでした。作業を終了します。\n\n"
            "再開するときは /start を送ってください。"
        )
        return ConversationHandler.END


# ============================================================
# /cancel / fallback
# ============================================================

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "キャンセルしました。/start でやり直してください。",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def unknown_in_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "今はその操作ができません。画面の指示に従うか、/cancel で中断できます。"
        )


# ============================================================
# Application構築
# ============================================================

def main():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            WAIT_BOX_PHOTO: [MessageHandler(filters.PHOTO, handle_box_photo)],
            CONFIRM_BOX: [CallbackQueryHandler(handle_confirm_box, pattern="^box_(ok|fix)$")],
            INPUT_BOX_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_box_manual)],

            WAIT_FLOWER_1: [MessageHandler(filters.PHOTO, handle_flower_1)],
            WAIT_FLOWER_2: [
                MessageHandler(filters.PHOTO, handle_flower_2),
                CallbackQueryHandler(handle_flower1_back, pattern="^flower1_back$"),
            ],

            CHOOSE_HINSHU: [
                CallbackQueryHandler(handle_hinshu, pattern="^(hinshu:|hinshu_back_photo$)"),
            ],

            CHOOSE_SIZE: [CallbackQueryHandler(handle_size, pattern="^(size:|size_manual$|size_back$)")],
            INPUT_SIZE_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_size_manual)],

            CHOOSE_NEDAN: [CallbackQueryHandler(handle_nedan, pattern="^(nedan:|nedan_manual$|nedan_back$)")],
            INPUT_NEDAN_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_nedan_manual)],

            CHOOSE_IRISU: [CallbackQueryHandler(handle_irisu, pattern="^(irisu:|irisu_manual$|irisu_back$)")],
            INPUT_IRISU_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_irisu_manual)],

            CHOOSE_KUCHISU: [CallbackQueryHandler(handle_kuchisu, pattern="^(kuchisu:|kuchisu_manual$|kuchisu_back$)")],
            INPUT_KUCHISU_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_kuchisu_manual)],

            CONFIRM_FLOWER: [CallbackQueryHandler(handle_confirm_flower, pattern="^save_(ok|cancel|back)$")],
            AFTER_SAVE: [CallbackQueryHandler(handle_after_save, pattern="^(next_flower|new_box|finish)$")],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            MessageHandler(filters.ALL, unknown_in_conv),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
