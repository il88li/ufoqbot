from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import DEVELOPER_LINK, PROMO_CHANNEL_LINK, PROMO_SUB_STARS_LINK

BTN_EXTRACT = "استخراج برومبت"
BTN_CREATE = "انشاء برومبت"
BTN_POINTS = "تجميع نقاط"
BTN_DEVELOPER = "المطور"
BTN_PROMO = "أحدث البرومبتات"
BTN_BACK = "رجوع"
BTN_VERIFY = "تحقق"
BTN_CONTACT_DEV = "تواصل مع المطور"
BTN_CANCEL = "إلغاء"
BTN_INVITE_FRIENDS = "دعوة الأصدقاء"
BTN_SUBSCRIBE_STARS = "الاشتراك مقابل نجوم"
BTN_SUBSCRIBE_PROMO = "الاشتراك في قناة البرومبتات"

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton(BTN_EXTRACT, callback_data="extract")],
        [InlineKeyboardButton(BTN_CREATE, callback_data="create_prompt")],
        [InlineKeyboardButton(BTN_POINTS, callback_data="points"),
         InlineKeyboardButton(BTN_DEVELOPER, callback_data="developer")],
        [InlineKeyboardButton(BTN_PROMO, callback_data="promo_channel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def points_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton(BTN_BACK, callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def subscription_check_keyboard():
    keyboard = [
        [InlineKeyboardButton(BTN_VERIFY, callback_data="check_sub")]
    ]
    return InlineKeyboardMarkup(keyboard)

def developer_keyboard():
    keyboard = [
        [InlineKeyboardButton(BTN_CONTACT_DEV, url=DEVELOPER_LINK)]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_BACK, callback_data="back_to_main")]
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_extract")]
    ])

def promo_required_keyboard():
    keyboard = [
        [InlineKeyboardButton(BTN_INVITE_FRIENDS, callback_data="points")],
        [InlineKeyboardButton(BTN_SUBSCRIBE_STARS, url=PROMO_SUB_STARS_LINK)]
    ]
    return InlineKeyboardMarkup(keyboard)

def promo_success_keyboard():
    keyboard = [
        [InlineKeyboardButton(BTN_SUBSCRIBE_PROMO, url=PROMO_CHANNEL_LINK)],
        [InlineKeyboardButton(BTN_BACK, callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)