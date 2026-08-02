import logging
import sqlite3
import time
import asyncio
import os
import aiohttp
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, BadRequest, RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
import config
import database
import grok_api
import keyboards
import admin

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_rate_limit_cache = {}
RATE_LIMIT_WINDOW = 10
RATE_LIMIT_MAX = 5

def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    if user_id not in _rate_limit_cache:
        _rate_limit_cache[user_id] = []
    _rate_limit_cache[user_id] = [t for t in _rate_limit_cache[user_id] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit_cache[user_id]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit_cache[user_id].append(now)
    return True

analysis_queue = asyncio.Queue()
queue_worker_task = None
MAX_RETRIES = 3
MAX_QUEUE_SIZE = 100
pending_tasks = []

# ============================================================
# دوال مساعدة
# ============================================================

async def send_long_message(chat_id, text, context, parse_mode=None):
    """إرسال رسالة طويلة بتقسيمها إلى أجزاء لا تتجاوز 4096 حرفاً."""
    max_length = 4096
    if not text:
        return
    if len(text) <= max_length:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        return
    
    parts = []
    current_part = ""
    for line in text.split('\n'):
        if len(current_part) + len(line) + 1 <= max_length:
            current_part += line + '\n'
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = line + '\n'
    if current_part:
        parts.append(current_part.strip())
    
    for i, part in enumerate(parts):
        if len(parts) > 1:
            header = f"[الجزء {i+1}/{len(parts)}]\n"
            part = header + part
        await context.bot.send_message(chat_id=chat_id, text=part, parse_mode=parse_mode)

async def safe_answer_query(query, text=None, show_alert=False):
    """الإجابة على استعلام callback بأمان مع تجاهل أخطاء انتهاء الصلاحية."""
    try:
        await query.answer(text=text, show_alert=show_alert)
    except Exception as e:
        if "Query is too old" in str(e) or "query id is invalid" in str(e):
            logger.debug(f"تجاهل استعلام منتهي الصلاحية: {e}")
        else:
            logger.error(f"خطأ في answer_query: {e}")

# ============================================================
# دوال الطابور والمعالجة
# ============================================================

async def queue_worker():
    logger.info("بدء تشغيل معالج الطابور الخلفي...")
    while True:
        try:
            task = await analysis_queue.get()
            logger.info(f"معالجة طلب من المستخدم {task['user_id']} (الطلبات المتبقية: {analysis_queue.qsize()})")
            await process_analysis_task(task)
            analysis_queue.task_done()
            logger.info(f"تمت معالجة طلب المستخدم {task['user_id']}")
        except asyncio.CancelledError:
            logger.info("تم إيقاف معالج الطابور. حفظ المهام المتبقية...")
            while not analysis_queue.empty():
                try:
                    pending_tasks.append(await analysis_queue.get())
                except:
                    pass
            break
        except Exception as e:
            logger.error(f"خطأ في معالج الطابور: {e}", exc_info=True)
            await asyncio.sleep(1)

async def send_to_channel(photo_bytes, prompt_text, bot, retries=3):
    chat_id = config.PROMO_CHANNEL_ID_NUMERIC or config.PROMO_CHANNEL_ID
    if not chat_id:
        logger.error("لم يتم تحديد معرف القناة في الإعدادات.")
        return False
    if not photo_bytes:
        logger.error("photo_bytes فارغ أو غير صالح.")
        return False
    if isinstance(photo_bytes, bytearray):
        photo_bytes = bytes(photo_bytes)
    for attempt in range(retries):
        try:
            logger.info(f"محاولة إرسال إلى القناة {chat_id} (المحاولة {attempt+1}/{retries})")
            photo_msg = await bot.send_photo(
                chat_id=chat_id,
                photo=photo_bytes,
                caption="by @UFOQ_BOT"
            )
            logger.info(f"تم إرسال الصورة بنجاح (معرف الرسالة: {photo_msg.message_id})")
            await bot.send_message(
                chat_id=chat_id,
                text=prompt_text,
                reply_to_message_id=photo_msg.message_id
            )
            logger.info("تم إرسال البرومبت بنجاح كرد على الصورة.")
            return True
        except Forbidden as e:
            logger.error(f"خطأ صلاحيات (Forbidden) في المحاولة {attempt+1}: البوت ليس لديه صلاحية الإرسال في القناة أو تم حظره. التفاصيل: {e}")
            break
        except BadRequest as e:
            if "chat not found" in str(e).lower() or "channel not found" in str(e).lower():
                logger.error(f"خطأ (BadRequest) في المحاولة {attempt+1}: القناة غير موجودة أو المعرف غير صحيح. التفاصيل: {e}")
                break
            else:
                logger.error(f"خطأ BadRequest غير متوقع في المحاولة {attempt+1}: {e}")
                if attempt < retries - 1:
                    delay = 2 ** (attempt + 1)
                    logger.info(f"إعادة المحاولة بعد {delay} ثانية...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("فشلت جميع محاولات الإرسال إلى القناة.")
        except RetryAfter as e:
            wait_time = e.retry_after
            logger.warning(f"تم تجاوز حد السرعة (RetryAfter)، الانتظار {wait_time} ثانية قبل المحاولة {attempt+2}.")
            await asyncio.sleep(wait_time)
        except Exception as e:
            logger.error(f"خطأ غير متوقع في المحاولة {attempt+1}: {e}", exc_info=True)
            if attempt < retries - 1:
                delay = 2 ** (attempt + 1)
                logger.info(f"إعادة المحاولة بعد {delay} ثانية...")
                await asyncio.sleep(delay)
            else:
                logger.error("فشلت جميع محاولات الإرسال إلى القناة.")
    return False

async def send_sticker_without_text(context, sticker_id, chat_id):
    try:
        await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_id)
        logger.info(f"تم إرسال ملصق المعالجة للمستخدم {chat_id}")
        return True
    except Exception as e:
        logger.error(f"فشل إرسال الملصق: {e}")
        return False

async def send_prompt_to_site(prompt_text, image_url, user_id, title=None):
    api_url = os.getenv('SITE_API_URL', 'https://ufoq.vercel.app/api/prompt/create')
    api_key = os.getenv('SITE_API_KEY')
    if not api_key:
        logger.warning("SITE_API_KEY غير محددة، تخطي المزامنة مع الموقع.")
        return
    
    if not title:
        title = prompt_text[:100]
    
    payload = {
        'prompt_text': prompt_text,
        'title': title,
        'image_url': image_url or '',
        'publisher': f'UFOQ Bot (User {user_id})',
        'publisher_link': f'https://t.me/user/{user_id}',
        'category': 'bot',
        'keywords': 'مستخرج من البوت'
    }
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    logger.info(f"تمت مزامنة البرومبت مع الموقع بنجاح للمستخدم {user_id}، المعرف: {result.get('id')}")
                else:
                    text = await resp.text()
                    logger.warning(f"فشلت مزامنة البرومبت مع الموقع: HTTP {resp.status} - {text[:200]}")
    except asyncio.TimeoutError:
        logger.error(f"انتهت مهلة الاتصال بموقع UFOQ للمستخدم {user_id}")
    except Exception as e:
        logger.error(f"خطأ غير متوقع أثناء إرسال البرومبت للموقع: {e}")

# ============================================================
# معالجة استخراج البرومبت باستخدام Grok API
# ============================================================
async def process_analysis_task(task):
    user_id = task['user_id']
    image_bytes = task['image_bytes']
    context = task['context']
    queue_message_id = task.get('queue_message_id')
    original_photo = task.get('photo')
    image_url = task.get('image_url', '')
    
    await send_sticker_without_text(context, config.PROCESSING_STICKER_ID, user_id)
    
    for attempt in range(MAX_RETRIES):
        try:
            if queue_message_id:
                try:
                    status_text = "جاري تحليل الصورة باستخدام Grok..."
                    if attempt > 0:
                        status_text = f"جاري إعادة المحاولة ({attempt}/{MAX_RETRIES})..."
                    await context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=queue_message_id,
                        text=status_text
                    )
                except:
                    pass
            
            # الحصول على جلسة Grok
            try:
                token, chat_uuid = grok_api.get_grok_session()
            except Exception as e:
                logger.warning(f"فشل الحصول على جلسة Grok، إعادة تهيئة: {e}")
                token, chat_uuid = grok_api.force_refresh_session()
            
            # رفع الصورة مع إعادة المحاولة
            upload_attempts = 3
            for upload_attempt in range(upload_attempts):
                try:
                    image_url = grok_api.upload_image_to_grok(chat_uuid, image_bytes, token)
                    break
                except Exception as e:
                    logger.warning(f"فشل رفع الصورة، المحاولة {upload_attempt+1}/{upload_attempts}: {e}")
                    if upload_attempt == upload_attempts - 1:
                        raise
                    # إعادة تهيئة الجلسة
                    token, chat_uuid = grok_api.force_refresh_session()
                    await asyncio.sleep(2)
            
            prompt_text = config.SYSTEM_PROMPT
            objects = [
                {"object_type": "text", "object_url": None, "object_text": prompt_text, "model_type": "grok-4.5"},
                {"object_type": "image", "object_url": image_url, "object_text": "صورة", "model_type": "grok-4.5"}
            ]
            msg_id = grok_api.send_message_to_grok(chat_uuid, objects, token)
            reply_text = grok_api.wait_for_reply(chat_uuid, msg_id, token, timeout=180)
            
            if queue_message_id:
                try:
                    await context.bot.delete_message(chat_id=user_id, message_id=queue_message_id)
                except:
                    pass
            
            # ===== إرسال النتيجة بدون parse_mode =====
            await send_long_message(user_id, reply_text, context, parse_mode=None)
            await context.bot.send_message(
                chat_id=user_id,
                text="تم الانتهاء. يمكنك إرسال /start للعودة للقائمة الرئيسية."
            )
            
            await send_prompt_to_site(
                prompt_text=reply_text,
                image_url=image_url,
                user_id=user_id,
                title=reply_text[:100]
            )
            
            channel_success = False
            if original_photo:
                channel_success = await send_to_channel(original_photo, reply_text, context.bot)
                if channel_success:
                    logger.info(f"تم نشر الصورة والبرومبت في القناة بنجاح للمستخدم {user_id}")
                else:
                    logger.warning(f"فشل نشر الصورة والبرومبت في القناة للمستخدم {user_id}")
                    try:
                        await context.bot.send_message(
                            chat_id=config.ADMIN_ID,
                            text=f"فشل نشر محتوى المستخدم {user_id} في القناة. راجع السجلات للتفاصيل."
                        )
                    except:
                        pass
            else:
                logger.warning(f"لا توجد صورة للإرسال إلى القناة للمستخدم {user_id}")
            
            logger.info(f"تم إرسال النتيجة للمستخدم {user_id}")
            return
            
        except Exception as e:
            logger.error(f"محاولة {attempt+1}/{MAX_RETRIES} فشلت للمستخدم {user_id}: {e}")
            if "401" in str(e) or "Unauthorized" in str(e) or "فشل" in str(e):
                logger.info("محاولة إعادة تهيئة جلسة Grok...")
                try:
                    grok_api.force_refresh_session()
                except Exception as refresh_err:
                    logger.error(f"فشل إعادة تهيئة الجلسة: {refresh_err}")
            if attempt == MAX_RETRIES - 1:
                if queue_message_id:
                    try:
                        await context.bot.delete_message(chat_id=user_id, message_id=queue_message_id)
                    except:
                        pass
                await context.bot.send_message(
                    chat_id=user_id,
                    text="عذراً، حدث خطأ أثناء تحليل الصورة. يرجى المحاولة مرة أخرى لاحقاً."
                )
            else:
                await asyncio.sleep(5 * (attempt + 1))

