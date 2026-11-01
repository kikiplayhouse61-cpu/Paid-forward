import os
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, String, Integer, BigInteger, Boolean, DateTime, Text, ForeignKey, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.environ.get("ADMIN_ID", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
UPI_DEFAULT = os.environ.get("UPI_ID", "tosifbhati065@okaxis").strip()
TZ = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Kolkata"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")
if not ADMIN_ID_RAW.isdigit():
    raise RuntimeError("ADMIN_ID must be your numeric Telegram user ID")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required. Attach PostgreSQL on Railway.")

ADMIN_ID = int(ADMIN_ID_RAW)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
DB = sessionmaker(bind=engine, expire_on_commit=False)

PLANS = {7: 49, 15: 89, 30: 149}
MAX_GROUPS = 20
INTERVAL_SECONDS = 20 * 60
DAILY_CAP = 1300

class Base(DeclarativeBase): pass

class Customer(Base):
    __tablename__ = "customers"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    full_name: Mapped[str] = mapped_column(String(255), default="")
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    sub_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Destination(Base):
    __tablename__ = "destinations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    plan_days: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    utr: Mapped[str] = mapped_column(String(100), unique=True)
    screenshot_file_id: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

class SendLog(Base):
    __tablename__ = "send_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

Base.metadata.create_all(engine)

def setting(key, default=""):
    with DB() as s:
        row = s.get(Setting, key)
        return row.value if row else default

def set_setting(key, value):
    with DB() as s:
        row = s.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=value)
            s.add(row)
        else:
            row.value = value
        s.commit()

def customer_from_update(update):
    u = update.effective_user
    with DB() as s:
        c = s.get(Customer, u.id)
        if c is None:
            c = Customer(user_id=u.id)
            s.add(c)
        c.username = u.username or ""
        c.full_name = u.full_name or ""
        s.commit()
        return c

def is_admin(update):
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)

def active_customer(user_id):
    with DB() as s:
        c = s.get(Customer, user_id)
        return bool(c and not c.blocked and c.sub_until and c.sub_until > datetime.now(timezone.utc))

def customer_allowed(user_id):
    with DB() as s:
        c = s.get(Customer, user_id)
        return bool(c and not c.blocked and c.sub_until and c.sub_until > datetime.now(timezone.utc))

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Buy Subscription", callback_data="plans")],
        [InlineKeyboardButton("📊 My Dashboard", callback_data="dashboard"),
         InlineKeyboardButton("💳 Payment Status", callback_data="paystatus")],
        [InlineKeyboardButton("👥 My Groups", callback_data="groups")],
        [InlineKeyboardButton("📈 My Usage", callback_data="usage")],
        [InlineKeyboardButton("🆘 Help & Support", callback_data="help")],
        [InlineKeyboardButton("🎥 Video / How to Use", callback_data="tutorial")]
    ])

def plan_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("7 Days — ₹49", callback_data="plan:7")],
        [InlineKeyboardButton("15 Days — ₹89", callback_data="plan:15")],
        [InlineKeyboardButton("30 Days — ₹149", callback_data="plan:30")],
        [InlineKeyboardButton("⬅ Back", callback_data="home")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏳ Pending Payments", callback_data="admin:pending")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin:stats")],
        [InlineKeyboardButton("🖼 Change UPI QR", callback_data="admin:qr")],
        [InlineKeyboardButton("🎬 Change Example Video", callback_data="admin:video")],
        [InlineKeyboardButton("💳 Change UPI ID", callback_data="admin:upi")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer_from_update(update)
    await update.message.reply_text(
        "Welcome to Telegram Board.\nChoose an option below.",
        reply_markup=main_menu()
    )

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text("Owner Admin Board", reply_markup=admin_keyboard())

async def setupi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not context.args:
        await update.message.reply_text("Usage: /setupi your@upi")
        return
    set_setting("upi_id", context.args[0].strip())
    await update.message.reply_text("UPI ID updated.")

async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    await show_pending(update.effective_chat.id, context)

async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update) or not context.args or not context.args[0].isdigit(): return
    with DB() as s:
        c = s.get(Customer, int(context.args[0]))
        if c: c.blocked = True; s.commit()
    await update.message.reply_text("Customer blocked in this service.")

async def unblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update) or not context.args or not context.args[0].isdigit(): return
    with DB() as s:
        c = s.get(Customer, int(context.args[0]))
        if c: c.blocked = False; s.commit()
    await update.message.reply_text("Customer unblocked in this service.")

