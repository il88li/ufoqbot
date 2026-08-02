import logging
import sqlite3
import time
import asyncio
import os
import aiohttp
import re
import json
from fastapi import FastAPI, Request, Response
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
# دوال البوت الأساسية ومعالجات الأزرار
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /start مع دعم روابط الإحالة والهدايا."""
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # التحقق من الحظر
    if database.is_banned(user_id):
        await update.message.reply_text("🚫 أنت محظور من استخدام هذا البوت.")
        return
    
    # معالجة روابط الإحالة والهدايا
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            referrer_id = int(arg[4:])
            if referrer_id != user_id:
                # إضافة المستخدم وتحديث نقاط المُحيل
                if database.add_user(user_id, referrer_id):
                    await update.message.reply_text("✅ تم التسجيل بنجاح! حصلت على نقطة مجانية، ومُحيلك حصل على نقطة إضافية.")
                else:
                    await update.message.reply_text("👋 مرحباً بعودتك!")
            else:
                await update.message.reply_text("👋 لا يمكنك دعوة نفسك.")
        elif arg.startswith("gift_"):
            code = arg[5:]
            gift_info = database.get_gift_info(code)
            if gift_info is None:
                await update.message.reply_text(config.GIFT_ALREADY_USED)
            else:
                result = database.use_gift(code)
                if result == "expired":
                    await update.message.reply_text("❌ انتهت صلاحية هذه الهدية.")
                elif result == "success":
                    # إضافة نقاط للمستخدم
                    database.add_user(user_id)  # إنشاء المستخدم إذا لم يكن موجوداً
                    database.add_points(user_id, gift_info['points'])
                    await update.message.reply_text(
                        config.GIFT_SUCCESS_TEXT.format(
                            points=gift_info['points'],
                            code=code
                        )
                    )
                else:
                    await update.message.reply_text("❌ حدث خطأ في استخدام الهدية.")
        else:
            await update.message.reply_text("👋 مرحباً! استخدم الأزرار أدناه.")
    else:
        # مستخدم جديد أو عادي
        database.add_user(user_id)
    
    # عرض القائمة الرئيسية
    text = config.WELCOME_TEXT.format(
        bot_username=config.BOT_USERNAME
    )
    
    # إرسال الصورة الرئيسية إن وجدت
    if config.MAIN_IMAGE_URL:
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=config.MAIN_IMAGE_URL,
                caption=text,
                parse_mode='HTML',
                reply_markup=keyboards.main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"فشل إرسال الصورة الرئيسية: {e}")
            await update.message.reply_text(
                text,
                parse_mode='HTML',
                reply_markup=keyboards.main_menu_keyboard()
            )
    else:
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=keyboards.main_menu_keyboard()
        )

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """التحقق من اشتراك المستخدم في القناة الإجبارية."""
    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=config.CHANNEL_ID,
            user_id=user_id
        )
        if chat_member.status in ["member", "administrator", "creator"]:
            return True
    except Exception as e:
        logger.warning(f"فشل التحقق من اشتراك المستخدم {user_id}: {e}")
        # في حالة الخطأ نسمح مؤقتاً (يمكن تعديل السلوك)
        return True
    return False

async def extract_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة زر 'استخراج برومبت'."""
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    user_id = update.effective_user.id
    
    # التحقق من الحظر والحدود
    if database.is_banned(user_id):
        await query.edit_message_text("🚫 أنت محظور من استخدام هذه الميزة.")
        return
    if not check_rate_limit(user_id):
        await safe_answer_query(query, "وصلت للحد الأقصى من الطلبات.", show_alert=True)
        return
    if not await check_subscription(user_id, context):
        await query.edit_message_text(
            config.SUB_REQUIRED_TEXT,
            parse_mode='HTML',
            reply_markup=keyboards.subscription_check_keyboard()
        )
        return
    
    # التحقق من النقاط
    user_data = database.get_user(user_id)
    if user_data is None or user_data["points"] < 1:
        await query.edit_message_text(
            config.NO_POINTS_TEXT.format(
                invite_link=database.get_invite_link(user_id)
            ),
            parse_mode='HTML',
            reply_markup=keyboards.points_menu_keyboard()
        )
        return
    
    # خصم النقطة
    database.add_points(user_id, -1)
    logger.info(f"تم خصم نقطة من المستخدم {user_id} لعملية الاستخراج")
    
    # طلب إرسال الصورة
    await query.edit_message_text(
        config.REQUEST_MEDIA_TEXT,
        parse_mode='HTML',
        reply_markup=keyboards.cancel_keyboard()
    )
    context.user_data["awaiting_extract"] = True

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الصور والروابط المرسلة من المستخدم."""
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    
    if not context.user_data.get("awaiting_extract", False):
        await update.message.reply_text("الرجاء الضغط على زر 'استخراج برومبت' أولاً.")
        return
    
    # التحقق من الحظر والنقاط مرة أخرى
    if database.is_banned(user_id):
        await update.message.reply_text("🚫 أنت محظور.")
        context.user_data["awaiting_extract"] = False
        return
    user_data = database.get_user(user_id)
    if user_data is None or user_data["points"] < 0:  # يمكن أن تكون سالبة؟ لكننا نمنع
        await update.message.reply_text("لا تملك نقاطاً كافية.")
        context.user_data["awaiting_extract"] = False
        return
    
    image_bytes = None
    image_url = None
    photo = None
    
    # حالة 1: صورة مباشرة
    if update.message.photo:
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            image_bytes = await file.download_as_bytearray()
            logger.info(f"تم استلام صورة من المستخدم {user_id}")
        except Exception as e:
            logger.error(f"فشل تحميل الصورة: {e}")
            await update.message.reply_text("❌ فشل تحميل الصورة. حاول مرة أخرى.")
            return
    
    # حالة 2: رابط
    elif update.message.text and update.message.text.startswith(('http://', 'https://')):
        url = update.message.text.strip()
        try:
            # استخدام asyncio.to_thread لتجنب حظر الحدث
            image_bytes = await asyncio.to_thread(
                grok_api.download_image_from_url,
                url,
                config.MAX_IMAGE_SIZE
            )
            image_url = url
            logger.info(f"تم تحميل صورة من الرابط {url} للمستخدم {user_id}")
        except Exception as e:
            logger.error(f"فشل تحميل الصورة من الرابط: {e}")
            await update.message.reply_text(config.URL_DOWNLOAD_ERROR)
            return
    else:
        await update.message.reply_text("❌ الرجاء إرسال صورة أو رابط صورة صالح.")
        return
    
    if not image_bytes:
        await update.message.reply_text("❌ لم يتم استلام بيانات الصورة.")
        return
    
    # التحقق من حجم الصورة
    if len(image_bytes) > config.MAX_IMAGE_SIZE:
        await update.message.reply_text(f"❌ حجم الصورة يتجاوز الحد الأقصى ({config.MAX_IMAGE_SIZE//1024//1024} ميجابايت).")
        context.user_data["awaiting_extract"] = False
        return
    
    # إرسال رسالة "جاري المعالجة"
    status_msg = await update.message.reply_text("⏳ جاري تحليل الصورة...")
    
    # وضع المهمة في الطابور
    if analysis_queue.qsize() >= MAX_QUEUE_SIZE:
        await status_msg.edit_text("❌ الطابور ممتلئ. حاول مرة أخرى لاحقاً.")
        context.user_data["awaiting_extract"] = False
        return
    
    task = {
        "user_id": user_id,
        "image_bytes": image_bytes,
        "context": context,
        "queue_message_id": status_msg.message_id,
        "photo": photo.file_id if photo else None,
        "image_url": image_url
    }
    await analysis_queue.put(task)
    logger.info(f"تم إضافة طلب المستخدم {user_id} إلى الطابور (الطول: {analysis_queue.qsize()})")
    
    context.user_data["awaiting_extract"] = False

async def points_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة زر 'تجميع نقاط'."""
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    user_id = update.effective_user.id
    
    user_data = database.get_user(user_id)
    if user_data is None:
        await query.edit_message_text("❌ لم يتم العثور على بياناتك.")
        return
    
    invited_count = database.get_invited_count(user_id)
    invite_link = database.get_invite_link(user_id)
    
    text = config.POINTS_INFO_TEXT.format(
        points=user_data["points"],
        invited_count=invited_count,
        invite_link=invite_link
    )
    
    # التحقق من شرط الدعوات للترويج
    if invited_count >= 5:
        # عرض رسالة الترويج
        promo_text = config.PROMO_SUCCESS_TEXT
        await query.edit_message_text(
            promo_text,
            parse_mode='HTML',
            reply_markup=keyboards.promo_success_keyboard()
        )
    else:
        # عرض النقاط مع خيارات الدعوة
        keyboard = [
            [InlineKeyboardButton("📤 دعوة الأصدقاء", callback_data="share_invite")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
        ]
        if invited_count < 5:
            keyboard.insert(0, [InlineKeyboardButton("⭐ اشتراك بالنجوم", url=config.PROMO_SUB_STARS_LINK)])
        
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def share_invite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاركة رابط الدعوة."""
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    user_id = update.effective_user.id
    
    invite_link = database.get_invite_link(user_id)
    await query.edit_message_text(
        f"<blockquote>📤 رابط دعوتك:\n<code>{invite_link}</code>\n\nشاركه مع أصدقائك واحصل على نقاط!</blockquote>",
        parse_mode='HTML',
        reply_markup=keyboards.back_keyboard()
    )

async def developer_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة زر 'المطور'."""
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    
    text = config.DEVELOPER_TEXT
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=keyboards.developer_keyboard()
    )

