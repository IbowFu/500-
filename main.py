import asyncio
import random
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========================= إعدادات أساسية =========================
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])

DEFAULT_CHANNEL = "@ForexNews24hours"
BOT_USERNAME = "get500dollar_bot"

# سيتم تحميل المستخدمين من قاعدة البيانات
users = {}

withdraw_limit = 500
SUB_CHANNELS = [DEFAULT_CHANNEL]
referral_reward = 1.0

# ========================= دوال قاعدة البيانات =========================
def get_db_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            balance REAL DEFAULT 0,
            invites TEXT DEFAULT '[]'
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def load_users_from_db():
    global users
    users = {}
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, name, balance, invites FROM users")
    for row in cur.fetchall():
        uid = row["user_id"]
        invites_list = json.loads(row["invites"]) if row["invites"] else []
        users[uid] = {
            "name": row["name"],
            "balance": float(row["balance"]),
            "invites": set(invites_list),
            "subscribed": True,
            "pending_pay": None,
            "pending_pay_info": None,
            "pending_inviter": None
        }
    cur.close()
    conn.close()

def save_user_to_db(uid, data):
    conn = get_db_connection()
    cur = conn.cursor()
    invites_json = json.dumps(list(data["invites"]))
    cur.execute("""
        INSERT INTO users (user_id, name, balance, invites)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET
            name = EXCLUDED.name,
            balance = EXCLUDED.balance,
            invites = EXCLUDED.invites
    """, (uid, data["name"], data["balance"], invites_json))
    conn.commit()
    cur.close()
    conn.close()

# ========================= باقي الإعدادات والرسائل =========================
MESSAGES = {
    "main_menu": (
        "مرحباً بك في البوت الربحي!\n"
        "اختر من القائمة:\n\n"
        "⚠️ *ملاحظة مهمة*: لا يتم احتساب الحسابات الوهمية أو المؤقتة التي تشترك في القناة.\n"
        "فقط الحسابات الحقيقية تُحتسب ضمن نظام الإحالة والمكافآت! 🤖❌"
    ),
    "stats": "رصيدك الحالي: {balance}$\nعدد المدعوين: {invites}\n(يمكنك السحب عند {limit}$)",
    "invite": "شارك الرابط وقم بدعوة أصدقائك وكسب أرباح:\n{link}",
    "withdraw_menu": "اختر وسيلة الدفع التي تناسبك:",
    "withdraw_fail": "رصيدك الحالي ({balance}$) أقل من الحد الأدنى للسحب ({limit}$).\nلا يمكنك تقديم طلب السحب قبل الوصول إلى {limit}$.",
    "admin_settings": "لوحة الإعدادات الإدارية:\n• الحد الأدنى للسحب: {limit}$\n• ربح الإحالة: {referral}$\nاختر من التالي:"
}