# ============================================================
# معالجة "انشاء برومبت" باستخدام Grok API مع دعم روابط Pinterest
# ============================================================
async def handle_ai_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    
    if not context.user_data.get("awaiting_ai_prompt"):
        await update.message.reply_text("الرجاء الضغط على زر 'انشاء برومبت' أولاً.")
        return
    
    if not update.message.text:
        await update.message.reply_text("الرجاء إرسال نص صالح.")
        return
    
    text = update.message.text.strip()
    image_urls = []
    prompt_text = text
    
    if '||' in text:
        parts = text.split('||', 1)
        prompt_text = parts[0].strip()
        if parts[1].strip():
            raw_urls = [x.strip() for x in parts[1].split(',') if x.strip()]
            for url in raw_urls:
                if url.startswith(('http://', 'https://')):
                    image_urls.append(url)
    
    if not prompt_text:
        await update.message.reply_text("الرجاء إدخال نص البرومبت الأساسي.")
        return
    
    user_data = database.get_user(user_id)
    if user_data is None or user_data["points"] < 1:
        await update.message.reply_text("لا تملك نقاطاً كافية.")
        context.user_data["awaiting_ai_prompt"] = False
        return
    
    database.add_points(user_id, -1)
    logger.info(f"تم خصم نقطة من المستخدم {user_id} لعملية التوسيع")
    
    sticker_sent = await send_sticker_without_text(context, config.PROCESSING_STICKER_ID, user_id)
    
    status_msg = await update.message.reply_text("جاري معالجة طلبك باستخدام Grok...")
    
    try:
        token, chat_uuid = grok_api.get_grok_session()
        
        objects = []
        
        if config.AI_SYSTEM_PROMPT:
            objects.append({
                "object_type": "text",
                "object_url": None,
                "object_text": config.AI_SYSTEM_PROMPT,
                "model_type": "grok-4.5"
            })
        
        objects.append({
            "object_type": "text",
            "object_url": None,
            "object_text": prompt_text,
            "model_type": "grok-4.5"
        })
        
        uploaded_urls = []
        for url in image_urls:
            try:
                logger.info(f"محاولة تحميل الصورة من الرابط: {url}")
                image_bytes = await asyncio.to_thread(grok_api.download_image_from_url, url, config.MAX_IMAGE_SIZE)
                if image_bytes:
                    # رفع الصورة مع إعادة المحاولة
                    upload_attempts = 3
                    img_url = None
                    for upload_attempt in range(upload_attempts):
                        try:
                            img_url = grok_api.upload_image_to_grok(chat_uuid, image_bytes, token)
                            break
                        except Exception as e:
                            logger.warning(f"فشل رفع الصورة، المحاولة {upload_attempt+1}/{upload_attempts}: {e}")
                            if upload_attempt == upload_attempts - 1:
                                raise
                            token, chat_uuid = grok_api.force_refresh_session()
                            await asyncio.sleep(2)
                    
                    if img_url:
                        objects.append({
                            "object_type": "image",
                            "object_url": img_url,
                            "object_text": "صورة",
                            "model_type": "grok-4.5"
                        })
                        uploaded_urls.append(img_url)
                        logger.info(f"تم رفع الصورة بنجاح: {img_url}")
                else:
                    logger.warning(f"فشل تحميل الصورة من الرابط: {url}")
            except Exception as e:
                logger.warning(f"فشل معالجة الصورة من الرابط {url}: {e}")
        
        if not objects:
            raise Exception("لا يوجد محتوى صالح للإرسال (نص أو صورة)")
        
        msg_id = grok_api.send_message_to_grok(chat_uuid, objects, token)
        reply = grok_api.wait_for_reply(chat_uuid, msg_id, token, timeout=180)
        
        if sticker_sent:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=status_msg.message_id - 1)
            except:
                pass
        
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=status_msg.message_id)
        except:
            pass
        
        # ===== إرسال النتيجة بدون parse_mode =====
        await send_long_message(user_id, reply, context, parse_mode=None)
        await context.bot.send_message(
            chat_id=user_id,
            text="تم الانتهاء. يمكنك إرسال /start للعودة للقائمة الرئيسية."
        )
        
        await send_prompt_to_site(
            prompt_text=reply,
            image_url=uploaded_urls[0] if uploaded_urls else '',
            user_id=user_id,
            title=reply[:100]
        )
        
    except Exception as e:
        logger.error(f"خطأ في معالجة التوسيع للمستخدم {user_id}: {e}")
        
        try:
            if sticker_sent:
                await context.bot.delete_message(chat_id=user_id, message_id=status_msg.message_id - 1)
        except:
            pass
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=status_msg.message_id)
        except:
            pass
        
        await update.message.reply_text(
            f"{config.AI_PROCESSING_ERROR}\nتفاصيل: {str(e)[:100]}"
        )
    
    context.user_data["awaiting_ai_prompt"] = False

