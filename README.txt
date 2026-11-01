TELEGRAM BOARD — SUBSCRIPTION + ADMIN PAYMENT VERSION

IMPORTANT
- This version posts through the Telegram Bot API. The bot must be added as an administrator
  to each customer group/channel and granted permission to post.
- It does NOT log in to customers' personal Telegram accounts.
- Telegram rate limits and group permissions still apply. Never use this for unsolicited spam.
- Payment screenshots/UTRs are claims only. Admin must verify the transaction in their UPI app/bank.

FEATURES
- Plans: 7 days ₹49, 15 days ₹89, 30 days ₹149
- UPI ID: tosifbhati065@okaxis
- Customer submits UTR + payment screenshot; admin approves/rejects manually
- Admin can change UPI ID, upload/change QR and example video from the bot
- Free example video is shown BEFORE subscription payment on each plan
- Admin controls: pending payments, approve/reject, block/unblock, extend subscription
- Customer dashboard and subscription expiry checks
- Per-customer maximum 20 registered destinations
- Fixed 20-minute interval
- Rolling 24-hour cap of 1,300 successful sends per customer
- PostgreSQL persistence via DATABASE_URL (recommended on Railway)

DEPLOY (Railway)
1. Push these five files to a private GitHub repository.
2. Create a Railway project from the repository and add a PostgreSQL service.
3. Set variables:
   BOT_TOKEN       = BotFather token
   ADMIN_ID        = your numeric Telegram user ID
   DATABASE_URL    = Railway PostgreSQL connection string (Railway may provide postgres://;
                     this app normalizes it to postgresql://)
   UPI_ID          = tosifbhati065@okaxis (optional; default already set)
   APP_TIMEZONE    = Asia/Kolkata (optional)
4. Start command: python bot.py
5. Open your bot and send /start.
6. Add the bot as admin to each group/channel where posting is allowed.
7. In the admin bot chat, use /admin to manage QR, example video, UPI ID and payments.

ADMIN COMMANDS
/admin              Show admin menu
/setupi <upi-id>    Change UPI ID
/setqr              Then send a QR photo
/setvideo           Then send an example video
/pending            List pending payment requests
/block <user_id>    Block a customer
/unblock <user_id>  Unblock a customer
/extend <user_id> <days>  Extend an active subscription
/stats              Show customer/payment statistics

CUSTOMER FLOW
/start -> Buy Subscription -> choose plan -> Watch Example (free) or Continue to payment
-> submit UTR -> send screenshot -> admin manually verifies -> Approve/Reject.
The example video is shown before payment is requested.

DESTINATIONS
Customer adds a destination by forwarding a message from that group/channel to the bot,
or sending its numeric chat ID. The bot must already be an admin there. A customer may
register up to 20 destinations. A destination can be removed from My Groups.

SECURITY
- Set ADMIN_ID. Startup fails if missing.
- Keep BOT_TOKEN and DATABASE_URL private.
- QR and example video are stored as Telegram file_id values in the database.
- Do not paste payment screenshots or OTPs publicly.
- Back up the PostgreSQL database.
- This is a starter deployment; test with a private test group before taking payments.
