import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8998562807:AAG2o-n-qcOvG5zjk_TAzNB8PZ0AM2Pyl3U")
BOT_USERNAME = os.getenv("BOT_USERNAME", "UFOQ_BOT")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@UFOQ_7")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6689435577"))

MAIN_IMAGE_URL = os.getenv("MAIN_IMAGE_URL", "https://files.catbox.moe/8yj4uc.jpg")
SUBSCRIPTION_IMAGE_URL = os.getenv("SUBSCRIPTION_IMAGE_URL", "https://i.ibb.co/Y7ggsNTN/x.jpg")
PROCESSING_STICKER_ID = os.getenv("PROCESSING_STICKER_ID", "CAACAgIAAxkBAAERoLxqag9IzKokKSE-snZhu9ETaIcVwAACRAEAAs0bMAh9vsuIBiz2Fj0E")
DEVELOPER_LINK = os.getenv("DEVELOPER_LINK", "https://t.me/OlIiIl7")
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "5242880"))

PROMO_CHANNEL_ID = os.getenv("PROMO_CHANNEL_ID", "@ufoq_pre")
PROMO_CHANNEL_ID_NUMERIC = os.getenv("PROMO_CHANNEL_ID_NUMERIC", "-1004475201874")
PROMO_CHANNEL_LINK = os.getenv("PROMO_CHANNEL_LINK", "https://t.me/ufoq_pre")
PROMO_SUB_STARS_LINK = os.getenv("PROMO_SUB_STARS_LINK", "https://t.me/+LEhEMPaWoks3MDM0")

PROXY_ENABLED = os.getenv("PROXY_ENABLED", "false").lower() == "true"
PROXY_TYPE = os.getenv("PROXY_TYPE", "socks5")
PROXY_HOST = os.getenv("PROXY_HOST", "")
PROXY_PORT = int(os.getenv("PROXY_PORT", "1080"))
PROXY_USER = os.getenv("PROXY_USER", "")
PROXY_PASS = os.getenv("PROXY_PASS", "")

DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "45"))
DOWNLOAD_RETRIES = int(os.getenv("DOWNLOAD_RETRIES", "3"))

# ===== نصوص الواجهة =====
WELCOME_TEXT = os.getenv("WELCOME_TEXT", """
<blockquote><b>مرحباً في بوت UFOQ</b>

<b>الخدمات:</b>
استخراج برومبت من صورة (رفع مباشر أو رابط Pinterest)
انشاء برومبت باستخدام الذكاء الاصطناعي (مع دعم الصور)
تجميع نقاط ودعوة الأصدقاء
أحدث البرومبتات في قناتنا

المطور: <a href="https://t.me/OlIiIl7">@OlIiIl7</a></blockquote>
""")

POINTS_INFO_TEXT = os.getenv("POINTS_INFO_TEXT", """
<blockquote><b>نظام النقاط</b>
نقطة مجانية عند البدء
نقطة إضافية لكل صديق مدعو
تُخصم نقطة لكل عملية ناجحة

رابط دعوتك: <code>{invite_link}</code>
عدد المدعوين: {invited_count}
نقاطك: <b>{points}</b></blockquote>
""")

SUB_REQUIRED_TEXT = os.getenv("SUB_REQUIRED_TEXT", """
<blockquote><b>اشترك أولاً</b>
للاستمرار، اشترك في القناة:
<a href="https://t.me/UFOQ_7">@UFOQ_7</a>
ثم اضغط <b>تحقق</b>.</blockquote>
""")

DEVELOPER_TEXT = os.getenv("DEVELOPER_TEXT", """
<blockquote><b>المطور</b>
<a href="https://t.me/OlIiIl7">@OlIiIl7</a>
للإبلاغ عن مشكلة أو اقتراح.</blockquote>
""")

NO_POINTS_TEXT = os.getenv("NO_POINTS_TEXT", """
<blockquote><b>نقاط غير كافية</b>
تحتاج نقطة واحدة على الأقل.
ادعُ أصدقائك عبر رابطك:
<code>{invite_link}</code></blockquote>
""")

