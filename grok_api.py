import cloudscraper
import json
import re
import time
import tempfile
import os
import requests
import logging
import socks
import socket
import config
from bs4 import BeautifulSoup
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_grok_token = None
_grok_chat_uuid = None
_grok_email = None
_grok_email_id = None
_grok_session_expiry = 0
GROK_SESSION_TIMEOUT = 3600  # ساعة واحدة

ZECO_URL = "https://zecora0.serv00.net/Gmail.php"

# ============================================================
# إعداد البروكسي لـ requests و cloudscraper بشكل موحد
# ============================================================

def get_proxy_dict():
    """إرجاع إعدادات البروكسي لـ requests."""
    if not config.PROXY_ENABLED:
        return None
    
    proxy_url = ""
    if config.PROXY_TYPE in ["socks5", "socks4"]:
        scheme = config.PROXY_TYPE
        if config.PROXY_USER and config.PROXY_PASS:
            proxy_url = f"{scheme}://{config.PROXY_USER}:{config.PROXY_PASS}@{config.PROXY_HOST}:{config.PROXY_PORT}"
        else:
            proxy_url = f"{scheme}://{config.PROXY_HOST}:{config.PROXY_PORT}"
    else:
        proxy_url = f"http://{config.PROXY_HOST}:{config.PROXY_PORT}"
    
    return {
        "http": proxy_url,
        "https": proxy_url
    }

def get_cloudscraper():
    """إنشاء cloudscraper مع دعم البروكسي."""
    scraper = cloudscraper.create_scraper()
    if config.PROXY_ENABLED:
        proxies = get_proxy_dict()
        if proxies:
            scraper.proxies = proxies
    return scraper

# ============================================================
# دوال Grok مع دعم البروكسي (تم توحيد استخدام cloudscraper)
# ============================================================

def _create_email():
    try:
        scraper = get_cloudscraper()
        resp = scraper.get(f"{ZECO_URL}?action=create", timeout=15)
        if resp.status_code != 200:
            raise Exception(f"فشل إنشاء البريد (HTTP {resp.status_code})")
        data = resp.json()
        if 'error' in data or not data.get('email'):
            raise Exception(f"فشل إنشاء البريد: {data}")
        return data['email'], data['id']
    except Exception as e:
        raise Exception(f"خطأ في إنشاء البريد: {e}")

def _send_otp(email, scraper):
    resp = scraper.post(
        'https://api.syntx.ai/api/v1/auth/email/send-otp',
        json={"email": email, "ref_uuid": None, "utm": ""},
        headers={'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36'},
        timeout=30
    )
    if resp.status_code != 200 or not resp.json().get('success'):
        raise Exception(f"فشل إرسال رمز التحقق (HTTP {resp.status_code})")
    logger.info("تم إرسال OTP بنجاح")

