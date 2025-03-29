import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    MessageHandler, Filters, CallbackContext,
    ConversationHandler
)
import qrcode
from io import BytesIO
import sqlite3
from uuid import uuid4

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = "7834105383:AAFq7Lh_9dpjsfy9OAoMmfmLlrwaENSLQXU"
ADMIN_CHAT_ID = 5994179918  # Replace with your Telegram ID
UPI_ID = "BHARATPE09910247693@yesbankltd"  # Replace with your UPI ID
PAYMENT_AMOUNT = 100  # ₹100 for male users


# Database setup
def init_db():
    conn = sqlite3.connect('dating_bot.db')
    c = conn.cursor()

    # Users table with ON CONFLICT REPLACE for updates
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY ON CONFLICT REPLACE,
                  username TEXT,
                  gender TEXT,
                  name TEXT,
                  age INTEGER,
                  phone TEXT,
                  photo_id TEXT,
                  bio TEXT,
                  approved INTEGER DEFAULT 0,
                  paid INTEGER DEFAULT 0)''')

    # Payments table
    c.execute('''CREATE TABLE IF NOT EXISTS payments
                 (payment_id TEXT PRIMARY KEY,
                  user_id INTEGER,
                  amount INTEGER,
                  status TEXT DEFAULT 'pending',
                  screenshot_id TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')

    conn.commit()
    conn.close()


init_db()

# Conversation states
GENDER, MALE_PAYMENT, PHOTO, DETAILS, BIO = range(5)


# Start command
def start(update: Update, context: CallbackContext):
    # Clear any existing user data
    context.user_data.clear()

    description = (
        "✨ Welcome to the Dating Bot! ✨\n\n"
        "👋 This is a safe platform where girls can choose their match.\n"
        "⚠️ Fake payment screenshots will result in permanent ban.\n"
        "💖 Girls' data is 100% safe and will only be shared after mutual approval.\n\n"
        "Please select your gender:"
    )

    keyboard = [
        [InlineKeyboardButton("👨 Male", callback_data='male'),
         InlineKeyboardButton("👩 Female", callback_data='female')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='help'),
         InlineKeyboardButton("💳 Payment Info", callback_data='payment_info')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send new message instead of replying to existing one
    if update.message:
        update.message.reply_text(description, reply_markup=reply_markup)
    else:
        update.callback_query.message.reply_text(description, reply_markup=reply_markup)
    return GENDER


# Gender selection handler
def gender_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == 'help':
        help_command(update, context)
        return ConversationHandler.END
    elif query.data == 'payment_info':
        payment_info(update, context)
        return ConversationHandler.END

    context.user_data['gender'] = query.data

    if query.data == 'female':
        query.edit_message_text(
            "👩 You selected Female (FREE registration)\n\n"
            "Please send your photo for your profile:"
        )
        return PHOTO
    else:
        # Generate payment QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(f"upi://pay?pa={UPI_ID}&am={PAYMENT_AMOUNT}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to bytes
        bio = BytesIO()
        img.save(bio, format='PNG')
        bio.seek(0)

        # Send payment instructions
        context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=bio,
            caption=(
                f"👨 You selected Male (₹{PAYMENT_AMOUNT} registration fee)\n\n"
                f"Please pay ₹{PAYMENT_AMOUNT} to:\n"
                f"UPI ID: `{UPI_ID}`\n\n"
                "After payment, send the screenshot here."
            ),
            parse_mode='Markdown'
        )
        return MALE_PAYMENT


# Handle payment screenshot
def payment_handler(update: Update, context: CallbackContext):
    if 'gender' not in context.user_data or context.user_data['gender'] != 'male':
        update.message.reply_text("Please start the registration process first with /start")
        return

    # Save payment screenshot
    photo_file = update.message.photo[-1].get_file()
    payment_id = str(uuid4())

    conn = sqlite3.connect('dating_bot.db')
    c = conn.cursor()

    # Store payment info
    c.execute(
        "INSERT INTO payments (payment_id, user_id, amount, screenshot_id) VALUES (?, ?, ?, ?)",
        (payment_id, update.effective_user.id, PAYMENT_AMOUNT, photo_file.file_id)
    )

    conn.commit()
    conn.close()

    # Notify admin with user info
    user = update.effective_user
    context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"⚠️ Payment received from:\n"
             f"User ID: {user.id}\n"
             f"Username: @{user.username}\n"
             f"Name: {user.full_name}\n\n"
             f"Please verify payment with /verify_{payment_id}"
    )
    context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo_file.file_id,
        caption=f"Payment screenshot from {user.username or user.id}"
    )

    update.message.reply_text(
        "Payment received! Please send your photo for your profile:"
    )
    return PHOTO