# ============================================================
# دوال البوت الأساسية
# ============================================================

async def create_prompt_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    user_id = update.effective_user.id
    
    if not check_rate_limit(user_id):
        await safe_answer_query(query, "وصلت للحد الأقصى من الطلبات.", show_alert=True)
        return
    if database.is_banned(user_id):
        await query.edit_message_caption("لا يمكنك استخدام هذه الميزة.")
        return
    if not await check_subscription(user_id, context):
        caption = config.SUB_REQUIRED_TEXT
        keyboard = keyboards.subscription_check_keyboard()
        await safe_edit_caption(query, caption, keyboard)
        return
    
    user_data = database.get_user(user_id)
    if user_data is None or user_data["points"] < 1:
        invite_link = database.get_invite_link(user_id)
        caption = config.NO_POINTS_TEXT.format(invite_link=invite_link)
        back_keyboard = keyboards.back_keyboard()
        await safe_edit_caption(query, caption, back_keyboard)
        return
    
    context.user_data["awaiting_ai_prompt"] = True
    cancel_keyboard = keyboards.cancel_keyboard()
    await safe_edit_caption(query, config.REQUEST_PROMPT_TEXT, cancel_keyboard)

_subscription_cache = {}
CACHE_TTL = 30

async def check_subscription(chat_id, context):
    now = time.time()
    if chat_id in _subscription_cache:
        cached = _subscription_cache[chat_id]
        if now - cached["timestamp"] < CACHE_TTL:
            return cached["status"]
    try:
        member = await context.bot.get_chat_member(config.CHANNEL_ID, chat_id)
        status = member.status in ["member", "administrator", "creator"]
    except:
        status = False
    _subscription_cache[chat_id] = {"status": status, "timestamp": now}
    return status