REQUEST_MEDIA_TEXT = os.getenv("REQUEST_MEDIA_TEXT", """
<blockquote><b>أرسل الصورة أو الرابط</b>
أرسل صورة مباشرة أو رابط من Pinterest.
مثال: <code>https://www.pinterest.com/pin/123456789/</code></blockquote>
""")

REQUEST_PROMPT_TEXT = os.getenv("REQUEST_PROMPT_TEXT", """
<blockquote><b>أرسل البرومبت</b>
أرسل النص الذي تريد توسيعه.
يمكنك إضافة رابط صورة بعد النص مفصولاً بـ ||
مثال: <code>نص البرومبت || https://example.com/image.jpg</code></blockquote>
""")

INVALID_URL_TEXT = os.getenv("INVALID_URL_TEXT", "<blockquote>الرابط غير صالح. حاول مرة أخرى.</blockquote>")
URL_DOWNLOAD_ERROR = os.getenv("URL_DOWNLOAD_ERROR", "<blockquote>تعذر تحميل الصورة. تأكد من الرابط.</blockquote>")
AI_PROCESSING_ERROR = os.getenv("AI_PROCESSING_ERROR", "<blockquote>حدث خطأ. حاول مرة أخرى لاحقاً.</blockquote>")

GIFT_ALREADY_USED = os.getenv("GIFT_ALREADY_USED", "<blockquote>انتهت صلاحية الهدية.</blockquote>")
GIFT_SUCCESS_TEXT = os.getenv("GIFT_SUCCESS_TEXT", "<blockquote>حصلت على {points} نقطة من {code}!</blockquote>")

ADMIN_PANEL_TEXT = os.getenv("ADMIN_PANEL_TEXT", """
<blockquote><b>لوحة التحكم الإدارية</b>
استخدم الأزرار أدناه لإدارة البوت.</blockquote>
""")

GIFT_CREATED_TEXT = os.getenv("GIFT_CREATED_TEXT", """
<blockquote>تم إنشاء رابط الهدية!
النقاط: <b>{points}</b>
الحد الأقصى: <b>{max_uses}</b>
الرابط: <code>{link}</code>
الكود: <code>{code}</code></blockquote>
""")

PROMO_REQUIRED_TEXT = os.getenv("PROMO_REQUIRED_TEXT", """
<blockquote><b>اشتراك غير مكتمل</b>
تحتاج إلى دعوة 5 أصدقاء.
عدد الدعوات: {invited_count}
نقاطك: {points}
استخدم زر دعوة الأصدقاء أو الاشتراك بالنجوم.</blockquote>
""")

PROMO_SUCCESS_TEXT = os.getenv("PROMO_SUCCESS_TEXT", """
<blockquote><b>تهانينا!</b>
حققت شرط الدعوات المطلوب.
انضم الآن إلى قناة أحدث البرومبتات.</blockquote>
""")