async def extend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update) or len(context.args) != 2: return
    if not context.args[0].isdigit() or not context.args[1].isdigit(): return
    uid, days = int(context.args[0]), int(context.args[1])
    with DB() as s:
        c = s.get(Customer, uid)
        if not c:
            await update.message.reply_text("Customer not found.")
            return
        now = datetime.now(timezone.utc)
        base = c.sub_until if c.sub_until and c.sub_until > now else now
        c.sub_until = base + timedelta(days=days)
        s.commit()
    await update.message.reply_text(f"Extended customer {uid} by {days} days.")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    with DB() as s:
        customers = s.scalar(select(func.count()).select_from(Customer)) or 0
        pending = s.scalar(select(func.count()).select_from(Payment).where(Payment.status == "pending")) or 0
        active = s.scalar(select(func.count()).select_from(Customer).where(Customer.sub_until > datetime.now(timezone.utc), Customer.blocked == False)) or 0
    await update.message.reply_text(f"Customers: {customers}\nActive: {active}\nPending payments: {pending}")

async def show_pending(chat_id, context):
    with DB() as s:
        rows = s.scalars(select(Payment).where(Payment.status == "pending").order_by(Payment.created_at.asc()).limit(20)).all()
        items = [(p.id, p.user_id, p.plan_days, p.amount, p.utr, p.screenshot_file_id) for p in rows]
    if not items:
        await context.bot.send_message(chat_id, "No pending payments.")
        return
    for pid, uid, days, amount, utr, photo in items:
        text = f"Payment #{pid}\nCustomer: {uid}\nPlan: {days} days\nAmount: ₹{amount}\nUTR: {utr}\nVerify in your UPI/bank app before approving."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{pid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{pid}")
        ]])
        if photo:
            await context.bot.send_photo(chat_id, photo, caption=text, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id, text, reply_markup=kb)

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    customer_from_update(update)
    data = q.data

    if data == "home":
        await q.edit_message_text("Main Menu", reply_markup=main_menu())
    elif data == "plans":
        await q.edit_message_text("Choose a plan. You can watch the free example before paying.", reply_markup=plan_keyboard())
    elif data.startswith("plan:"):
        days = int(data.split(":")[1])
        if days not in PLANS: return
        context.user_data["selected_plan"] = days
        vid = setting("example_video", "")
        if vid:
            await context.bot.send_video(uid, vid, caption=f"Free example for the {days}-day plan. Watch before deciding.")
        await q.message.reply_text(
            f"Plan: {days} days — ₹{PLANS[days]}\nThe example video above is free. Continue only if you want to subscribe.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Continue to Payment", callback_data=f"pay:{days}")],
                [InlineKeyboardButton("Choose Another Plan", callback_data="plans")]
            ])
        )
    elif data.startswith("pay:"):
        days = int(data.split(":")[1])
        if days not in PLANS: return
        upi = setting("upi_id", UPI_DEFAULT)
        qr = setting("qr_file_id", "")
        if qr:
            await context.bot.send_photo(uid, qr, caption=f"Pay ₹{PLANS[days]} to {upi}\nAfter payment, send your UTR/reference number here.")
        await q.message.reply_text(
            f"Payment details\nPlan: {days} days\nAmount: ₹{PLANS[days]}\nUPI ID: {upi}\n\nSend your UTR/reference number as a message. Then send the payment screenshot.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="home")]])
        )
        context.user_data["payment_plan"] = days
        context.user_data["awaiting_utr"] = True
    elif data == "dashboard":
        with DB() as s:
            c = s.get(Customer, uid)
            until = c.sub_until.astimezone(TZ).strftime("%d-%m-%Y %H:%M") if c and c.sub_until else "Not active"
            blocked = c.blocked if c else False
        await q.edit_message_text(f"Subscription: {until}\nService blocked: {'Yes' if blocked else 'No'}", reply_markup=main_menu())
    elif data == "paystatus":
        with DB() as s:
            rows = s.scalars(select(Payment).where(Payment.user_id == uid).order_by(Payment.created_at.desc()).limit(5)).all()
            out = "\n".join([f"#{p.id}: ₹{p.amount} — {p.status}" for p in rows]) or "No payment requests yet."
        await q.edit_message_text(out, reply_markup=main_menu())
    elif data == "groups":
        with DB() as s:
            rows = s.scalars(select(Destination).where(Destination.user_id == uid, Destination.enabled == True)).all()
            out = "\n".join([f"{d.title or d.chat_id} ({d.chat_id})" for d in rows]) or "No groups saved."
        await q.edit_message_text(out + "\n\nTo add a group: add this bot as an admin there, then forward a message from that group to me, or send its numeric chat ID.", reply_markup=main_menu())
    elif data == "usage":
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        with DB() as s:
            count = s.scalar(select(func.count()).select_from(SendLog).where(SendLog.user_id == uid, SendLog.sent_at >= since)) or 0
        await q.edit_message_text(f"Successful sends in rolling 24 hours: {count}/{DAILY_CAP}\nFixed interval: 20 minutes", reply_markup=main_menu())
    elif data == "help":
        await q.edit_message_text("For support, contact the service administrator.", reply_markup=main_menu())
    elif data == "tutorial":
        vid = setting("example_video", "")
        if vid:
            await context.bot.send_video(uid, vid, caption="Free example / how to use")
        else:
            await q.message.reply_text("Tutorial video has not been uploaded yet.")
    elif data.startswith("admin:"):
        if uid != ADMIN_ID: return
        action = data.split(":")[1]
        if action == "pending":
            await show_pending(uid, context)
        elif action == "stats":
            await stats_cmd(update, context)
        elif action == "qr":
            context.user_data["admin_upload"] = "qr"
            await q.message.reply_text("Now send the new QR image as a photo.")
        elif action == "video":
            context.user_data["admin_upload"] = "video"
            await q.message.reply_text("Now send the new example video.")
        elif action == "upi":
            context.user_data["admin_upload"] = "upi"
            await q.message.reply_text("Now send the new UPI ID as text.")
    elif data.startswith(("approve:", "reject:")):
        if uid != ADMIN_ID: return
        action, pid_s = data.split(":")
        pid = int(pid_s)
        with DB() as s:
            p = s.get(Payment, pid)
            if not p or p.status != "pending":
                await q.message.reply_text("Request is no longer pending.")
                return
            p.status = "approved" if action == "approve" else "rejected"
            p.reviewed_at = datetime.now(timezone.utc)
            if action == "approve":
                c = s.get(Customer, p.user_id)
                now = datetime.now(timezone.utc)
                base = c.sub_until if c.sub_until and c.sub_until > now else now
                c.sub_until = base + timedelta(days=p.plan_days)
            target = p.user_id
            s.commit()
        await context.bot.send_message(target, "Payment approved. Your subscription is active." if action == "approve" else "Payment request rejected. Please contact support if you think this is an error.")
        await q.edit_message_caption((q.message.caption or "") + f"\n\nStatus: {action}")