async def safe_edit_caption(query, caption, reply_markup=None):
    try:
        if query.message.caption is None:
            await query.message.reply_photo(
                photo=config.MAIN_IMAGE_URL,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            try:
                await query.message.delete()
            except:
                pass
            return
        current_caption = query.message.caption or ""
        current_markup = query.message.reply_markup
        if current_caption == caption and current_markup == reply_markup:
            return
        await query.edit_message_caption(caption=caption, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        if "Message is not modified" in str(e):
            pass
        elif "There is no caption" in str(e):
            try:
                await query.message.reply_photo(
                    photo=config.MAIN_IMAGE_URL,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                await query.message.delete()
            except:
                pass
        else:
            raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    args = context.args
    if not check_rate_limit(user_id):
        await update.message.reply_text("وصلت للحد الأقصى من الطلبات. يرجى الانتظار قليلاً.")
        return
    if database.is_banned(user_id):
        await update.message.reply_text("لا يمكنك استخدام هذا البوت حالياً.")
        return
    if args:
        param = args[0]
        if param.startswith("ref_"):
            invited_by = param.split("_")[1]
            if invited_by.isdigit():
                invited_by = int(invited_by)
                user_data = database.get_user(user_id)
                if user_data is None:
                    database.add_user(user_id, invited_by)
                    await context.bot.send_message(
                        chat_id=invited_by,
                        text="قام صديقك بالاشتراك عبر رابطك! حصلت على نقطة إضافية."
                    )
                    await update.message.reply_text("تم تفعيل حسابك! حصلت على نقطة مجانية، وصديقك حصل على نقطة أيضاً.")
                else:
                    await update.message.reply_text("هذا الرابط خاص بالدعوة، لكنك مسجل بالفعل.")
            else:
                await update.message.reply_text("رابط دعوة غير صالح.")
            return
        elif param.startswith("gift_"):
            code = param.split("_")[1]
            gift = database.get_gift_info(code)
            if not gift:
                await update.message.reply_text("رابط هدية غير صالح.")
                return
            if gift["used_count"] >= gift["max_uses"]:
                await update.message.reply_text(config.GIFT_ALREADY_USED)
                return
            result = database.use_gift(code)
            if result == "expired":
                await update.message.reply_text(config.GIFT_ALREADY_USED)
                return
            database.add_points(user_id, gift["points"])
            await update.message.reply_text(
                config.GIFT_SUCCESS_TEXT.format(points=gift["points"], code=code),
                parse_mode='HTML'
            )
            return
    if not await check_subscription(user_id, context):
        caption = config.SUB_REQUIRED_TEXT
        keyboard = keyboards.subscription_check_keyboard()
        await update.message.reply_photo(
            photo=config.SUBSCRIPTION_IMAGE_URL,
            caption=caption,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        return
    user_data = database.get_user(user_id)
    if user_data is None:
        database.add_user(user_id, None)
        await update.message.reply_text("مرحباً بك! حصلت على نقطة مجانية للبدء.")
    caption = config.WELCOME_TEXT
    keyboard = keyboards.main_menu_keyboard()
    await update.message.reply_photo(
        photo=config.MAIN_IMAGE_URL,
        caption=caption,
        reply_markup=keyboard,
        parse_mode='HTML'
    )

async def extract_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await safe_answer_query(query, "وصلت للحد الأقصى من الطلبات.", show_alert=True)
        return
    if database.is_banned(user_id):
        await query.edit_message_caption("لا يمكنك استخدام هذه الميزة.")
        return
    if not await check_subscription(user_id, context):
        caption = config.SUB_REQUIRED_TEXT
        keyboard = keyboards.subscription_check_keyboard()
        await safe_edit_caption(query, caption, keyboard)
        return
    user_data = database.get_user(user_id)
    if user_data is None or user_data["points"] < 1:
        invite_link = database.get_invite_link(user_id)
        caption = config.NO_POINTS_TEXT.format(invite_link=invite_link)
        back_keyboard = keyboards.back_keyboard()
        await safe_edit_caption(query, caption, back_keyboard)
        return
    context.user_data["awaiting_media"] = True
    cancel_keyboard = keyboards.cancel_keyboard()
    await safe_edit_caption(query, config.REQUEST_MEDIA_TEXT, cancel_keyboard)

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("دالة handle_image تم استدعاؤها")
    if update.effective_user is None:
        logger.warning("التحديث لا يحتوي على مستخدم، تم التجاهل تماماً.")
        return
    user_id = update.effective_user.id
    logger.info(f"المستخدم {user_id} أرسل صورة")
    if not check_rate_limit(user_id):
        await update.message.reply_text("وصلت للحد الأقصى من الطلبات. يرجى الانتظار قليلاً.")
        return
    if database.is_banned(user_id):
        await update.message.reply_text("لا يمكنك استخدام هذه الميزة.")
        return
    if not context.user_data.get("awaiting_media"):
        await update.message.reply_text("الرجاء الضغط على زر 'استخراج برومبت' أولاً.")
        return
    if not update.message.photo:
        await update.message.reply_text("يرجى إرسال صورة واحدة فقط.")
        return
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    if file.file_size > config.MAX_IMAGE_SIZE:
        await update.message.reply_text(f"حجم الصورة كبير جداً. الحد الأقصى هو {config.MAX_IMAGE_SIZE // (1024*1024)} ميجابايت.")
        context.user_data["awaiting_media"] = False
        return
    user_data = database.get_user(user_id)
    if user_data is None or user_data["points"] < 1:
        await update.message.reply_text("لا تملك نقاطاً كافية.")
        context.user_data["awaiting_media"] = False
        return
    database.add_points(user_id, -1)
    logger.info(f"تم خصم نقطة من المستخدم {user_id}")
    image_bytes = await file.download_as_bytearray()
    logger.info(f"تم تحميل الصورة، حجمها {len(image_bytes)} بايت")
    if analysis_queue.qsize() >= MAX_QUEUE_SIZE:
        await update.message.reply_text("الطابور ممتلئ حالياً، يرجى المحاولة لاحقاً.")
        context.user_data["awaiting_media"] = False
        return
    queue_msg = await update.message.reply_text(
        "تم استلام طلبك! تم إضافته إلى قائمة الانتظار.\n"
        f"موقعك في الطابور: {analysis_queue.qsize() + 1}\n"
        "سيتم إعلامك عند الانتهاء..."
    )
    task = {
        'user_id': user_id,
        'image_bytes': image_bytes,
        'context': context,
        'queue_message_id': queue_msg.message_id,
        'photo': image_bytes
    }
    await analysis_queue.put(task)
    logger.info(f"تم إضافة طلب المستخدم {user_id} إلى الطابور (الطلبات المتراكمة: {analysis_queue.qsize()})")
    context.user_data["awaiting_media"] = False

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    if not context.user_data.get("awaiting_media"):
        await update.message.reply_text("الرجاء الضغط على زر 'استخراج برومبت' أولاً.")
        return
    if not update.message.text:
        await update.message.reply_text("الرجاء إرسال رابط صحيح.")
        return
    url = update.message.text.strip()
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text(config.INVALID_URL_TEXT)
        return
    user_data = database.get_user(user_id)
    if user_data is None or user_data["points"] < 1:
        await update.message.reply_text("لا تملك نقاطاً كافية.")
        context.user_data["awaiting_media"] = False
        return
    try:
        image_bytes = await asyncio.to_thread(grok_api.download_image_from_url, url, config.MAX_IMAGE_SIZE)
    except ValueError as e:
        await update.message.reply_text(f"[!] {str(e)}")
        context.user_data["awaiting_media"] = False
        return
    except Exception as e:
        error_msg = str(e)
        if "Pinterest" in error_msg:
            user_error = "فشل تحميل الصورة من Pinterest. تأكد من صحة الرابط وأن الصورة عامة."
        elif "og:image" in error_msg or "img" in error_msg:
            user_error = "تعذر العثور على صورة في هذا الرابط. حاول استخدام رابط مباشر لصورة."
        elif "HTTP" in error_msg:
            user_error = "الموقع غير متاح حالياً. حاول مرة أخرى لاحقاً."
        elif "حجم" in error_msg:
            user_error = error_msg
        else:
            user_error = config.URL_DOWNLOAD_ERROR
        await update.message.reply_text(f"{user_error}\nتفاصيل: {error_msg[:100]}")
        context.user_data["awaiting_media"] = False
        return
    database.add_points(user_id, -1)
    if analysis_queue.qsize() >= MAX_QUEUE_SIZE:
        await update.message.reply_text("الطابور ممتلئ حالياً، يرجى المحاولة لاحقاً.")
        context.user_data["awaiting_media"] = False
        return
    queue_msg = await update.message.reply_text(
        "تم استلام طلبك! جاري تحميل الصورة...\n"
        f"موقعك في الطابور: {analysis_queue.qsize() + 1}"
    )
    task = {
        'user_id': user_id,
        'image_bytes': image_bytes,
        'context': context,
        'queue_message_id': queue_msg.message_id,
        'photo': image_bytes
    }
    await analysis_queue.put(task)
    context.user_data["awaiting_media"] = False

async def cancel_extract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    context.user_data["awaiting_media"] = False
    context.user_data["awaiting_ai_prompt"] = False
    caption = config.WELCOME_TEXT
    keyboard = keyboards.main_menu_keyboard()
    await safe_edit_caption(query, caption, keyboard)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    context.user_data["awaiting_media"] = False
    context.user_data["awaiting_ai_prompt"] = False
    await update.message.reply_text("تم إلغاء العملية.")
    caption = config.WELCOME_TEXT
    keyboard = keyboards.main_menu_keyboard()
    await update.message.reply_photo(
        photo=config.MAIN_IMAGE_URL,
        caption=caption,
        reply_markup=keyboard,
        parse_mode='HTML'
    )

async def promo_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await safe_answer_query(query, "وصلت للحد الأقصى من الطلبات.", show_alert=True)
        return
    if database.is_banned(user_id):
        await query.edit_message_caption("لا يمكنك استخدام هذه الميزة.")
        return
    if not await check_subscription(user_id, context):
        caption = config.SUB_REQUIRED_TEXT
        keyboard = keyboards.subscription_check_keyboard()
        await safe_edit_caption(query, caption, keyboard)
        return
    user_data = database.get_user(user_id)
    if user_data is None:
        await safe_edit_caption(query, "حدث خطأ في استرجاع بياناتك.", keyboards.back_keyboard())
        return
    invited_count = user_data["invite_count"]
    points = user_data["points"]
    if invited_count < 5:
        caption = config.PROMO_REQUIRED_TEXT.format(invited_count=invited_count, points=points)
        keyboard = keyboards.promo_required_keyboard()
        await safe_edit_caption(query, caption, keyboard)
        return
    caption = config.PROMO_SUCCESS_TEXT
    keyboard = keyboards.promo_success_keyboard()
    await safe_edit_caption(query, caption, keyboard)

async def other_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await safe_answer_query(update.callback_query, "وصلت للحد الأقصى من الطلبات.", show_alert=True)
        return
    query = update.callback_query
    await safe_answer_query(query)
    if database.is_banned(user_id):
        if query.message.caption is not None:
            await query.edit_message_caption("لا يمكنك استخدام هذه الميزة.")
        else:
            await query.message.reply_text("لا يمكنك استخدام هذه الميزة.")
        return
    if not await check_subscription(user_id, context):
        caption = config.SUB_REQUIRED_TEXT
        keyboard = keyboards.subscription_check_keyboard()
        await safe_edit_caption(query, caption, keyboard)
        return
    data = query.data
    if data == "points":
        user_data = database.get_user(user_id)
        if user_data:
            points = user_data["points"]
            invited_count = user_data["invite_count"]
            invite_link = database.get_invite_link(user_id)
            text = config.POINTS_INFO_TEXT.format(
                invite_link=invite_link,
                invited_count=invited_count,
                points=points
            )
            keyboard = keyboards.points_menu_keyboard()
            await safe_edit_caption(query, text, keyboard)
        else:
            await safe_edit_caption(query, "حدث خطأ في استرجاع بياناتك.", keyboards.points_menu_keyboard())
    elif data == "developer":
        text = config.DEVELOPER_TEXT
        keyboard = keyboards.developer_keyboard()
        await safe_edit_caption(query, text, keyboard)
    elif data == "back_to_main":
        context.user_data["awaiting_media"] = False
        context.user_data["awaiting_ai_prompt"] = False
        caption = config.WELCOME_TEXT
        keyboard = keyboards.main_menu_keyboard()
        await safe_edit_caption(query, caption, keyboard)
    elif data == "check_sub":
        if user_id in _subscription_cache:
            del _subscription_cache[user_id]
        if await check_subscription(user_id, context):
            caption = "تم التحقق من اشتراكك! يمكنك الآن استخدام البوت."
            keyboard = keyboards.main_menu_keyboard()
            await safe_edit_caption(query, caption, keyboard)
        else:
            caption = "لا يزال الاشتراك غير مفعّل. يرجى الاشتراك ثم الضغط على 'تحقق'."
            await safe_edit_caption(query, caption, keyboards.subscription_check_keyboard())

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"خطأ غير متوقع: {context.error}", exc_info=True)
    if update and update.effective_message and update.effective_user:
        try:
            await update.effective_message.reply_text("عذراً، حدث خطأ غير متوقع. تم إبلاغ المطور.")
        except Exception as e:
            logger.error(f"تعذر إرسال رسالة الخطأ للمستخدم: {e}")
    else:
        logger.warning("التحديث لا يحتوي على مستخدم أو رسالة، تم تجاهل إرسال رسالة الخطأ.")

async def delete_webhook_safe():
    try:
        app_temp = Application.builder().token(config.BOT_TOKEN).build()
        await app_temp.bot.delete_webhook()
        logger.info("تم حذف Webhook بنجاح")
        return True
    except Exception as e:
        logger.warning(f"فشل حذف Webhook: {e}")
        return False

def main():
    try:
        logger.info("محاولة حذف Webhook...")
        try:
            asyncio.run(delete_webhook_safe())
        except Exception as e:
            logger.warning(f"فشل حذف Webhook (قد لا يكون موجوداً): {e}")
        
        database.init_db()
        logger.info("تم تهيئة قاعدة البيانات")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        global queue_worker_task
        queue_worker_task = loop.create_task(queue_worker())
        logger.info("تم بدء معالج الطابور الخلفي")
        
        # ===== البروكسي =====
        if config.PROXY_ENABLED:
            proxy_display = f"{config.PROXY_TYPE}://{config.PROXY_HOST}:{config.PROXY_PORT}"
            if config.PROXY_USER and config.PROXY_PASS:
                proxy_display = f"{config.PROXY_TYPE}://{config.PROXY_USER}:***@{config.PROXY_HOST}:{config.PROXY_PORT}"
            logger.info(f"البروكسي مفعل: {proxy_display}")
        else:
            logger.info("البروكسي غير مفعل (اتصال مباشر)")
        
        async def check_channel_permissions():
            try:
                app_temp = Application.builder().token(config.BOT_TOKEN).build()
                bot = app_temp.bot
                chat_id = config.PROMO_CHANNEL_ID_NUMERIC or config.PROMO_CHANNEL_ID
                if chat_id:
                    me = await bot.get_chat_member(chat_id, bot.id)
                    if me.status not in ["administrator", "creator"]:
                        logger.warning(f"البوت ليس أدمن في القناة {chat_id}، قد لا يتمكن من النشر.")
                    else:
                        logger.info(f"البوت لديه صلاحيات النشر في القناة {chat_id}.")
                else:
                    logger.warning("لم يتم تحديد قناة للنشر، لن يتم إرسال أي محتوى.")
            except Exception as e:
                logger.warning(f"لا يمكن التحقق من صلاحيات القناة: {e}")
        
        loop.create_task(check_channel_permissions())
        
        app = Application.builder().token(config.BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("cancel", cancel_command))
        app.add_handler(CommandHandler("admin", admin.admin_panel_command))
        app.add_handler(CommandHandler("add_points", admin.add_points_command))
        app.add_handler(CommandHandler("remove_points", admin.remove_points_command))
        app.add_handler(CommandHandler("create_gift", admin.create_gift_command))
        app.add_handler(CommandHandler("ban", admin.ban_command))
        app.add_handler(CommandHandler("unban", admin.unban_command))
        app.add_handler(CommandHandler("banned_list", admin.banned_list_command))
        app.add_handler(admin.get_admin_conversation_handler())
        app.add_handler(CallbackQueryHandler(extract_button, pattern="^extract$"))
        app.add_handler(CallbackQueryHandler(create_prompt_button, pattern="^create_prompt$"))
        app.add_handler(CallbackQueryHandler(cancel_extract, pattern="^cancel_extract$"))
        app.add_handler(CallbackQueryHandler(promo_channel_handler, pattern="^promo_channel$"))
        app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_image))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'^https?://'), handle_url))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_prompt))
        app.add_handler(CallbackQueryHandler(other_callbacks, pattern="^(?!extract$|create_prompt$|cancel_extract$|admin_|promo_channel$).*$"))
        app.add_error_handler(error_handler)
        
        logger.info("البوت يعمل الآن مع poll_interval=5 وطابور خلفي")
        app.run_polling(poll_interval=5, allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.critical(f"فشل بدء التشغيل: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"فشل تشغيل البوت: {e}", exc_info=True)
        raise