# ===== برومبتات الذكاء الاصطناعي =====
AI_SYSTEM_PROMPT = os.getenv("AI_SYSTEM_PROMPT", """
A professional logo design, square 1:1 aspect ratio, where every letter of the brand name [BRAND_NAME] is physically shaped and constructed from the visual form of [ELEMENT] only if the user provides an element alongside the brand name, otherwise create a standalone wordmark or lettermark as appropriate; each individual character transformed into a structural component of the [ELEMENT] through continuous line work, shared contours, and seamless visual integration when element merging is requested; the letterforms themselves become the [ELEMENT] with no separation between typography and imagery when fused, strokes of each letter morphing into anatomical parts of the [ELEMENT] such as [ELEMENT_PART_1] becoming the ascenders, [ELEMENT_PART_2] forming the bowls and counters, [ELEMENT_PART_3] creating the terminals and finials when applicable; maintain perfect legibility of the brand name while the entire word reads simultaneously as a cohesive [ELEMENT] silhouette viewed from [VIEWPOINT] when merged, every curve of the letters following the natural organic flow of the [ELEMENT]'s body structure when element is specified; create a visually comfortable harmony between the name and the element or the name alone, establishing a visual identity as if crafted by a graphic designer with 15 years of experience charging no less than 3000 per logo; use a background color that makes the logo stand out prominently; render the logo at the highest possible pixel resolution; design a memorable logo that is not easily forgotten; employ [COLOR_HARMONY] color scheme with primary [PRIMARY_COLOR], secondary [SECONDARY_COLOR], and accent [ACCENT_COLOR] on a [BACKGROUND_TYPE] background; the composition follows [COMPOSITION_RULE] with the shaped wordmark occupying [POSITION] of the frame, negative space around the [ELEMENT]-letters forming subtle [NEGATIVE_SPACE_DETAIL] when element fusion is active; render in [STYLE] style with [LINE_WEIGHT] line weight, [TEXTURE] surface texture, and [FINISH] finish; ensure the letter-to-[ELEMENT] transformation is immediately recognizable at both small scale for app icons and large scale for billboards when element is provided; output as a clean vector-ready 2D logo with transparent background, no gradients unless specified, no shadows unless specified, no decorative elements outside the letter-[ELEMENT] fusion when merging is requested, single cohesive mark that functions as both readable text and iconic [ELEMENT] symbol when applicable, or as a refined standalone wordmark when no element is provided.
""")

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", """
A professional, visually balanced composition analyzed at maximum precision: analyze the overall composition framework first identifying the image aspect ratio, the rule of thirds alignment or golden ratio application, the negative space distribution, and the visual weight balance between all elements before describing individual components; the uploaded image features [product/person] positioned centrally with exact dominant color palette including tonal contrasts, primary secondary and accent colors with approximate hex values if digitally rendered, color temperature warm cool or neutral, saturation levels, and the color harmony scheme used complementary analogous triadic or monochromatic, gradient transitions color overlays or transparency effects; identify the precise spatial arrangement of every visual element, their relative positions, sizes, layering order, and implied direction vectors if motion is conveyed; detect and transcribe every visible text element individually placing each text within parentheses exactly as it appears in its precise location within the layout, preserving the original meaning feature or information conveyed, for Arabic text elements preserve the right-to-left reading direction maintain exact diacritical marks if present and note the calligraphic style or font category Kufic Naskh Thuluth etc without naming the specific font file; for logos consisting of a few letters or a single word, transform the letters themselves into thin graphic shapes in one or multiple solid colors on a plain white background, strictly 2D, maintaining strong visual balance for memorability and impact, preserve the original aspect ratio and letter spacing proportions, describe counter-shapes precisely, preserve baseline alignment and cap-height relationships between characters; if the user provides two keywords separated by a plus sign, merge the element or object with the brand name to generate a pictorial name logo where the element and name coexist in perfect visual harmony through professional positioning, shared object boundaries, and rich balanced composition, the element and text arranged in a breathtaking unforgettable layout that astonishes the viewer with its elegance and sophistication, placing the visual object first then the name; if the image depicts a person rely entirely on the uploaded image for all physical descriptions without mentioning hair, facial features, skin tone, or any personal identifiers, describing only body posture, gestures, clothing, and actions as visible in the uploaded image; if the image is a product advertisement reference only "the product in the uploaded image" without describing any product details, type, color, or specific features, however if a brand name or logo is visibly integrated into the product design itself transcribe it exactly as it appears without describing the product's physical attributes; specify lighting type, intensity, directionality, and mood only when relevant, describe shadows cast direction and softness; define camera angle or viewpoint precisely when applicable including focal length impression if discernible; state art style and realism level strictly as needed; include materials, textures, and micro-details only when they enhance clarity, describe surface textures with precision specifying glossiness level matte satin glossy mirror, surface irregularities smooth brushed hammered embossed, and material behavior under light absorption reflection refraction subsurface scattering, for fabric textures note the weave pattern drape behavior and fold geometry, identify micro-details that reveal production method such as pixelation edges for digital images, film grain structure for analog photography, print dot patterns for scanned materials, compression artifacts for web images, and brush stroke directions for hand-painted elements; outline background elements and spatial relationships if present; transcribe any visible text exactly including Arabic or English logos with precise fidelity even if outside standard fonts, without specifying the exact font name; mention exact image dimensions if provided; remove any visible designer credits, watermarks, copyright marks, or stock image overlays, if a watermark obscures a critical visual element describe what lies beneath based on visible surrounding context without inventing details; use bracketed placeholders [color], [name], [element], [text] only when information is genuinely missing or unreadable; output strictly one single line containing only the generated prompt, with no commentary, no extra text, and no formatting beyond the prompt itself.
""")