def _wait_for_otp(email, email_id, scraper, timeout=180):
    last_id = None
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = scraper.get(
                f"{ZECO_URL}?action=get_messages&mailbox_id={email_id}&email={email}",
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0 and data[0].get('id') != last_id:
                    last_id = data[0]['id']
                    content = data[0].get('html', '') or data[0].get('text', '') or data[0].get('body', '')
                    match = re.search(r'\b(\d{6})\b', content)
                    if match:
                        logger.info("تم استلام OTP")
                        return match.group(1)
        except Exception as e:
            logger.debug(f"خطأ في انتظار OTP: {e}")
        time.sleep(2)
    raise Exception("لم يتم استلام رمز التحقق خلال المهلة")

def _verify_otp(email, otp, scraper):
    resp = scraper.post(
        'https://api.syntx.ai/api/v1/auth/email/verify-otp',
        json={"email": email, "otp_code": otp, "ref_uuid": None, "utm": ""},
        headers={'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36'},
        timeout=30
    )
    if resp.status_code != 200 or not resp.json().get('success'):
        raise Exception(f"فشل التحقق من الرمز (HTTP {resp.status_code})")
    token = resp.json().get('token')
    if not token:
        raise Exception("لم يتم استلام توكن")
    logger.info("تم التحقق من OTP واستلام التوكن")
    return token

def _create_chat(token, scraper):
    resp = scraper.post(
        'https://api.syntx.ai/api/v1/chats',
        json={"title": "Grok Chat", "scope": "text"},
        headers={'Authorization': f'Bearer {token}', 'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36'},
        timeout=30
    )
    if resp.status_code != 201:
        raise Exception(f"فشل إنشاء المحادثة (HTTP {resp.status_code})")
    uuid = resp.json().get('uuid')
    if not uuid:
        raise Exception("لم يتم استلام UUID")
    logger.info(f"تم إنشاء المحادثة: {uuid}")
    return uuid

def init_grok_session(max_retries=3):
    global _grok_token, _grok_chat_uuid, _grok_email, _grok_email_id
    for attempt in range(max_retries):
        try:
            scraper = get_cloudscraper()
            _grok_email, _grok_email_id = _create_email()
            _send_otp(_grok_email, scraper)
            otp = _wait_for_otp(_grok_email, _grok_email_id, scraper, timeout=180)
            _grok_token = _verify_otp(_grok_email, otp, scraper)
            _grok_chat_uuid = _create_chat(_grok_token, scraper)
            logger.info(f"تم تهيئة جلسة Grok بنجاح (المحاولة {attempt+1})")
            return _grok_token, _grok_chat_uuid
        except Exception as e:
            logger.error(f"محاولة {attempt+1}/{max_retries} فشلت في تهيئة جلسة Grok: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(5)
    return _grok_token, _grok_chat_uuid

def get_grok_session():
    global _grok_token, _grok_chat_uuid, _grok_session_expiry
    now = time.time()
    
    if not _grok_token or not _grok_chat_uuid or (now + 300) > _grok_session_expiry:
        logger.info("جلسة Grok منتهية أو على وشك الانتهاء، إعادة التهيئة...")
        token, uuid = init_grok_session()
        if token and uuid:
            _grok_token = token
            _grok_chat_uuid = uuid
            _grok_session_expiry = now + GROK_SESSION_TIMEOUT
            return _grok_token, _grok_chat_uuid
        raise Exception("تعذر تهيئة جلسة Grok")
    
    return _grok_token, _grok_chat_uuid

def force_refresh_session():
    global _grok_token, _grok_chat_uuid, _grok_session_expiry
    logger.info("إعادة تهيئة جلسة Grok (فرض)...")
    _grok_token = None
    _grok_chat_uuid = None
    _grok_session_expiry = 0
    return get_grok_session()

def upload_image_to_grok(chat_uuid, image_bytes, token):
    """رفع الصورة باستخدام cloudscraper مع البروكسي."""
    for attempt in range(2):
        try:
            scraper = get_cloudscraper()
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name
            try:
                with open(tmp_path, 'rb') as f:
                    files = {'files': (os.path.basename(tmp_path), f, 'application/octet-stream')}
                    data = {'check_duplicates': 'true', 'chat_uuid': chat_uuid}
                    headers = {'Authorization': f'Bearer {token}'}
                    # استخدام cloudscraper بدلاً من requests لضمان البروكسي
                    resp = scraper.post(
                        'https://api.syntx.ai/api/v1/chats/upload-files',
                        data=data,
                        files=files,
                        headers=headers,
                        timeout=45
                    )
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get('successful', 0) > 0 and result.get('files'):
                        url = result['files'][0]['url']
                        logger.info(f"تم رفع الصورة بنجاح: {url}")
                        return url
                    else:
                        raise Exception("رفع الصورة فشل: response لا يحتوي على ملفات")
                else:
                    raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"محاولة رفع الصورة {attempt+1}/2 فشلت: {e}")
            if attempt == 1:
                raise
            time.sleep(2)
    raise Exception("فشل رفع الصورة بعد محاولتين")

def send_message_to_grok(chat_uuid, objects, token):
    for attempt in range(2):
        try:
            scraper = get_cloudscraper()
            resp = scraper.post(
                f"https://api.syntx.ai/api/v1/chats/{chat_uuid}/messages?ai_name=grok",
                json={"objects": objects},
                headers={'Authorization': f'Bearer {token}', 'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36'},
                timeout=45
            )
            if resp.status_code == 200:
                msg_id = resp.json().get('id')
                if not msg_id:
                    raise Exception("لم يتم استلام معرف الرسالة")
                logger.info(f"تم إرسال الرسالة إلى Grok، المعرف: {msg_id}")
                return msg_id
            else:
                raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"محاولة إرسال الرسالة {attempt+1}/2 فشلت: {e}")
            if attempt == 1:
                raise
            time.sleep(2)
    raise Exception("فشل إرسال الرسالة بعد محاولتين")

