"""
花出品 Telegramボット メイン

会話フロー:
  /start → 箱番号の写真要求 → OCR → 確認
  → (花ループ開始) 全体写真 → アップ写真
  → 品種 → サイズ → 値段 → 入数 → 口数
  → 確認 → 完了 → Google保存
  → 次の花 or 新しい箱 or 終了
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
    WAIT_BOX_PHOTO,     # 箱番号の写真待ち
    CONFIRM_BOX,        # OCR結果の確認
    INPUT_BOX_MANUAL,   # 箱番号の手入力
    WAIT_FLOWER_1,      # 全体写真待ち
    WAIT_FLOWER_2,      # アップ写真待ち
    CHOOSE_HINSHU,      # 品種選択
    CHOOSE_SIZE,        # サイズ選択
    INPUT_SIZE_MANUAL,  # サイズ手入力
    CHOOSE_NEDAN,       # 値段選択
    INPUT_NEDAN_MANUAL, # 値段手入力
    CHOOSE_IRISU,       # 入数選択
    INPUT_IRISU_MANUAL, # 入数手入力
    CHOOSE_KUCHISU,     # 口数選択
    INPUT_KUCHISU_MANUAL, # 口数手入力
    CONFIRM_FLOWER,     # 最終確認
    AFTER_SAVE,         # 保存後、次どうするか
) = range(16)


# ============================================================
# ヘルパー
# ============================================================

def _is_authorized(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == config.TELEGRAM_USER_ID


def _buttons(options, prefix: str, per_row: int = 3, extra=None):
    """optionsリストからインラインボタンを組み立て"""
    buttons = []
    row = []
    for i, opt in enumerate(options):
        row.append(InlineKeyboardButton(str(opt), callback_data=f"{prefix}:{opt}"))
        if len(row) == per_row:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if extra:
        for e in extra:
            buttons.append([InlineKeyboardButton(e[0], callback_data=e[1])])
    return InlineKeyboardMarkup(buttons)


async def _guard(update: Update) -> bool:
    """認証チェック。未認証なら拒否メッセージを出す"""
    if _is_authorized(update):
        return True
    if update.message:
        await update.message.reply_text("このボットは許可されたユーザー専用です。")
    elif update.callback_query:
        await update.callback_query.answer("権限がありません", show_alert=True)
    return False


# ============================================================
# /start
# ============================================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    ctx.user_data.clear()
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

    photo = update.message.photo[-1]  # 最高解像度
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
    # 英数字のみ、8桁以内か確認
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
# 花の写真 2枚
# ============================================================

async def handle_flower_1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    photo = update.message.photo[-1]
    file = await photo.get_file()
    buf = BytesIO()
    await file.download_to_memory(buf)
    ctx.user_data["photo_zentai"] = buf.getvalue()

    await update.message.reply_text(
        "1枚目を受け取りました。次はアップ写真（2枚目）を送ってください。"
    )
    return WAIT_FLOWER_2


async def handle_flower_2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    photo = update.message.photo[-1]
    file = await photo.get_file()
    buf = BytesIO()
    await file.download_to_memory(buf)
    ctx.user_data["photo_up"] = buf.getvalue()

    # 品種選択へ
    await update.message.reply_text(
        "2枚目を受け取りました。品種を選んでください。",
        reply_markup=_buttons(config.HINSHU_LIST, "hinshu", per_row=2),
    )
    return CHOOSE_HINSHU


# ============================================================
# 品種
# ============================================================

async def handle_hinshu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    _, value = q.data.split(":", 1)
    ctx.user_data["hinshu"] = value

    await q.edit_message_text(
        f"品種: {value}\n\nサイズを選んでください。",
        reply_markup=_buttons(
            config.SIZE_OPTIONS, "size", per_row=3,
            extra=[("✏️ 手入力", "size_manual")],
        ),
    )
    return CHOOSE_SIZE


# ============================================================
# サイズ
# ============================================================

async def handle_size(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "size_manual":
        await q.edit_message_text("サイズを手入力してください（数値）。")
        return INPUT_SIZE_MANUAL

    _, value = q.data.split(":", 1)
    ctx.user_data["size"] = value
    return await _ask_nedan(q, ctx)


async def handle_size_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    ctx.user_data["size"] = update.message.text.strip()
    return await _ask_nedan(update.message, ctx)


async def _ask_nedan(msg_obj, ctx):
    """msg_objはmessage or callback_queryどちらでもOK"""
    text = f"サイズ: {ctx.user_data['size']}\n\n値段を選んでください。"
    kb = _buttons(
        config.NEDAN_OPTIONS, "nedan", per_row=3,
        extra=[("✏️ 手入力", "nedan_manual")],
    )
    if hasattr(msg_obj, "edit_message_text"):
        await msg_obj.edit_message_text(text, reply_markup=kb)
    else:
        await msg_obj.reply_text(text, reply_markup=kb)
    return CHOOSE_NEDAN


# ============================================================
# 値段
# ============================================================

async def handle_nedan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "nedan_manual":
        await q.edit_message_text("値段を手入力してください（円、数値のみ）。")
        return INPUT_NEDAN_MANUAL

    _, value = q.data.split(":", 1)
    ctx.user_data["nedan"] = int(value)
    return await _ask_irisu(q, ctx)


async def handle_nedan_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    try:
        value = int(update.message.text.strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("正の整数で入力してください。")
        return INPUT_NEDAN_MANUAL

    ctx.user_data["nedan"] = value
    return await _ask_irisu(update.message, ctx)


async def _ask_irisu(msg_obj, ctx):
    text = f"値段: {ctx.user_data['nedan']}円\n\n入数を選んでください。"
    kb = _buttons(
        config.IRISU_OPTIONS, "irisu", per_row=3,
        extra=[("✏️ 手入力", "irisu_manual")],
    )
    if hasattr(msg_obj, "edit_message_text"):
        await msg_obj.edit_message_text(text, reply_markup=kb)
    else:
        await msg_obj.reply_text(text, reply_markup=kb)
    return CHOOSE_IRISU


# ============================================================
# 入数
# ============================================================

async def handle_irisu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "irisu_manual":
        await q.edit_message_text("入数を手入力してください（整数）。")
        return INPUT_IRISU_MANUAL

    _, value = q.data.split(":", 1)
    ctx.user_data["irisu"] = int(value)
    return await _ask_kuchisu(q, ctx)


async def handle_irisu_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    try:
        value = int(update.message.text.strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("正の整数で入力してください。")
        return INPUT_IRISU_MANUAL

    ctx.user_data["irisu"] = value
    return await _ask_kuchisu(update.message, ctx)


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
        extra=[("✏️ 手入力", "kuchisu_manual")],
    )
    if hasattr(msg_obj, "edit_message_text"):
        await msg_obj.edit_message_text(text, reply_markup=kb)
    else:
        await msg_obj.reply_text(text, reply_markup=kb)
    return CHOOSE_KUCHISU


# ============================================================
# 口数
# ============================================================

async def handle_kuchisu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "kuchisu_manual":
        await q.edit_message_text("口数を手入力してください（整数）。")
        return INPUT_KUCHISU_MANUAL

    _, value = q.data.split(":", 1)
    ctx.user_data["kuchisu"] = int(value)
    return await _show_confirm(q, ctx)


async def handle_kuchisu_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    try:
        value = int(update.message.text.strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("正の整数で入力してください。")
        return INPUT_KUCHISU_MANUAL

    ctx.user_data["kuchisu"] = value
    return await _show_confirm(update.message, ctx)


# ============================================================
# 確認 → 完了
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
            InlineKeyboardButton("❌ キャンセル", callback_data="save_cancel"),
        ]
    ])
    if hasattr(msg_obj, "edit_message_text"):
        await msg_obj.edit_message_text(summary, reply_markup=kb)
    else:
        await msg_obj.reply_text(summary, reply_markup=kb)
    return CONFIRM_FLOWER


async def handle_confirm_flower(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "save_cancel":
        await q.edit_message_text("キャンセルしました。\n\n/start で最初からやり直してください。")
        ctx.user_data.clear()
        return ConversationHandler.END

    # 保存処理
    await q.edit_message_text("保存中…")
    d = ctx.user_data
    try:
        folder_id = gs.get_or_create_box_folder(d["box_number"])

        # 既存の花枚数を数えてファイル名に反映
        flower_count = d.get("flower_count_in_box", 0) + 1
        d["flower_count_in_box"] = flower_count

        zentai_name = f"flower{flower_count}_zentai.jpg"
        up_name = f"flower{flower_count}_up.jpg"

        zentai_url = gs.upload_photo(folder_id, zentai_name, d["photo_zentai"])
        up_url = gs.upload_photo(folder_id, up_name, d["photo_up"])

        gs.append_row({
            "box_number": d["box_number"],
            "hinshu": d["hinshu"],
            "size": d["size"],
            "nedan": d["nedan"],
            "irisu": d["irisu"],
            "kibou_tanka": d["kibou_tanka"],
            "kuchisu": d["kuchisu"],
            "zentai_url": zentai_url,
            "up_url": up_url,
        })
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
        f"✅ 保存しました（箱 {d['box_number']} / 花 {flower_count}枚目）",
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
        ctx.user_data.clear()
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
            WAIT_FLOWER_2: [MessageHandler(filters.PHOTO, handle_flower_2)],

            CHOOSE_HINSHU: [CallbackQueryHandler(handle_hinshu, pattern="^hinshu:")],

            CHOOSE_SIZE: [CallbackQueryHandler(handle_size, pattern="^(size:|size_manual$)")],
            INPUT_SIZE_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_size_manual)],

            CHOOSE_NEDAN: [CallbackQueryHandler(handle_nedan, pattern="^(nedan:|nedan_manual$)")],
            INPUT_NEDAN_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_nedan_manual)],

            CHOOSE_IRISU: [CallbackQueryHandler(handle_irisu, pattern="^(irisu:|irisu_manual$)")],
            INPUT_IRISU_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_irisu_manual)],

            CHOOSE_KUCHISU: [CallbackQueryHandler(handle_kuchisu, pattern="^(kuchisu:|kuchisu_manual$)")],
            INPUT_KUCHISU_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_kuchisu_manual)],

            CONFIRM_FLOWER: [CallbackQueryHandler(handle_confirm_flower, pattern="^save_(ok|cancel)$")],
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