# Handle profile photo
def photo_handler(update: Update, context: CallbackContext):
    photo_file = update.message.photo[-1].get_file()
    context.user_data['photo_id'] = photo_file.file_id

    update.message.reply_text(
        "Great! Now please send your details in this format:\n\n"
        "Name: Your Name\n"
        "Age: Your Age\n"
        "Phone: Your Number\n"
        "Location: Your City\n\n"
        "You can add any other details you'd like to share."
    )
    return DETAILS


# Handle user details
def details_handler(update: Update, context: CallbackContext):
    context.user_data['details'] = update.message.text

    update.message.reply_text(
        "Almost done! Please write a short bio about yourself (max 200 characters):"
    )
    return BIO


# Handle bio and complete registration
def bio_handler(update: Update, context: CallbackContext):
    bio = update.message.text
    if len(bio) > 200:
        update.message.reply_text("Bio is too long! Please keep it under 200 characters.")
        return BIO

    # Save all data to database
    user_id = update.effective_user.id
    username = update.effective_user.username
    gender = context.user_data['gender']
    photo_id = context.user_data['photo_id']
    details = context.user_data['details']

    # Parse details (simple implementation)
    details_dict = {}
    for line in details.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            details_dict[key.strip().lower()] = value.strip()

    name = details_dict.get('name', 'Not provided')
    age = details_dict.get('age', 'Not provided')
    phone = details_dict.get('phone', 'Not provided')
    location = details_dict.get('location', 'Not provided')

    conn = sqlite3.connect('dating_bot.db')
    c = conn.cursor()

    # Save user data with ON CONFLICT REPLACE
    c.execute(
        """INSERT OR REPLACE INTO users 
        (user_id, username, gender, name, age, phone, photo_id, bio, paid) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, username, gender, name, age, phone, photo_id, bio,
         (1 if gender == 'male' else 0))
    )

    conn.commit()
    conn.close()

    # Prepare admin notification with all details
    admin_message = (
        f"⚠️ New {'Male' if gender == 'male' else 'Female'} user registered:\n\n"
        f"User ID: {user_id}\n"
        f"Username: @{username}\n"
        f"Name: {name}\n"
        f"Age: {age}\n"
        f"Location: {location}\n"
        f"Phone: {phone}\n"
        f"Bio: {bio}\n\n"
    )

    if gender == 'male':
        admin_message += "Payment required before approval\n"
        admin_message += f"Approve with /approve_{user_id}"
    else:
        admin_message += "Auto-approved (female user)\n"
        admin_message += f"View profile with /view_{user_id}"

    # Send user photo and details to admin
    context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo_id,
        caption=admin_message
    )

    # Different responses for male/female
    if gender == 'female':
        # Auto-approve female users
        conn = sqlite3.connect('dating_bot.db')
        c = conn.cursor()
        c.execute(
            "UPDATE users SET approved = 1 WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        conn.close()

        update.message.reply_text(
            "🎉 Registration complete! 🎉\n\n"
            "Your profile has been approved. You can now:\n"
            "- Browse profiles with /profiles\n"
            "- Get help with /help"
        )
    else:
        update.message.reply_text(
            "🎉 Registration complete! 🎉\n\n"
            "Your profile and payment are under review.\n"
            "You'll receive a notification when approved.\n\n"
            "You can check your status with /status"
        )

    return ConversationHandler.END


# FIXED APPROVAL FUNCTION
def approve_profile(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("You are not authorized.")
        return

    try:
        user_id = int(context.args[0])
    except:
        update.message.reply_text("Use: /approve USER_ID")
        return

    conn = sqlite3.connect('dating_bot.db')
    c = conn.cursor()

    try:
        # 1. FIRST verify user exists and get current status
        c.execute("SELECT username, approved FROM users WHERE user_id=?", (user_id,))
        user = c.fetchone()

        if not user:
            update.message.reply_text("User not found!")
            return

        username, approved = user

        if approved:
            update.message.reply_text("Already approved!")
            return

        # 2. UPDATE with transaction
        c.execute("UPDATE users SET approved=1 WHERE user_id=?", (user_id,))
        conn.commit()

        # 3. VERIFY the update
        c.execute("SELECT approved FROM users WHERE user_id=?", (user_id,))
        if c.fetchone()[0] != 1:
            raise Exception("Update failed")

        # 4. NOTIFY user
        try:
            context.bot.send_message(
                chat_id=user_id,
                text="🎉 Your profile has been approved!\nUse /profiles to browse."
            )
            update.message.reply_text(f"Approved {username or user_id}")
        except Exception as e:
            logger.error(f"Failed to notify {user_id}: {e}")
            update.message.reply_text("Approved but failed to notify user")

    except Exception as e:
        logger.error(f"Approval error: {e}")
        update.message.reply_text("Approval failed!")
        conn.rollback()
    finally:
        conn.close()


# FIXED STATUS CHECK
def status_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    conn = sqlite3.connect('dating_bot.db')
    c = conn.cursor()

    try:
        c.execute("SELECT approved FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()

        if not result:
            update.message.reply_text("Complete registration first!")
            return

        approved = result[0]
        update.message.reply_text(
            "✅ Approved!" if approved
            else "⏳ Pending approval"
        )
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        update.message.reply_text("Error checking status")
    finally:
        conn.close()


        # Notify user - THIS WAS MISSING IN PREVIOUS VERSION
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 Congratulations {user_name}! 🎉\n\n"
                     "Your profile has been approved by admin.\n\n"
                     "You can now:\n"
                     "- Browse profiles with /profiles\n"
                     "- Find matches and connect with others!"
            )
            update.message.reply_text(f"User {username or user_id} has been approved and notified.")
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
            update.message.reply_text(
                f"User {username or user_id} approved but could not send notification. "
                "They may have blocked the bot."
            )

    # ... (rest of the code remains the same)


# View profiles command
def view_profiles(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    conn = sqlite3.connect('dating_bot.db')
    c = conn.cursor()

    # Check if user is approved
    c.execute(
        "SELECT gender, approved FROM users WHERE user_id = ?",
        (user_id,)
    )
    user = c.fetchone()

    if not user:
        update.message.reply_text("Please complete registration first with /start")
        conn.close()
        return

    gender, approved = user

    if not approved:
        update.message.reply_text("If you have completed the payment, your profile will be approved. If you have made a fake payment, it will keep showing as pending repeatedly. If your profile is not getting approved even after making the payment, message me at @Dating711.")
        conn.close()
        return

    # Get profiles to show (opposite gender)
    target_gender = 'female' if gender == 'male' else 'male'
    c.execute(
        "SELECT user_id, name, age, bio, photo_id FROM users WHERE gender = ? AND approved = 1",
        (target_gender,)
    )
    profiles = c.fetchall()
    conn.close()

    if not profiles:
        update.message.reply_text("No profiles available at the moment. Check back later!")
        return

    # Store profiles in context for pagination
    context.user_data['profiles'] = profiles
    context.user_data['current_profile'] = 0

    # Show first profile
    show_profile(update, context)


def show_profile(update: Update, context: CallbackContext):
    profiles = context.user_data.get('profiles', [])
    current = context.user_data.get('current_profile', 0)

    if not profiles or current >= len(profiles):
        update.message.reply_text("No more profiles to show.")
        return

    profile_id, name, age, bio, photo_id = profiles[current]

    # Create keyboard
    keyboard = []
    if len(profiles) > 1:
        if current > 0:
            keyboard.append(InlineKeyboardButton("⬅️ Previous", callback_data='prev_profile'))
        if current < len(profiles) - 1:
            keyboard.append(InlineKeyboardButton("Next ➡️", callback_data='next_profile'))

    keyboard.append(InlineKeyboardButton("💌 Message", callback_data=f'message_{profile_id}'))

    reply_markup = InlineKeyboardMarkup([keyboard])

    # Send profile
    try:
        context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo_id,
            caption=f"👤 {name}, {age}\n\n{bio}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending profile photo: {e}")
        update.message.reply_text(
            f"👤 {name}, {age}\n\n{bio}",
            reply_markup=reply_markup
        )


def profile_navigation(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    action = query.data

    if action.startswith('message_'):
        target_id = int(action.split('_')[1])
        context.user_data['message_target'] = target_id
        query.edit_message_text("Please type your message to send:")
        return BIO  # Reusing BIO state for message handling
    elif action == 'prev_profile':
        context.user_data['current_profile'] -= 1
    elif action == 'next_profile':
        context.user_data['current_profile'] += 1

    show_profile(update, context)


def handle_message(update: Update, context: CallbackContext):
    if 'message_target' not in context.user_data:
        update.message.reply_text("Please select a profile to message first.")
        return

    target_id = context.user_data['message_target']
    message = update.message.text

    # Get sender info
    conn = sqlite3.connect('dating_bot.db')
    c = conn.cursor()
    c.execute(
        "SELECT name, gender FROM users WHERE user_id = ?",
        (update.effective_user.id,)
    )
    sender = c.fetchone()
    conn.close()

    if not sender:
        update.message.reply_text("Your profile not found. Please register first.")
        return

    sender_name, sender_gender = sender

    # Send message to target
    try:
        context.bot.send_message(
            chat_id=target_id,
            text=f"💌 New message from {sender_name} ({'👨' if sender_gender == 'male' else '👩'}):\n\n{message}\n\n"
                 f"Reply to this conversation to respond."
        )
        update.message.reply_text("✅ Your message has been sent!")
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        update.message.reply_text("❌ Failed to send message. The user may have blocked the bot.")

    return ConversationHandler.END


# Help command
def help_command(update: Update, context: CallbackContext):
    help_text = (
        "🤖 Dating Bot Help\n\n"
        "Available commands:\n"
        "/start - Begin registration\n"
        "/profiles - Browse available profiles\n"
        "/status - Check your approval status\n"
        "/help - Show this help message\n\n"
        "For girls:\n"
        "- Registration is completely free\n"
        "- Your data is 100% private and secure\n"
        "- Only approved male profiles will be shown to you\n\n"
        "For boys:\n"
        "- One-time registration fee of ₹100\n"
        "- Your profile must be approved before being shown to girls\n\n"
        f"Need more help? Contact admin: @Dating711"
    )

    if update.callback_query:
        update.callback_query.message.reply_text(help_text)
    else:
        update.message.reply_text(help_text)


# Payment info command
def payment_info(update: Update, context: CallbackContext):
    payment_text = (
        f"💳 Payment Information\n\n"
        f"For male users, there's a one-time registration fee of ₹{PAYMENT_AMOUNT}.\n\n"
        f"Payment method:\n"
        f"1. Send ₹{PAYMENT_AMOUNT} to our UPI ID: `{UPI_ID}`\n"
        f"2. After payment, send the screenshot of the payment confirmation\n\n"
        f"⚠️ Important:\n"
        f"- Fake payment screenshots will result in permanent ban\n"
        f"- Payment is only required for male users\n"
        f"- Girls can register for free\n\n"
        f"Need help with payment? Contact admin: @Deting711"
    )

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(f"upi://pay?pa={UPI_ID}&am={PAYMENT_AMOUNT}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    bio = BytesIO()
    img.save(bio, format='PNG')
    bio.seek(0)

    if update.callback_query:
        update.callback_query.message.reply_photo(
            photo=bio,
            caption=payment_text,
            parse_mode='Markdown'
        )
    else:
        update.message.reply_photo(
            photo=bio,
            caption=payment_text,
            parse_mode='Markdown'
        )


# Status command

def status_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    conn = sqlite3.connect('dating_bot.db')
    c = conn.cursor()
    c.execute(
        "SELECT approved FROM users WHERE user_id = ?",
        (user_id,)
    )
    status = c.fetchone()
    conn.close()

    if not status:
        update.message.reply_text("You haven't completed registration yet. Use /start to begin.")
    elif status[0]:
        update.message.reply_text("✅ Your profile is approved! Use /profiles to browse.")
    else:
        update.message.reply_text(
            "⏳If you have completed the payment, your profile will be approved. If you have made a fake payment, it will keep showing as pending repeatedly. If your profile is not getting approved even after making the payment, message me at @Deting711")




def cancel(update: Update, context: CallbackContext):
    update.message.reply_text('Operation cancelled.')
    return ConversationHandler.END


def error_handler(update: Update, context: CallbackContext):
    logger.error(msg="Exception while handling update:", exc_info=context.error)

    try:
        update.message.reply_text('An error occurred. Please try again or contact admin.')
    except:
        pass


def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    # Conversation handler for registration
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GENDER: [CallbackQueryHandler(gender_handler)],
            MALE_PAYMENT: [MessageHandler(Filters.photo, payment_handler)],
            PHOTO: [MessageHandler(Filters.photo, photo_handler)],
            DETAILS: [MessageHandler(Filters.text & ~Filters.command, details_handler)],
            BIO: [MessageHandler(Filters.text & ~Filters.command, bio_handler)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dp.add_handler(conv_handler)
    dp.add_handler(CommandHandler('help', help_command))
    dp.add_handler(CommandHandler('status', status_command))
    dp.add_handler(CommandHandler('payment_info', payment_info))
    dp.add_handler(CommandHandler('profiles', view_profiles))
    dp.add_handler(CommandHandler('approve', approve_profile))
    dp.add_handler(CallbackQueryHandler(profile_navigation, pattern='^(prev_profile|next_profile|message_)'))
    dp.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
    dp.add_handler(CallbackQueryHandler(payment_info, pattern='^payment_info$'))
    dp.add_error_handler(error_handler)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()