def wait_for_reply(chat_uuid, last_msg_id, token, timeout=180):
    scraper = get_cloudscraper()
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = scraper.get(
                f"https://api.syntx.ai/api/v1/chats/{chat_uuid}/messages?page_size=20",
                headers={'Authorization': f'Bearer {token}', 'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36'},
                timeout=20
            )
            if resp.status_code == 200:
                for msg in resp.json().get('messages', []):
                    if msg.get('author_id') == -1 and msg.get('id', 0) > last_msg_id:
                        obj = msg.get('message_object', [{}])[0]
                        if obj and obj.get('object_type') == 'text' and obj.get('completed'):
                            logger.info("تم استلام الرد من Grok")
                            return obj.get('object_text')
            else:
                logger.debug(f"wait_for_reply: HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"wait_for_reply: {e}")
        time.sleep(3)
    raise Exception("لم يتم استلام رد من Grok خلال المهلة المحددة")

# ============================================================
# دوال تحميل الصور من الروابط (محسّنة - بدون Facebook و Freepik)
# ============================================================

def download_image_from_url(url, max_size=5*1024*1024):
    """
    تحميل صورة من رابط مع دعم خاص لـ Pinterest والروابط المباشرة والمواقع العامة.
    تم حذف دعم Facebook و Freepik بالكامل.
    """
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        raise ValueError("الرابط غير صالح: يجب أن يبدأ بـ http:// أو https://")
    
    scraper = get_cloudscraper()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # 1. محاولة التحميل المباشر (إذا كان الرابط ينتهي بامتداد صورة)
    image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
    if url.lower().endswith(image_extensions):
        try:
            resp = scraper.get(url, headers=headers, timeout=config.DOWNLOAD_TIMEOUT)
            if resp.status_code == 200 and 'image' in resp.headers.get('content-type', ''):
                data = resp.content
                if len(data) <= max_size:
                    logger.info(f"تم تحميل الصورة مباشرة من الرابط: {url}")
                    return data
                else:
                    raise Exception(f"حجم الصورة كبير جداً ({len(data)} بايت)")
        except Exception as e:
            logger.warning(f"فشل التحميل المباشر: {e}")
    
    # 2. معالجة خاصة حسب المنصة
    domain = urlparse(url).netloc.lower()
    
    # 2.1 Pinterest
    if 'pinterest' in domain:
        logger.info(f"اكتشاف رابط Pinterest: {url}")
        return _download_from_pinterest(url, scraper, headers, max_size)
    
    # 2.2 منصات أخرى (عامة)
    else:
        logger.info(f"رابط عام، محاولة استخراج og:image: {url}")
        return _download_from_generic(url, scraper, headers, max_size)

# ============================================================
# دوال مساعدة لكل منصة
# ============================================================

def _download_image_from_url(img_url, max_size, headers=None):
    """تحميل صورة من رابط مباشر مع التحقق من الحجم والنوع."""
    scraper = get_cloudscraper()
    if not headers:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = scraper.get(img_url, headers=headers, timeout=config.DOWNLOAD_TIMEOUT, stream=True)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code} عند تحميل الصورة")
    content_type = resp.headers.get('content-type', '')
    if 'image' not in content_type:
        raise Exception(f"الرابط لا يؤدي إلى صورة (نوع المحتوى: {content_type})")
    data = b''
    for chunk in resp.iter_content(chunk_size=8192):
        data += chunk
        if len(data) > max_size:
            raise Exception(f"حجم الصورة كبير جداً ({len(data)} بايت)")
    if len(data) == 0:
        raise Exception("البيانات فارغة")
    return data