async def promo_channel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة زر 'أحدث البرومبتات'."""
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    
    user_id = update.effective_user.id
    invited_count = database.get_invited_count(user_id)
    
    if invited_count >= 5:
        await query.edit_message_text(
            config.PROMO_SUCCESS_TEXT,
            parse_mode='HTML',
            reply_markup=keyboards.promo_success_keyboard()
        )
    else:
        await query.edit_message_text(
            config.PROMO_REQUIRED_TEXT.format(
                invited_count=invited_count,
                points=database.get_user(user_id)["points"]
            ),
            parse_mode='HTML',
            reply_markup=keyboards.promo_required_keyboard()
        )

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """العودة إلى القائمة الرئيسية."""
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    
    text = config.WELCOME_TEXT.format(bot_username=config.BOT_USERNAME)
    
    if config.MAIN_IMAGE_URL:
        try:
            await query.edit_message_caption(
                caption=text,
                parse_mode='HTML',
                reply_markup=keyboards.main_menu_keyboard()
            )
        except:
            await query.edit_message_text(
                text,
                parse_mode='HTML',
                reply_markup=keyboards.main_menu_keyboard()
            )
    else:
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=keyboards.main_menu_keyboard()
        )

async def cancel_extract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء عملية الاستخراج."""
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    
    context.user_data["awaiting_extract"] = False
    context.user_data["awaiting_ai_prompt"] = False
    
    text = "❌ تم إلغاء العملية."
    await query.edit_message_text(text)
    # العودة للقائمة الرئيسية بعد لحظة
    await asyncio.sleep(1)
    await back_to_main(update, context)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء أي عملية جارية عبر الأمر /cancel."""
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    
    context.user_data["awaiting_extract"] = False
    context.user_data["awaiting_ai_prompt"] = False
    
    await update.message.reply_text(
        "❌ تم إلغاء العملية.",
        reply_markup=keyboards.main_menu_keyboard()
    )

async def gift_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استخدام كود هدية عبر الأمر /gift <code>."""
    if update.effective_user is None:
        return
    user_id = update.effective_user.id
    
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ الاستخدام: /gift <الكود>")
        return
    
    code = args[0].strip()
    gift_info = database.get_gift_info(code)
    if gift_info is None:
        await update.message.reply_text(config.GIFT_ALREADY_USED)
        return
    
    result = database.use_gift(code)
    if result == "expired":
        await update.message.reply_text("❌ انتهت صلاحية هذه الهدية.")
    elif result == "success":
        database.add_user(user_id)
        database.add_points(user_id, gift_info['points'])
        await update.message.reply_text(
            config.GIFT_SUCCESS_TEXT.format(
                points=gift_info['points'],
                code=code
            )
        )
    else:
        await update.message.reply_text("❌ حدث خطأ في استخدام الهدية.")