async def text_and_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    customer_from_update(update)

    if uid == ADMIN_ID and context.user_data.get("admin_upload"):
        mode = context.user_data.pop("admin_upload")
        if mode == "qr" and update.message.photo:
            set_setting("qr_file_id", update.message.photo[-1].file_id)
            await update.message.reply_text("UPI QR updated.")
        elif mode == "video" and update.message.video:
            set_setting("example_video", update.message.video.file_id)
            await update.message.reply_text("Example video updated.")
        elif mode == "upi" and update.message.text:
            set_setting("upi_id", update.message.text.strip())
            await update.message.reply_text("UPI ID updated.")
        else:
            await update.message.reply_text("Wrong format. Try again using /admin.")
        return

    if context.user_data.get("awaiting_utr") and update.message.text:
        utr = update.message.text.strip()
        if len(utr) < 6 or len(utr) > 100:
            await update.message.reply_text("Please send a valid UTR/reference number.")
            return
        context.user_data["pending_utr"] = utr
        context.user_data["awaiting_utr"] = False
        context.user_data["awaiting_screenshot"] = True
        await update.message.reply_text("UTR received. Now send the payment screenshot. Admin will manually verify it; please allow up to 15 minutes.")
        return

    if context.user_data.get("awaiting_screenshot") and update.message.photo:
        days = context.user_data.get("payment_plan")
        utr = context.user_data.get("pending_utr")
        if days not in PLANS or not utr:
            await update.message.reply_text("Payment flow expired. Start again with /start.")
            return
        with DB() as s:
            existing = s.scalar(select(Payment).where(Payment.utr == utr))
            if existing:
                await update.message.reply_text("This UTR has already been submitted. Contact support if this is your payment.")
                return
            p = Payment(user_id=uid, plan_days=days, amount=PLANS[days], utr=utr,
                        screenshot_file_id=update.message.photo[-1].file_id)
            s.add(p)
            s.commit()
            pid = p.id
        context.user_data.pop("awaiting_screenshot", None)
        context.user_data.pop("pending_utr", None)
        context.user_data.pop("payment_plan", None)
        await update.message.reply_text("Payment request submitted. Please allow up to 15 minutes for admin verification.")
        await context.bot.send_message(ADMIN_ID, f"New payment request #{pid}\nCustomer: {uid}\nUTR: {utr}\nAmount: ₹{PLANS[days]}\nUse /pending to review.")
        return

    # Register a group/channel chat ID only if the bot can access it.
    if update.message.forward_origin:
        origin = update.message.forward_origin
        chat = getattr(origin, "chat", None)
        if chat:
            await add_destination(update, context, chat.id, getattr(chat, "title", "") or str(chat.id))
            return
    if update.message.text and update.message.text.lstrip("-").isdigit():
        chat_id = int(update.message.text)
        try:
            chat = await context.bot.get_chat(chat_id)
            me = await context.bot.get_me()
            member = await context.bot.get_chat_member(chat_id, me.id)
            if member.status not in ("administrator", "creator"):
                await update.message.reply_text("The bot must be an administrator in that group/channel first.")
                return
            await add_destination(update, context, chat_id, getattr(chat, "title", "") or str(chat_id))
        except Exception:
            await update.message.reply_text("I cannot access this chat. Add the bot as admin and check the chat ID.")
        return