def _download_from_pinterest(url, scraper, headers, max_size):
    """استخراج الصورة من Pinterest."""
    for attempt in range(config.DOWNLOAD_RETRIES):
        try:
            resp = scraper.get(url, headers=headers, timeout=config.DOWNLOAD_TIMEOUT)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            soup = BeautifulSoup(resp.text, 'lxml')
            
            # محاولة 1: og:image
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                img_url = og_image['content']
                if '?' in img_url:
                    img_url = img_url.split('?')[0]
                return _download_image_from_url(img_url, max_size, headers)
            
            # محاولة 2: البحث عن صورة داخل pin
            pin_img = soup.find('img', {'data-test-id': 'pin-image'})
            if pin_img and pin_img.get('src'):
                return _download_image_from_url(pin_img['src'], max_size, headers)
            
            # محاولة 3: أي صورة كبيرة
            images = soup.find_all('img')
            for img in images:
                src = img.get('src')
                if src and not src.startswith('data:') and 'logo' not in src.lower():
                    if not src.startswith('http'):
                        parsed = urlparse(url)
                        base = f"{parsed.scheme}://{parsed.netloc}"
                        src = base + src if src.startswith('/') else base + '/' + src
                    try:
                        return _download_image_from_url(src, max_size, headers)
                    except:
                        continue
            
            raise Exception("لم يتم العثور على صورة صالحة في صفحة Pinterest")
        
        except Exception as e:
            logger.error(f"محاولة {attempt+1} من Pinterest فشلت: {e}")
            if attempt == config.DOWNLOAD_RETRIES - 1:
                raise Exception(f"فشل تحميل الصورة من Pinterest بعد {config.DOWNLOAD_RETRIES} محاولات: {str(e)}")
            time.sleep(2 ** attempt)

def _download_from_generic(url, scraper, headers, max_size):
    """استخراج الصورة من مواقع عامة باستخدام og:image وأول img كبير."""
    for attempt in range(config.DOWNLOAD_RETRIES):
        try:
            resp = scraper.get(url, headers=headers, timeout=config.DOWNLOAD_TIMEOUT)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            soup = BeautifulSoup(resp.text, 'lxml')
            
            # محاولة 1: og:image
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                img_url = og_image['content']
                if not img_url.startswith('http'):
                    parsed = urlparse(url)
                    base = f"{parsed.scheme}://{parsed.netloc}"
                    img_url = base + img_url if img_url.startswith('/') else base + '/' + img_url
                try:
                    return _download_image_from_url(img_url, max_size, headers)
                except Exception as e:
                    logger.warning(f"فشل تحميل og:image: {e}")
            
            # محاولة 2: أول img بعرض > 300
            images = soup.find_all('img')
            for img in images:
                src = img.get('src')
                if src and not src.startswith('data:'):
                    width = img.get('width')
                    if width and width.isdigit() and int(width) < 300:
                        continue
                    if not src.startswith('http'):
                        parsed = urlparse(url)
                        base = f"{parsed.scheme}://{parsed.netloc}"
                        src = base + src if src.startswith('/') else base + '/' + src
                    try:
                        return _download_image_from_url(src, max_size, headers)
                    except:
                        continue
            
            raise Exception("لم يتم العثور على صورة صالحة في الصفحة")
        
        except Exception as e:
            logger.error(f"محاولة {attempt+1} من موقع عام فشلت: {e}")
            if attempt == config.DOWNLOAD_RETRIES - 1:
                raise Exception(f"فشل تحميل الصورة من الرابط بعد {config.DOWNLOAD_RETRIES} محاولات: {str(e)}")
            time.sleep(2 ** attempt)