# ============================================================
# معالج المحادثة الإداري (من admin.py)
# ============================================================

def setup_admin_handlers(app: Application):
    """إعداد معالج المحادثة الإداري."""
    admin_handler = admin.get_admin_conversation_handler()
    app.add_handler(admin_handler)

# ============================================================
# تكوين FastAPI و webhook
# ============================================================

# إنشاء تطبيق FastAPI
app = FastAPI(title="UFOQ Bot", version="2.0.0")

# إنشاء تطبيق Telegram
telegram_app = Application.builder().token(config.BOT_TOKEN).build()

# إعداد المعالجات
telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(CommandHandler("cancel", cancel_command))
telegram_app.add_handler(CommandHandler("gift", gift_command))

# أزرار القائمة الرئيسية
telegram_app.add_handler(CallbackQueryHandler(extract_button, pattern="^extract$"))
telegram_app.add_handler(CallbackQueryHandler(create_prompt_button, pattern="^create_prompt$"))
telegram_app.add_handler(CallbackQueryHandler(points_button, pattern="^points$"))
telegram_app.add_handler(CallbackQueryHandler(developer_button, pattern="^developer$"))
telegram_app.add_handler(CallbackQueryHandler(promo_channel_button, pattern="^promo_channel$"))
telegram_app.add_handler(CallbackQueryHandler(share_invite_button, pattern="^share_invite$"))
telegram_app.add_handler(CallbackQueryHandler(back_to_main, pattern="^back_to_main$"))
telegram_app.add_handler(CallbackQueryHandler(cancel_extract, pattern="^cancel_extract$"))
telegram_app.add_handler(CallbackQueryHandler(check_subscription_button, pattern="^check_sub$"))