async def add_destination(update, context, chat_id, title):
    uid = update.effective_user.id
    try:
        me = await context.bot.get_me()
        member = await context.bot.get_chat_member(chat_id, me.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("Bot admin permission is required.")
            return
    except Exception:
        await update.message.reply_text("Bot cannot verify admin permission in that destination.")
        return
    with DB() as s:
        count = s.scalar(select(func.count()).select_from(Destination).where(Destination.user_id == uid, Destination.enabled == True)) or 0
        exists = s.scalar(select(Destination).where(Destination.user_id == uid, Destination.chat_id == chat_id))
        if exists:
            await update.message.reply_text("This destination is already registered.")
            return
        if count >= MAX_GROUPS:
            await update.message.reply_text(f"Maximum {MAX_GROUPS} destinations reached.")
            return
        s.add(Destination(user_id=uid, chat_id=chat_id, title=title))
        s.commit()
    await update.message.reply_text(f"Destination added: {title}")

async def scheduler(app: Application):
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        now = datetime.now(timezone.utc)
        with DB() as s:
            customers = s.scalars(select(Customer).where(Customer.blocked == False, Customer.sub_until > now)).all()
            customer_ids = [c.user_id for c in customers]
        for uid in customer_ids:
            since = now - timedelta(hours=24)
            with DB() as s:
                count = s.scalar(select(func.count()).select_from(SendLog).where(SendLog.user_id == uid, SendLog.sent_at >= since)) or 0
                destinations = s.scalars(select(Destination).where(Destination.user_id == uid, Destination.enabled == True)).all()
                dests = [(d.chat_id, d.title) for d in destinations]
            if count >= DAILY_CAP or not dests:
                continue
            # The customer must set a message using /setmessage. Stored as per-customer DB setting.
            msg = setting(f"message:{uid}", "")
            if not msg:
                continue
            for chat_id, title in dests:
                since = datetime.now(timezone.utc) - timedelta(hours=24)
                with DB() as s:
                    used = s.scalar(select(func.count()).select_from(SendLog).where(SendLog.user_id == uid, SendLog.sent_at >= since)) or 0
                if used >= DAILY_CAP: break
                try:
                    await app.bot.send_message(chat_id=chat_id, text=msg)
                    with DB() as s:
                        s.add(SendLog(user_id=uid, sent_at=datetime.now(timezone.utc)))
                        s.commit()
                except Exception:
                    # Permission failures and Telegram rate limits are not bypassed.
                    continue

async def setmessage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not customer_allowed(uid):
        await update.message.reply_text("An active approved subscription is required.")
        return
    msg = update.message.text.partition(" ")[2].strip()
    if not msg:
        await update.message.reply_text("Usage: /setmessage Your message text")
        return
    set_setting(f"message:{uid}", msg[:4000])
    await update.message.reply_text("Message saved. Scheduler checks every 20 minutes.")

async def post_init(app: Application):
    app.create_task(scheduler(app))

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(CommandHandler("setupi", setupi_cmd))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("extend", extend_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("setmessage", setmessage_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, text_and_media))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
