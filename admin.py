import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler
)
import config
import database

logger = logging.getLogger(__name__)

# ========== حالات المحادثة الإدارية ==========
(
    ADMIN_MAIN,
    ADMIN_POINTS_MENU,
    ADMIN_USERS_MENU,
    ADMIN_PROMPTS_MENU,
    ADMIN_AWAITING_ADD_POINTS,
    ADMIN_AWAITING_REMOVE_POINTS,
    ADMIN_AWAITING_BAN,
    ADMIN_AWAITING_UNBAN,
    ADMIN_AWAITING_SYSTEM_PROMPT,
    ADMIN_AWAITING_AI_SYSTEM_PROMPT,
) = range(10)

def is_admin(user_id):
    return user_id == config.ADMIN_ID

# ============================================================
# دوال بناء لوحات المفاتيح (مبسطة)
# ============================================================

def get_admin_main_keyboard():
    """القائمة الرئيسية للإدارة (3 أزرار فقط)."""
    keyboard = [
        [InlineKeyboardButton("💰 النقاط", callback_data="admin_points_menu")],
        [InlineKeyboardButton("👥 الأعضاء", callback_data="admin_users_menu")],
        [InlineKeyboardButton("📝 System Prompts", callback_data="admin_prompts_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_points_keyboard():
    """قائمة إدارة النقاط."""
    keyboard = [
        [InlineKeyboardButton("شحن نقاط", callback_data="admin_add_points")],
        [InlineKeyboardButton("سحب نقاط", callback_data="admin_remove_points")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_to_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_users_keyboard():
    """قائمة إدارة الأعضاء."""
    keyboard = [
        [InlineKeyboardButton("حظر مستخدم", callback_data="admin_ban")],
        [InlineKeyboardButton("فك حظر", callback_data="admin_unban")],
        [InlineKeyboardButton("قائمة المحظورين", callback_data="admin_banned_list")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_to_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_prompts_keyboard():
    """قائمة إدارة System Prompts."""
    keyboard = [
        [InlineKeyboardButton("📤 رفع System Prompt", callback_data="admin_upload_system")],
        [InlineKeyboardButton("📤 رفع AI System Prompt", callback_data="admin_upload_ai")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_to_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_back_keyboard():
    """زر رجوع للواجهة الإدارية."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع للواجهة الإدارية", callback_data="admin_panel")]
    ])

def get_admin_back_to_main_keyboard():
    """زر رجوع للقائمة الرئيسية للإدارة."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_panel")]
    ])

# ============================================================
# دوال عرض لوحة التحكم
# ============================================================

async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة التحكم الإدارية (أمر /admin)."""
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("<blockquote>❌ عذراً، هذا الأمر مخصص للأدمن فقط.</blockquote>", parse_mode='HTML')
        return

    text = """
<blockquote><b>🗂️ لوحة التحكم الإدارية</b>

اختر إحدى المجموعات أدناه:

💰 <b>النقاط</b> – شحن أو سحب نقاط المستخدمين.
👥 <b>الأعضاء</b> – حظر، فك حظر، أو عرض المحظورين.
📝 <b>System Prompts</b> – تحديث برومبتات النظام عبر رفع ملف txt.</blockquote>
    """
    keyboard = get_admin_main_keyboard()
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة التحكم الإدارية (من استعلام callback)."""
    query = update.callback_query
    await query.answer()
    text = """
<blockquote><b>🗂️ لوحة التحكم الإدارية</b>

اختر إحدى المجموعات أدناه:

💰 <b>النقاط</b> – شحن أو سحب نقاط المستخدمين.
👥 <b>الأعضاء</b> – حظر، فك حظر، أو عرض المحظورين.
📝 <b>System Prompts</b> – تحديث برومبتات النظام عبر رفع ملف txt.</blockquote>
    """
    keyboard = get_admin_main_keyboard()
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
    return ADMIN_MAIN

# ============================================================
# قوائم الإدارة الفرعية
# ============================================================

async def admin_points_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة إدارة النقاط."""
    query = update.callback_query
    await query.answer()
    text = """
<blockquote><b>💰 إدارة النقاط</b>

اختر الإجراء المطلوب:</blockquote>
    """
    keyboard = get_admin_points_keyboard()
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
    return ADMIN_POINTS_MENU

async def admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة إدارة الأعضاء."""
    query = update.callback_query
    await query.answer()
    text = """
<blockquote><b>👥 إدارة الأعضاء</b>

اختر الإجراء المطلوب:</blockquote>
    """
    keyboard = get_admin_users_keyboard()
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
    return ADMIN_USERS_MENU

async def admin_prompts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة إدارة System Prompts."""
    query = update.callback_query
    await query.answer()
    text = """
<blockquote><b>📝 إدارة System Prompts</b>

يمكنك رفع ملف txt لتحديث برومبت النظام.

<b>ملاحظة:</b> سيتم استبدال البرومبت الحالي بالكامل.</blockquote>
    """
    keyboard = get_admin_prompts_keyboard()
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
    return ADMIN_PROMPTS_MENU

# ============================================================
# معالجات النقاط
# ============================================================

async def admin_add_points_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    await query.edit_message_text(
        "<blockquote>💰 أرسل معرف المستخدم وعدد النقاط المراد شحنها.\n"
        "مثال: <code>123456789 10</code>\n\n"
        "أو اضغط /cancel للإلغاء.</blockquote>",
        parse_mode='HTML',
        reply_markup=get_admin_back_to_main_keyboard()
    )
    return ADMIN_AWAITING_ADD_POINTS

async def admin_add_points_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    try:
        parts = update.message.text.strip().split()
        if len(parts) != 2:
            await update.message.reply_text("<blockquote>⚠️ الرجاء إدخال معرف المستخدم وعدد النقاط.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_ADD_POINTS
        user_id = int(parts[0])
        amount = int(parts[1])
        if amount <= 0:
            await update.message.reply_text("<blockquote>⚠️ يجب أن يكون عدد النقاط موجباً.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_ADD_POINTS
        user = database.get_user(user_id)
        if user is None:
            await update.message.reply_text(f"<blockquote>❌ المستخدم {user_id} غير موجود.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_ADD_POINTS
        database.add_points(user_id, amount)
        logger.info(f"Admin {update.effective_user.id} شحن {amount} نقطة للمستخدم {user_id}")
        await update.message.reply_text(
            f"<blockquote>✅ تم شحن <b>{amount}</b> نقطة للمستخدم <code>{user_id}</code>.\n"
            f"رصيده الحالي: <b>{user['points'] + amount}</b> نقطة.</blockquote>",
            parse_mode='HTML'
        )
        # العودة لقائمة النقاط
        text = """
<blockquote><b>💰 إدارة النقاط</b>

اختر الإجراء المطلوب:</blockquote>
        """
        keyboard = get_admin_points_keyboard()
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
        return ADMIN_POINTS_MENU
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال أرقام صحيحة.</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_ADD_POINTS
    except Exception as e:
        logger.error(f"خطأ في شحن النقاط: {e}")
        await update.message.reply_text(f"<blockquote>❌ حدث خطأ: {str(e)}</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_ADD_POINTS

async def admin_remove_points_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    await query.edit_message_text(
        "<blockquote>💰 أرسل معرف المستخدم وعدد النقاط المراد سحبها.\n"
        "مثال: <code>123456789 5</code>\n\n"
        "أو اضغط /cancel للإلغاء.</blockquote>",
        parse_mode='HTML',
        reply_markup=get_admin_back_to_main_keyboard()
    )
    return ADMIN_AWAITING_REMOVE_POINTS

async def admin_remove_points_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    try:
        parts = update.message.text.strip().split()
        if len(parts) != 2:
            await update.message.reply_text("<blockquote>⚠️ الرجاء إدخال معرف المستخدم وعدد النقاط.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_REMOVE_POINTS
        user_id = int(parts[0])
        amount = int(parts[1])
        if amount <= 0:
            await update.message.reply_text("<blockquote>⚠️ يجب أن يكون عدد النقاط موجباً.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_REMOVE_POINTS
        user = database.get_user(user_id)
        if user is None:
            await update.message.reply_text(f"<blockquote>❌ المستخدم {user_id} غير موجود.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_REMOVE_POINTS
        if user['points'] < amount:
            await update.message.reply_text(f"<blockquote>❌ رصيد المستخدم <b>{user['points']}</b> نقطة فقط، لا يكفي للسحب.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_REMOVE_POINTS
        database.add_points(user_id, -amount)
        logger.info(f"Admin {update.effective_user.id} سحب {amount} نقطة من المستخدم {user_id}")
        await update.message.reply_text(
            f"<blockquote>✅ تم سحب <b>{amount}</b> نقطة من المستخدم <code>{user_id}</code>.\n"
            f"رصيده الحالي: <b>{user['points'] - amount}</b> نقطة.</blockquote>",
            parse_mode='HTML'
        )
        text = """
<blockquote><b>💰 إدارة النقاط</b>

اختر الإجراء المطلوب:</blockquote>
        """
        keyboard = get_admin_points_keyboard()
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
        return ADMIN_POINTS_MENU
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال أرقام صحيحة.</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_REMOVE_POINTS
    except Exception as e:
        logger.error(f"خطأ في سحب النقاط: {e}")
        await update.message.reply_text(f"<blockquote>❌ حدث خطأ: {str(e)}</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_REMOVE_POINTS

# ============================================================
# معالجات الأعضاء
# ============================================================

async def admin_ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    await query.edit_message_text(
        "<blockquote>🚫 أرسل معرف المستخدم المراد حظره.\n"
        "مثال: <code>123456789</code>\n\n"
        "أو اضغط /cancel للإلغاء.</blockquote>",
        parse_mode='HTML',
        reply_markup=get_admin_back_to_main_keyboard()
    )
    return ADMIN_AWAITING_BAN

async def admin_ban_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    try:
        user_id = int(update.message.text.strip())
        if user_id == config.ADMIN_ID:
            await update.message.reply_text("<blockquote>⚠️ لا يمكن حظر الأدمن نفسه.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_BAN
        database.ban_user(user_id)
        logger.info(f"Admin {update.effective_user.id} حظر المستخدم {user_id}")
        await update.message.reply_text(f"<blockquote>✅ تم حظر المستخدم <code>{user_id}</code> بنجاح.</blockquote>", parse_mode='HTML')
        text = """
<blockquote><b>👥 إدارة الأعضاء</b>

اختر الإجراء المطلوب:</blockquote>
        """
        keyboard = get_admin_users_keyboard()
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
        return ADMIN_USERS_MENU
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال معرف مستخدم صحيح (أرقام فقط).</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_BAN
    except Exception as e:
        logger.error(f"خطأ في حظر المستخدم: {e}")
        await update.message.reply_text(f"<blockquote>❌ حدث خطأ: {str(e)}</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_BAN

async def admin_unban_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    await query.edit_message_text(
        "<blockquote>🔓 أرسل معرف المستخدم المراد فك حظره.\n"
        "مثال: <code>123456789</code>\n\n"
        "أو اضغط /cancel للإلغاء.</blockquote>",
        parse_mode='HTML',
        reply_markup=get_admin_back_to_main_keyboard()
    )
    return ADMIN_AWAITING_UNBAN

async def admin_unban_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    try:
        user_id = int(update.message.text.strip())
        if not database.is_banned(user_id):
            await update.message.reply_text(f"<blockquote>❌ المستخدم <code>{user_id}</code> ليس محظوراً.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_UNBAN
        database.unban_user(user_id)
        logger.info(f"Admin {update.effective_user.id} فك حظر المستخدم {user_id}")
        await update.message.reply_text(f"<blockquote>✅ تم فك الحظر عن المستخدم <code>{user_id}</code> بنجاح.</blockquote>", parse_mode='HTML')
        text = """
<blockquote><b>👥 إدارة الأعضاء</b>

اختر الإجراء المطلوب:</blockquote>
        """
        keyboard = get_admin_users_keyboard()
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
        return ADMIN_USERS_MENU
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال معرف مستخدم صحيح (أرقام فقط).</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_UNBAN
    except Exception as e:
        logger.error(f"خطأ في فك حظر المستخدم: {e}")
        await update.message.reply_text(f"<blockquote>❌ حدث خطأ: {str(e)}</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_UNBAN

async def admin_banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    banned = database.get_banned_users()
    if not banned:
        await query.edit_message_text("<blockquote>✅ لا يوجد مستخدمين محظورين حالياً.</blockquote>", parse_mode='HTML', reply_markup=get_admin_users_keyboard())
        return ADMIN_USERS_MENU
    text = "<blockquote><b>🚫 قائمة المحظورين</b>\n\n"
    for user_id, banned_at in banned:
        text += f"<code>{user_id}</code> – منذ {banned_at}\n"
    text += "</blockquote>"
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_admin_users_keyboard())
    return ADMIN_USERS_MENU

# ============================================================
# معالجات System Prompts
# ============================================================

async def admin_upload_system_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طلب رفع ملف System Prompt (للاستخراج)."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    await query.edit_message_text(
        "<blockquote>📤 أرسل ملف <code>.txt</code> يحتوي على <b>System Prompt</b> الجديد لاستخراج الصور.\n\n"
        f"البرومبت الحالي:\n<code>{config.SYSTEM_PROMPT[:200]}...</code>\n\n"
        "أو اضغط /cancel للإلغاء.</blockquote>",
        parse_mode='HTML',
        reply_markup=get_admin_back_to_main_keyboard()
    )
    return ADMIN_AWAITING_SYSTEM_PROMPT

async def admin_upload_ai_system_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طلب رفع ملف AI System Prompt (للتوسيع)."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    await query.edit_message_text(
        "<blockquote>📤 أرسل ملف <code>.txt</code> يحتوي على <b>AI System Prompt</b> الجديد لتوسيع البرومبتات.\n\n"
        f"البرومبت الحالي:\n<code>{config.AI_SYSTEM_PROMPT[:200]}...</code>\n\n"
        "أو اضغط /cancel للإلغاء.</blockquote>",
        parse_mode='HTML',
        reply_markup=get_admin_back_to_main_keyboard()
    )
    return ADMIN_AWAITING_AI_SYSTEM_PROMPT

async def handle_system_prompt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال ملف System Prompt وحفظه."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    
    if not update.message.document:
        await update.message.reply_text("<blockquote>⚠️ الرجاء إرسال ملف <code>.txt</code>.</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_SYSTEM_PROMPT
    
    document = update.message.document
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("<blockquote>⚠️ الرجاء إرسال ملف بامتداد <code>.txt</code> فقط.</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_SYSTEM_PROMPT
    
    try:
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        prompt_text = file_content.decode('utf-8').strip()
        
        if not prompt_text:
            await update.message.reply_text("<blockquote>⚠️ الملف فارغ. الرجاء إرسال ملف يحتوي على نص.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_SYSTEM_PROMPT
        
        # تحديث SYSTEM_PROMPT في config
        config.SYSTEM_PROMPT = prompt_text
        logger.info(f"Admin {update.effective_user.id} قام بتحديث SYSTEM_PROMPT")
        
        await update.message.reply_text(
            f"<blockquote>✅ تم تحديث <b>System Prompt</b> بنجاح!\n\n"
            f"البرومبت الجديد:\n<code>{prompt_text[:200]}...</code></blockquote>",
            parse_mode='HTML'
        )
        
        # العودة لقائمة System Prompts
        text = """
<blockquote><b>📝 إدارة System Prompts</b>

يمكنك رفع ملف txt لتحديث برومبت النظام.

<b>ملاحظة:</b> سيتم استبدال البرومبت الحالي بالكامل.</blockquote>
        """
        keyboard = get_admin_prompts_keyboard()
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
        return ADMIN_PROMPTS_MENU
        
    except UnicodeDecodeError:
        await update.message.reply_text("<blockquote>⚠️ الملف ليس بصيغة نصية صالحة. تأكد من أن الملف مشفر بـ UTF-8.</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_SYSTEM_PROMPT
    except Exception as e:
        logger.error(f"خطأ في رفع System Prompt: {e}")
        await update.message.reply_text(f"<blockquote>❌ حدث خطأ: {str(e)}</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_SYSTEM_PROMPT

async def handle_ai_system_prompt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال ملف AI System Prompt وحفظه."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    
    if not update.message.document:
        await update.message.reply_text("<blockquote>⚠️ الرجاء إرسال ملف <code>.txt</code>.</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_AI_SYSTEM_PROMPT
    
    document = update.message.document
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("<blockquote>⚠️ الرجاء إرسال ملف بامتداد <code>.txt</code> فقط.</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_AI_SYSTEM_PROMPT
    
    try:
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        prompt_text = file_content.decode('utf-8').strip()
        
        if not prompt_text:
            await update.message.reply_text("<blockquote>⚠️ الملف فارغ. الرجاء إرسال ملف يحتوي على نص.</blockquote>", parse_mode='HTML')
            return ADMIN_AWAITING_AI_SYSTEM_PROMPT
        
        # تحديث AI_SYSTEM_PROMPT في config
        config.AI_SYSTEM_PROMPT = prompt_text
        logger.info(f"Admin {update.effective_user.id} قام بتحديث AI_SYSTEM_PROMPT")
        
        await update.message.reply_text(
            f"<blockquote>✅ تم تحديث <b>AI System Prompt</b> بنجاح!\n\n"
            f"البرومبت الجديد:\n<code>{prompt_text[:200]}...</code></blockquote>",
            parse_mode='HTML'
        )
        
        # العودة لقائمة System Prompts
        text = """
<blockquote><b>📝 إدارة System Prompts</b>

يمكنك رفع ملف txt لتحديث برومبت النظام.

<b>ملاحظة:</b> سيتم استبدال البرومبت الحالي بالكامل.</blockquote>
        """
        keyboard = get_admin_prompts_keyboard()
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
        return ADMIN_PROMPTS_MENU
        
    except UnicodeDecodeError:
        await update.message.reply_text("<blockquote>⚠️ الملف ليس بصيغة نصية صالحة. تأكد من أن الملف مشفر بـ UTF-8.</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_AI_SYSTEM_PROMPT
    except Exception as e:
        logger.error(f"خطأ في رفع AI System Prompt: {e}")
        await update.message.reply_text(f"<blockquote>❌ حدث خطأ: {str(e)}</blockquote>", parse_mode='HTML')
        return ADMIN_AWAITING_AI_SYSTEM_PROMPT

# ============================================================
# دوال الرجوع
# ============================================================

async def admin_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """العودة للقائمة الرئيسية للإدارة."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return ConversationHandler.END
    
    text = """
<blockquote><b>🗂️ لوحة التحكم الإدارية</b>

اختر إحدى المجموعات أدناه:

💰 <b>النقاط</b> – شحن أو سحب نقاط المستخدمين.
👥 <b>الأعضاء</b> – حظر، فك حظر، أو عرض المحظورين.
📝 <b>System Prompts</b> – تحديث برومبتات النظام عبر رفع ملف txt.</blockquote>
    """
    keyboard = get_admin_main_keyboard()
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
    return ADMIN_MAIN

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء العملية والعودة للواجهة الإدارية."""
    if update.effective_user is None:
        return
    await update.message.reply_text("<blockquote>❌ تم إلغاء العملية.</blockquote>", parse_mode='HTML')
    text = """
<blockquote><b>🗂️ لوحة التحكم الإدارية</b>

اختر إحدى المجموعات أدناه:

💰 <b>النقاط</b> – شحن أو سحب نقاط المستخدمين.
👥 <b>الأعضاء</b> – حظر، فك حظر، أو عرض المحظورين.
📝 <b>System Prompts</b> – تحديث برومبتات النظام عبر رفع ملف txt.</blockquote>
    """
    keyboard = get_admin_main_keyboard()
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
    return ConversationHandler.END

# ============================================================
# أوامر إدارية نصية (احتياط)
# ============================================================

async def add_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("<blockquote>⚠️ الاستخدام: /add_points <user_id> <amount></blockquote>", parse_mode='HTML')
        return
    try:
        user_id = int(args[0])
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال أرقام صحيحة.</blockquote>", parse_mode='HTML')
        return
    if amount <= 0:
        await update.message.reply_text("<blockquote>⚠️ يجب أن يكون المبلغ موجباً.</blockquote>", parse_mode='HTML')
        return
    user = database.get_user(user_id)
    if user is None:
        await update.message.reply_text(f"<blockquote>❌ المستخدم {user_id} غير موجود.</blockquote>", parse_mode='HTML')
        return
    database.add_points(user_id, amount)
    await update.message.reply_text(f"<blockquote>✅ تم شحن {amount} نقطة للمستخدم {user_id}. رصيده الحالي: {user['points'] + amount}</blockquote>", parse_mode='HTML')

async def remove_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("<blockquote>⚠️ الاستخدام: /remove_points <user_id> <amount></blockquote>", parse_mode='HTML')
        return
    try:
        user_id = int(args[0])
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال أرقام صحيحة.</blockquote>", parse_mode='HTML')
        return
    if amount <= 0:
        await update.message.reply_text("<blockquote>⚠️ يجب أن يكون المبلغ موجباً.</blockquote>", parse_mode='HTML')
        return
    user = database.get_user(user_id)
    if user is None:
        await update.message.reply_text(f"<blockquote>❌ المستخدم {user_id} غير موجود.</blockquote>", parse_mode='HTML')
        return
    if user['points'] < amount:
        await update.message.reply_text(f"<blockquote>❌ رصيد المستخدم {user['points']} نقطة فقط، لا يكفي للسحب.</blockquote>", parse_mode='HTML')
        return
    database.add_points(user_id, -amount)
    await update.message.reply_text(f"<blockquote>✅ تم سحب {amount} نقطة من المستخدم {user_id}. رصيده الحالي: {user['points'] - amount}</blockquote>", parse_mode='HTML')

async def create_gift_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("<blockquote>⚠️ الاستخدام: /create_gift <points> <max_uses></blockquote>", parse_mode='HTML')
        return
    try:
        points = int(args[0])
        max_uses = int(args[1])
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال أرقام صحيحة.</blockquote>", parse_mode='HTML')
        return
    if points <= 0 or max_uses <= 0:
        await update.message.reply_text("<blockquote>⚠️ يجب أن تكون الأرقام موجبة.</blockquote>", parse_mode='HTML')
        return
    code = database.create_gift_link(points, max_uses)
    link = f"https://t.me/{config.BOT_USERNAME}?start=gift_{code}"
    text = config.GIFT_CREATED_TEXT.format(points=points, max_uses=max_uses, link=link, code=code)
    await update.message.reply_text(text, parse_mode='HTML')

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("<blockquote>⚠️ الاستخدام: /ban <user_id></blockquote>", parse_mode='HTML')
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال رقم صحيح.</blockquote>", parse_mode='HTML')
        return
    if user_id == config.ADMIN_ID:
        await update.message.reply_text("<blockquote>⚠️ لا يمكن حظر الأدمن نفسه.</blockquote>", parse_mode='HTML')
        return
    database.ban_user(user_id)
    await update.message.reply_text(f"<blockquote>✅ تم حظر المستخدم {user_id}.</blockquote>", parse_mode='HTML')

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("<blockquote>⚠️ الاستخدام: /unban <user_id></blockquote>", parse_mode='HTML')
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("<blockquote>⚠️ يرجى إدخال رقم صحيح.</blockquote>", parse_mode='HTML')
        return
    if not database.is_banned(user_id):
        await update.message.reply_text(f"<blockquote>❌ المستخدم {user_id} ليس محظوراً.</blockquote>", parse_mode='HTML')
        return
    database.unban_user(user_id)
    await update.message.reply_text(f"<blockquote>✅ تم فك الحظر عن المستخدم {user_id}.</blockquote>", parse_mode='HTML')

async def banned_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or not is_admin(update.effective_user.id):
        await update.message.reply_text("<blockquote>❌ غير مصرح.</blockquote>", parse_mode='HTML')
        return
    banned = database.get_banned_users()
    if not banned:
        await update.message.reply_text("<blockquote>✅ لا يوجد مستخدمين محظورين حالياً.</blockquote>", parse_mode='HTML')
        return
    text = "<blockquote><b>🚫 قائمة المحظورين</b>\n\n"
    for user_id, banned_at in banned:
        text += f"<code>{user_id}</code> – منذ {banned_at}\n"
    text += "</blockquote>"
    await update.message.reply_text(text, parse_mode='HTML')

# ============================================================
# إنشاء معالج المحادثة الإدارية
# ============================================================

def get_admin_conversation_handler():
    """إنشاء وإرجاع معالج المحادثة الإدارية المُبسّط."""
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("admin", admin_panel_command),
            CallbackQueryHandler(show_admin_panel, pattern="^admin_panel$"),
            CallbackQueryHandler(admin_points_menu, pattern="^admin_points_menu$"),
            CallbackQueryHandler(admin_users_menu, pattern="^admin_users_menu$"),
            CallbackQueryHandler(admin_prompts_menu, pattern="^admin_prompts_menu$"),
            CallbackQueryHandler(admin_add_points_start, pattern="^admin_add_points$"),
            CallbackQueryHandler(admin_remove_points_start, pattern="^admin_remove_points$"),
            CallbackQueryHandler(admin_ban_start, pattern="^admin_ban$"),
            CallbackQueryHandler(admin_unban_start, pattern="^admin_unban$"),
            CallbackQueryHandler(admin_banned_list, pattern="^admin_banned_list$"),
            CallbackQueryHandler(admin_upload_system_prompt, pattern="^admin_upload_system$"),
            CallbackQueryHandler(admin_upload_ai_system_prompt, pattern="^admin_upload_ai$"),
            CallbackQueryHandler(admin_back_to_main, pattern="^admin_back_to_main$"),
        ],
        states={
            ADMIN_MAIN: [
                CallbackQueryHandler(admin_points_menu, pattern="^admin_points_menu$"),
                CallbackQueryHandler(admin_users_menu, pattern="^admin_users_menu$"),
                CallbackQueryHandler(admin_prompts_menu, pattern="^admin_prompts_menu$"),
                CallbackQueryHandler(admin_back_to_main, pattern="^admin_back_to_main$"),
                CallbackQueryHandler(show_admin_panel, pattern="^admin_panel$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_POINTS_MENU: [
                CallbackQueryHandler(admin_add_points_start, pattern="^admin_add_points$"),
                CallbackQueryHandler(admin_remove_points_start, pattern="^admin_remove_points$"),
                CallbackQueryHandler(admin_back_to_main, pattern="^admin_back_to_main$"),
                CallbackQueryHandler(show_admin_panel, pattern="^admin_panel$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_USERS_MENU: [
                CallbackQueryHandler(admin_ban_start, pattern="^admin_ban$"),
                CallbackQueryHandler(admin_unban_start, pattern="^admin_unban$"),
                CallbackQueryHandler(admin_banned_list, pattern="^admin_banned_list$"),
                CallbackQueryHandler(admin_back_to_main, pattern="^admin_back_to_main$"),
                CallbackQueryHandler(show_admin_panel, pattern="^admin_panel$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_PROMPTS_MENU: [
                CallbackQueryHandler(admin_upload_system_prompt, pattern="^admin_upload_system$"),
                CallbackQueryHandler(admin_upload_ai_system_prompt, pattern="^admin_upload_ai$"),
                CallbackQueryHandler(admin_back_to_main, pattern="^admin_back_to_main$"),
                CallbackQueryHandler(show_admin_panel, pattern="^admin_panel$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_AWAITING_ADD_POINTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_points_input),
                CallbackQueryHandler(admin_points_menu, pattern="^admin_points_menu$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_AWAITING_REMOVE_POINTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_remove_points_input),
                CallbackQueryHandler(admin_points_menu, pattern="^admin_points_menu$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_AWAITING_BAN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_input),
                CallbackQueryHandler(admin_users_menu, pattern="^admin_users_menu$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_AWAITING_UNBAN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_unban_input),
                CallbackQueryHandler(admin_users_menu, pattern="^admin_users_menu$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_AWAITING_SYSTEM_PROMPT: [
                MessageHandler(filters.Document.ALL, handle_system_prompt_file),
                CallbackQueryHandler(admin_prompts_menu, pattern="^admin_prompts_menu$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
            ADMIN_AWAITING_AI_SYSTEM_PROMPT: [
                MessageHandler(filters.Document.ALL, handle_ai_system_prompt_file),
                CallbackQueryHandler(admin_prompts_menu, pattern="^admin_prompts_menu$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel),
            CallbackQueryHandler(show_admin_panel, pattern="^admin_panel$"),
            CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
        ],
        per_message=False,
        per_chat=True,
        allow_reentry=True,
        name="admin_conversation",
    )
    return conv_handler