# معالجات المحادثة
telegram_app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_media))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_prompt))

# إعداد المعالج الإداري
setup_admin_handlers(telegram_app)

# دالة التحقق من الاشتراك عبر زر
async def check_subscription_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة زر التحقق من الاشتراك."""
    if update.effective_user is None:
        return
    query = update.callback_query
    await safe_answer_query(query)
    user_id = update.effective_user.id
    
    if await check_subscription(user_id, context):
        await query.edit_message_text("✅ تم التحقق من اشتراكك! يمكنك استخدام البوت.")
        # عرض القائمة الرئيسية
        text = config.WELCOME_TEXT.format(bot_username=config.BOT_USERNAME)
        await query.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=keyboards.main_menu_keyboard()
        )
    else:
        await query.edit_message_text(
            config.SUB_REQUIRED_TEXT,
            parse_mode='HTML',
            reply_markup=keyboards.subscription_check_keyboard()
        )

# ============================================================
# نقطة نهاية webhook
# ============================================================

@app.post("/webhook")
async def webhook(request: Request):
    """نقطة نهاية استقبال تحديثات Telegram."""
    try:
        # قراءة البيانات
        data = await request.json()
        logger.info(f"استلام تحديث من Telegram: {data.get('update_id', 'unknown')}")
        
        # إنشاء كائن Update
        update = Update.de_json(data, telegram_app.bot)
        
        # معالجة التحديث
        await telegram_app.process_update(update)
        
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"خطأ في معالجة webhook: {e}", exc_info=True)
        return Response(status_code=500)

@app.get("/")
async def root():
    """نقطة نهاية صحية للتحقق من تشغيل البوت."""
    return {"status": "running", "bot": config.BOT_USERNAME}

# ============================================================
# دالة تعيين webhook
# ============================================================

async def set_webhook():
    """تعيين webhook عند بدء التشغيل."""
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        logger.warning("WEBHOOK_URL غير محددة، استخدم polling محلياً.")
        return False
    
    # إزالة أي webhook سابق
    await telegram_app.bot.delete_webhook()
    
    # تعيين webhook الجديد
    result = await telegram_app.bot.set_webhook(
        url=f"{webhook_url}/webhook",
        drop_pending_updates=True
    )
    
    if result:
        logger.info(f"✅ تم تعيين webhook بنجاح: {webhook_url}/webhook")
    else:
        logger.error("❌ فشل تعيين webhook")
    
    return result

# ============================================================
# أحداث بدء وإيقاف التشغيل
# ============================================================

@app.on_event("startup")
async def startup_event():