PAY_METHODS = [
    ("💵 PayPal (عالمي)", "أرسل بريد بوابة PayPal الخاصة بك"),
    ("💳 Visa/MasterCard (عالمي)", "أرسل رقم البطاقة والاسم وتاريخ الانتهاء"),
    ("💵 USDT (TRC20)", "أرسل عنوان محفظتك USDT (TRC20)"),
    ("🪙 Bitcoin", "أرسل عنوان محفظة Bitcoin"),
    ("💵 Payeer", "أرسل رقم حساب Payeer الخاص بك"),
    ("💵 Perfect Money", "أرسل رقم حساب Perfect Money"),
    ("💵 WebMoney", "أرسل رقم المحفظة WebMoney"),
    ("💵 AdvCash", "أرسل بريد حساب AdvCash"),
    ("💵 Skrill", "أرسل بريد Skrill"),
    ("💵 Neteller", "أرسل بريد Neteller"),
    ("💰 Western Union (عالمي)", "أرسل اسمك ورقم الإرسال"),
    ("💵 Payoneer", "أرسل بريد حساب Payoneer"),
    ("📱 Syriatel كاش (سوريا)", "أرسل رقم Syriatel كاش"),
    ("📱 MTN كاش (سوريا)", "أرسل رقم MTN كاش"),
    ("📱 شام كاش (سوريا)", "أرسل رقم شام أو اسم الحساب"),
    ("🏦 بنك بيمو سعودي فرنسي (سوريا)", "أرسل رقم بيمو أو الاسم الكامل"),
    ("🏦 بنك البركة (سوريا)", "أرسل رقم المواطن في بنك البركة"),
    ("📱 فودافون كاش (مصر)", "أرسل رقم فودافون كاش"),
    ("📱 أورانج كاش (مصر)", "أرسل رقم أورانج كاش"),
    ("📱 Etisalat Cash (مصر)", "أرسل رقمك في اتصالات كاش"),
    ("🏦 بنك مصر", "أرسل رقم حساب بنك مصر"),
    ("📱 دينارك (الأردن)", "أرسل رقم حساب دينارك"),
    ("🏦 بنك الإسكان (الأردن)", "أرسل رقم حساب بنك الإسكان"),
    ("📱 زين كاش (العراق)", "أرسل رقم زين كاش"),
    ("📦 MoneyGram (العراق)", "أرسل اسم المستلم ورقم الحوالة"),
    ("📱 وفاكاش (المغرب)", "أرسل رقم وفاكاش"),
    ("🏦 CIH Bank (المغرب)", "أرسل رقم حساب CIH Bank"),
    ("📱 بريد الجزائر (الجزائر)", "أرسل رقم بريد الجزائر"),
    ("🏦 بنك ABC الجزائر", "أرسل رقم حساب بنك ABC الجزائر"),
    ("🏦 بنك الراجحي (السعودية)", "أرسل رقم حساب بنك الراجحي"),
    ("🏦 بنك الأهلي السعودي", "أرسل رقم حساب الأهلي"),
    ("📱 Jawwal Pay (فلسطين)", "أرسل رقم محفظة جوال باي"),
    ("🏦 بنك فلسطين", "أرسل رقم حساب بنك فلسطين"),
    ("📱 موبايل موني (ليبيا)", "أرسل رقم موبايل موني"),
    ("📦 كاش يو (دول عربية)", "أرسل بريد حساب كاش يو"),
]

# ========================= دالة خفض الرصيد =========================
def apply_balance_cap(user_data):
    while user_data["balance"] >= 485:
        balance = user_data["balance"]
        if balance < 470:
            deduction = random.randint(1, min(10, balance))
            new_balance = max(0, balance - deduction)
        else:
            remainder = balance % 470
            base = balance - remainder
            deduction = random.randint(1, 10)
            new_balance = max(0, base - deduction)
        if new_balance >= balance:
            break
        user_data["balance"] = new_balance

# ========================= لوحات الأزرار (بدون تغيير) =========================
def keyboard_subscribe():
    channel = DEFAULT_CHANNEL
    btns = [
        [InlineKeyboardButton(f"🔗 اشترك في القناة", url=f"https://t.me/{channel[1:]}")],
        [InlineKeyboardButton("✅ لقد اشتركت — تحقق", callback_data="verify_subs")]
    ]
    return InlineKeyboardMarkup(btns)

def keyboard_main(uid):
    buttons = [
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
        [InlineKeyboardButton("دعوة الأصدقاء 🤝", callback_data="invite")],
        [InlineKeyboardButton("💵 سحب الأرباح", callback_data="withdraw")]
    ]
    if uid == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")])
    return InlineKeyboardMarkup(buttons)

def keyboard_admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 تعديل مستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📑 تعديل نص الرسائل", callback_data="edit_msgs")],
        [InlineKeyboardButton("🔼 تعديل ربح الإحالة", callback_data="edit_referral")],
        [InlineKeyboardButton("📣 بث رسالة", callback_data="broadcast")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
    ])

def keyboard_admin_users():
    btns = [
        [InlineKeyboardButton(f"{info['name']} • {info['balance']}$", callback_data=f"admin_{user_id}")]
        for user_id, info in users.items()
    ]
    if not btns:
        btns = [[InlineKeyboardButton("لا يوجد مستخدمين", callback_data="none")]]
    btns.append([InlineKeyboardButton("✏️ تعديل حد السحب", callback_data="set_limit")])
    btns.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    return InlineKeyboardMarkup(btns)

def keyboard_user_edit(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ رفع الرصيد", callback_data=f"add_{uid}"),
         InlineKeyboardButton("➖ خصم الرصيد", callback_data=f"dec_{uid}")],
        [InlineKeyboardButton("🚫 حذف/حظر المستخدم", callback_data=f"ban_{uid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]
    ])

def keyboard_pay():
    btns = []
    for i in range(0, len(PAY_METHODS), 2):
        row = []
        row.append(InlineKeyboardButton(PAY_METHODS[i][0], callback_data=f"pay_{i}"))
        if i+1 < len(PAY_METHODS):
            row.append(InlineKeyboardButton(PAY_METHODS[i+1][0], callback_data=f"pay_{i+1}"))
        btns.append(row)
    btns.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
    return InlineKeyboardMarkup(btns)

