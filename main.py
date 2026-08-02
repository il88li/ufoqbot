import logging
import sqlite3
import time
import asyncio
import os
import aiohttp
import re
import json
from flask import Flask, request, jsonify
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
# معالجة استخراج البرومبت
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
            
            try:
                token, chat_uuid = grok_api.get_grok_session()
            except Exception as e:
                logger.warning(f"فشل الحصول على جلسة Grok، إعادة تهيئة: {e}")
                token, chat_uuid = grok_api.force_refresh_session()
            
            upload_attempts = 3
            for upload_attempt in range(upload_attempts):
                try:
                    image_url = grok_api.upload_image_to_grok(chat_uuid, image_bytes, token)
                    break
                except Exception as e:
                    logger.warning(f"فشل رفع الصورة، المحاولة {upload_attempt+1}/{upload_attempts}: {e}")
                    if upload_attempt == upload_attempts - 1:
                        raise
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
# معالجة "انشاء برومبت"
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
        await safe_edit_caption(query, caption, back_k