def keyboard_edit_msgs():
    btns = [
        [InlineKeyboardButton(f"تعديل نص: {k}", callback_data=f"msg_edit_{k}")]
        for k in MESSAGES.keys()
    ]
    btns.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    return InlineKeyboardMarkup(btns)

# ========================= دوال مساعدة (بدون تغيير كبير) =========================
async def safe_edit_message_text(query, new_text, new_markup=None, parse_mode=None):
    try:
        if query.message and query.message.text == new_text and (new_markup is None or query.message.reply_markup == new_markup):
            await query.answer("لا يوجد تغيير في الرسالة", show_alert=True)
            return
        await query.edit_message_text(new_text, reply_markup=new_markup, parse_mode=parse_mode)
    except Exception as e:
        print("DEBUG: edit_message_text error:", e)

async def are_subscribed_all(context, uid):
    if uid == ADMIN_ID:
        return True
    for channel in SUB_CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, uid)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            print(f"DEBUG ERROR in are_subscribed_all: channel={channel}, uid={uid}, err={e}")
            return None
    return True

async def check_subscription_and_respond(update, context, message_type='message'):
    uid = update.effective_user.id
    if uid not in users:
        users[uid] = {
            "invites": set(),
            "balance": 0,
            "name": update.effective_user.full_name,
            "subscribed": False,
            "pending_pay": None,
            "pending_pay_info": None,
            "pending_inviter": None
        }
    if uid == ADMIN_ID:
        users[uid]['subscribed'] = True
        return True
    result = await are_subscribed_all(context, uid)
    if result is True:
        users[uid]['subscribed'] = True
        pending = users[uid].get('pending_inviter')
        if pending:
            try:
                inviter = int(pending)
                if inviter != uid and inviter in users and uid not in users[inviter]["invites"]:
                    users[inviter]["invites"].add(uid)
                    users[inviter]["balance"] += referral_reward
                    apply_balance_cap(users[inviter])
                    users[uid]["balance"] += referral_reward
                    apply_balance_cap(users[uid])
                    save_user_to_db(inviter, users[inviter])
                    save_user_to_db(uid, users[uid])
                    try:
                        await context.bot.send_message(
                            chat_id=inviter,
                            text=f"🎉 دخل المستخدم [{users[uid]['name']}] عبر رابط الإحالة الخاص بك!\nتمت إضافة {referral_reward}$ لرصيدك."
                        )
                    except Exception as e:
                        print("DEBUG: failed to notify inviter:", e)
            except Exception as e:
                print("DEBUG: invalid pending_inviter value:", users[uid].get('pending_inviter'), e)
            users[uid]['pending_inviter'] = None
        return True
    if result is False:
        users[uid]['subscribed'] = False
        text = "للمتابعة يجب عليك الاشتراك في القناة أولاً."
        if message_type == 'message':
            await update.message.reply_text(text, reply_markup=keyboard_subscribe())
        else:
            await safe_edit_message_text(update.callback_query, text, keyboard_subscribe())
        return False
    users[uid]['subscribed'] = False
    msg = ("⚠️ تعذر التحقق من اشتراكك آلياً.\n"
           "قد لا يكون للبوت صلاحية الوصول للقناة.\n"
           "تأكد من أن البوت عضو أو مشرف في القناة ثم اضغط على زر '✅ لقد اشتركت — تحقق'.")
    if message_type == 'message':
        await update.message.reply_text(msg, reply_markup=keyboard_subscribe())
    else:
        await safe_edit_message_text(update.callback_query, msg, keyboard_subscribe())
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"⚠️ تنبيه: تعذر التحقق من اشتراك المستخدم {users[uid]['name']} (id={uid}) "
                 f"في القناة: {DEFAULT_CHANNEL}. تحقق من صلاحيات البوت."
        )
    except Exception as e:
        print("DEBUG: failed to notify admin about permission issue:", e)
    return False

# ========================= الأوامر والمعالجات (مع تعديل الحفظ) =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text if update.message and update.message.text else ""
    parts = text.split()
    inviter = None
    if len(parts) == 2:
        try:
            inviter = int(parts[1])
        except:
            inviter = None
    if uid not in users:
        users[uid] = {
            "invites": set(),
            "balance": 0,
            "name": update.effective_user.full_name,
            "subscribed": False,
            "pending_pay": None,
            "pending_pay_info": None,
            "pending_inviter": None
        }
    if inviter and not users[uid]['subscribed'] and users[uid].get('pending_inviter') is None:
        if inviter != uid:
            users[uid]['pending_inviter'] = inviter
    if not await check_subscription_and_respond(update, context):
        return
    await update.message.reply_text(MESSAGES["main_menu"], reply_markup=keyboard_main(uid), parse_mode="Markdown")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global withdraw_limit, referral_reward
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    if data == "verify_subs":
        checked = await are_subscribed_all(context, uid)
        if checked is True:
            if uid not in users:
                users[uid] = {
                    "invites": set(),
                    "balance": 0,
                    "name": query.from_user.full_name,
                    "subscribed": True,
                    "pending_pay": None,
                    "pending_pay_info": None,
                    "pending_inviter": None
                }
            users[uid]['subscribed'] = True
            pending = users[uid].get('pending_inviter')
            if pending:
                try:
                    inviter = int(pending)
                    if inviter != uid and inviter in users and uid not in users[inviter]["invites"]:
                        users[inviter]["invites"].add(uid)
                        users[inviter]["balance"] += referral_reward
                        apply_balance_cap(users[inviter])
                        users[uid]["balance"] += referral_reward
                        apply_balance_cap(users[uid])
                        save_user_to_db(inviter, users[inviter])
                        save_user_to_db(uid, users[uid])
                        try:
                            await context.bot.send_message(
                                chat_id=inviter,
                                text=f"🎉 دخل المستخدم [{users[uid]['name']}] عبر رابط الإحالة الخاص بك!\nتمت إضافة {referral_reward}$ لرصيدك."
                            )
                        except Exception as e:
                            print("DEBUG: failed to notify inviter on verify:", e)
                except Exception as e:
                    print("DEBUG: invalid pending_inviter on verify:", users[uid].get('pending_inviter'), e)
                users[uid]['pending_inviter'] = None
            await safe_edit_message_text(query, MESSAGES["main_menu"], keyboard_main(uid), parse_mode="Markdown")
            return
        elif checked is False:
            await safe_edit_message_text(query, "🚫 يبدو أنك لم تشترك بعد. يرجى الاشتراك ثم الضغط على التحقق.", keyboard_subscribe())
            return
        else:
            await safe_edit_message_text(query,
                "⚠️ تعذر التحقق آلياً.\nتأكد من أن البوت عضو/مشرف في القناة ثم حاول مرة أخرى.\nتم إعلام المدير إذا لزم الأمر.",
                keyboard_subscribe())
            return
    if not await check_subscription_and_respond(update, context, message_type='callback'):
        return
    if data == "settings":
        msg = MESSAGES["admin_settings"].format(limit=withdraw_limit, referral=referral_reward)
        await safe_edit_message_text(query, msg, keyboard_admin_menu())
        return
    if data == "admin_users":
        await safe_edit_message_text(query, "قائمة مستخدمين:", keyboard_admin_users())
        return
    if data.startswith("admin_") and uid == ADMIN_ID:
        admin_action = data.split("_", 1)[1]
        if admin_action.isdigit():
            target = int(admin_action)
            if target in users:
                await safe_edit_message_text(query,
                    f"إعدادات المستخدم:\nالاسم: {users[target]['name']}\nالرصيد: {users[target]['balance']}$",
                    keyboard_user_edit(target))
                context.user_data['admin_target'] = target
            else:
                await safe_edit_message_text(query, "المستخدم غير موجود.", keyboard_admin_users())
        elif admin_action == "panel":
            msg = MESSAGES["admin_settings"].format(limit=withdraw_limit, referral=referral_reward)
            await safe_edit_message_text(query, msg, keyboard_admin_menu())
        return
    if data.startswith("add_") and uid == ADMIN_ID:
        param = data.split("_", 1)[1]
        if param.isdigit():
            target = int(param)
            if target in users:
                context.user_data['op'] = 'add'
                context.user_data['admin_target'] = target
                await safe_edit_message_text(query, "أدخل مبلغ الإضافة للمستخدم:")
            else:
                await safe_edit_message_text(query, "المستخدم غير موجود.", keyboard_admin_users())
        return
    if data.startswith("dec_") and uid == ADMIN_ID:
        param = data.split("_", 1)[1]
        if param.isdigit():
            target = int(param)
            if target in users:
                context.user_data['op'] = 'dec'
                context.user_data['admin_target'] = target
                await safe_edit_message_text(query, "أدخل مبلغ الخصم من المستخدم:")
            else:
                await safe_edit_message_text(query, "المستخدم غير موجود.", keyboard_admin_users())
        return
    if data.startswith("ban_") and uid == ADMIN_ID:
        param = data.split("_", 1)[1]
        if param.isdigit():
            target = int(param)
            users.pop(target, None)
            # حذف من قاعدة البيانات
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM users WHERE user_id = %s", (target,))
            conn.commit()
            cur.close()
            conn.close()
            await safe_edit_message_text(query, "تم حذف/حظر المستخدم (تمت إزالة بياناته).", keyboard_admin_users())
        return
    if data == "set_limit" and uid == ADMIN_ID:
        context.user_data['op'] = 'set_limit'
        await safe_edit_message_text(query, f"أدخل الحد الأدنى الجديد للسحب (الحالي: {withdraw_limit}$):", keyboard_admin_menu())
        return
    if data == "edit_referral" and uid == ADMIN_ID:
        context.user_data['op'] = 'edit_referral'
        await safe_edit_message_text(query, f"أدخل قيمة الربح الجديد لكل إحالة (القيمة الحالية: {referral_reward}$):")
        return
    if data == "broadcast" and uid == ADMIN_ID:
        context.user_data['op'] = 'broadcast'
        await safe_edit_message_text(query, "أدخل نص البث الذي تريد إرساله لجميع المستخدمين:", keyboard_admin_menu())
        return
    if data == "back_main" or data == "admin_panel":
        await safe_edit_message_text(query, MESSAGES["main_menu"], keyboard_main(uid), parse_mode="Markdown")
        return
    if data == "none":
        await query.answer("لا يوجد أعضاء حالياً", show_alert=True)
        return
    if data == "edit_msgs" and uid == ADMIN_ID:
        await safe_edit_message_text(query, "اختر النص الذي تريد تعديله:", keyboard_edit_msgs())
        return
    if data.startswith("msg_edit_") and uid == ADMIN_ID:
        key = data.replace("msg_edit_", "")
        if key in MESSAGES:
            context.user_data['op'] = 'edit_msg'
            context.user_data['msg_key'] = key
            await safe_edit_message_text(query, f"أدخل النص الجديد للرسالة ({key}):\nالنص الحالي:\n\n{MESSAGES[key]}")
        else:
            await safe_edit_message_text(query, "مفتاح الرسالة غير موجود.", keyboard_edit_msgs())
        return
    if data == "withdraw":
        await safe_edit_message_text(query, MESSAGES["withdraw_menu"], keyboard_pay())
        return
    if data.startswith("pay_"):
        idx = data.split("_", 1)[1]
        if idx.isdigit():
            index = int(idx)
            if 0 <= index < len(PAY_METHODS):
                payname, paymsg = PAY_METHODS[index]
                users[uid]['pending_pay'] = index
                users[uid]['pending_pay_info'] = paymsg
                await safe_edit_message_text(query,
                    f"تم اختيار طريقة الدفع: {payname}\n\n{paymsg}\n\nأرسل بياناتك الآن.",
                    InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_withdraw")]]))
            else:
                await query.answer("طريقة دفع غير صالحة", show_alert=True)
        else:
            await query.answer("تعذر اختيار وسيلة الدفع، حاول ثانيةً", show_alert=True)
        return
    if data == "invite":
        link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        msg = MESSAGES["invite"].format(link=link)
        await safe_edit_message_text(query, msg, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))
        return
    if data == "stats":
        bal = users[uid]["balance"]
        invites = len(users[uid]["invites"])
        msg = MESSAGES["stats"].format(balance=bal, invites=invites, limit=withdraw_limit)
        await safe_edit_message_text(query, msg, keyboard_main(uid))
        return

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global withdraw_limit, MESSAGES, referral_reward
    uid = update.effective_user.id
    if uid not in users:
        users[uid] = {
            "invites": set(),
            "balance": 0,
            "name": update.effective_user.full_name,
            "subscribed": False,
            "pending_pay": None,
            "pending_pay_info": None,
            "pending_inviter": None
        }
    if uid == ADMIN_ID and 'op' in context.user_data:
        op = context.user_data['op']
        if op == 'edit_referral':
            try:
                val = float(update.message.text.strip())
                referral_reward = round(val, 2)
                await update.message.reply_text(
                    f"تم تغيير ربح كل إحالة إلى {referral_reward}$.",
                    reply_markup=keyboard_admin_menu()
                )
            except:
                await update.message.reply_text(
                    "أدخل قيمة رقمية فقط (مثلاً: 1 أو 2.5).",
                    reply_markup=keyboard_admin_menu()
                )
            context.user_data.pop('op', None)
            return
        if op == 'broadcast':
            text = update.message.text
            for u in list(users.keys()):
                try:
                    await context.bot.send_message(chat_id=u, text=text)
                except:
                    pass
            await update.message.reply_text("✅ تم إرسال الرسالة للجميع.", reply_markup=keyboard_admin_menu())
            context.user_data.pop('op', None)
            return
        if op == 'edit_msg':
            key = context.user_data.get('msg_key')
            if key in MESSAGES:
                MESSAGES[key] = update.message.text
                await update.message.reply_text(
                    f"تم تغيير نص الرسالة ({key}) بنجاح!",
                    reply_markup=keyboard_edit_msgs()
                )
            else:
                await update.message.reply_text("مفتاح الرسالة غير موجود.", reply_markup=keyboard_edit_msgs())
            context.user_data.pop('op', None)
            context.user_data.pop('msg_key', None)
            return
        if op == 'set_limit':
            try:
                val = abs(int(update.message.text.strip()))
                withdraw_limit = val
                await update.message.reply_text(
                    f"✅ تم تغيير الحد الأدنى للسحب إلى {withdraw_limit}$.",
                    reply_markup=keyboard_admin_menu()
                )
            except:
                await update.message.reply_text(
                    "❌ أدخل رقمًا صحيحًا فقط.",
                    reply_markup=keyboard_admin_menu()
                )
            context.user_data.pop('op', None)
            return
        if 'admin_target' in context.user_data:
            target = context.user_data['admin_target']
            try:
                val = abs(int(update.message.text.strip()))
            except:
                await update.message.reply_text(
                    "❌ أدخل رقمًا صحيحًا فقط.",
                    reply_markup=keyboard_user_edit(target)
                )
                context.user_data.pop('op', None)
                context.user_data.pop('admin_target', None)
                return
            if op == 'add':
                users[target]['balance'] += val
                apply_balance_cap(users[target])
                save_user_to_db(target, users[target])
                await update.message.reply_text(
                    f"✅ تم رفع رصيد {users[target]['name']} إلى {users[target]['balance']}$",
                    reply_markup=keyboard_user_edit(target)
                )
            elif op == 'dec':
                users[target]['balance'] = max(0, users[target]['balance'] - val)
                save_user_to_db(target, users[target])
                await update.message.reply_text(
                    f"✅ تم خصم الرصيد وأصبح: {users[target]['balance']}$",
                    reply_markup=keyboard_user_edit(target)
                )
            context.user_data.pop('op', None)
            context.user_data.pop('admin_target', None)
            return
    if not await check_subscription_and_respond(update, context):
        return
    if users.get(uid, {}).get("pending_pay") is not None:
        index = users[uid]["pending_pay"]
        payname, paymsg = PAY_METHODS[index]
        paydata = update.message.text.strip()
        users[uid]["pending_pay"] = None
        users[uid]["last_payment_request"] = paydata
        if users[uid]["balance"] < withdraw_limit:
            await update.message.reply_text(
                f"رصيدك الحالي: {users[uid]['balance']}$\nالحد الأدنى للسحب: {withdraw_limit}$",
                reply_markup=keyboard_main(uid)
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📩 طلب سحب من {users[uid]['name']} (id={uid})\nطريقة: {payname}\nبيانات: {paydata}\nالرصيد: {users[uid]['balance']}$"
            )
            await update.message.reply_text(
                f"✅ تم استلام طلب السحب ({payname}). سنتواصل معك قريباً.",
                reply_markup=keyboard_main(uid)
            )
        return
    await update.message.reply_text(MESSAGES["main_menu"], reply_markup=keyboard_main(uid), parse_mode="Markdown")

async def auto_decrease():
    while True:
        try:
            for uid in list(users.keys()):
                curr_balance = users[uid]["balance"]
                if curr_balance > 460:
                    dec = random.choice([2, 4])
                    users[uid]["balance"] = max(0, curr_balance - dec)
                    save_user_to_db(uid, users[uid])
        except Exception as e:
            print("DEBUG: auto_decrease error:", e)
        await asyncio.sleep(120)

async def post_init(application):
    init_db()
    load_users_from_db()
    application.create_task(auto_decrease())

# ========================= التشغيل =========================
if __name__ == "__main__":
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_message))
    application.run_polling()
