import json
import os
import urllib.parse
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from sqlalchemy.orm import joinedload
from database import get_db, ParsedListing, StatusEnum, ParcelReview, TelegramUserState
from flows.scorer import calculate_score
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBAPP_URL = os.getenv("MAP_WEBAPP_URL")

ALLOWED_USERS_ENV = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(u.strip()) for u in ALLOWED_USERS_ENV.split(",") if u.strip().isdigit()]


def get_pending_parcels(db, user_id, limit=1):
    reviewed_subquery = db.query(ParcelReview.listing_id).filter(ParcelReview.user_id == str(user_id)).subquery()
    
    listings = db.query(ParsedListing).options(
        joinedload(ParsedListing.raw_listing),
        joinedload(ParsedListing.spatial_evaluation),
        joinedload(ParsedListing.route_evaluations),
        joinedload(ParsedListing.geocoded_parcel)
    ).filter(
        ParsedListing.status.in_([StatusEnum.SPATIALLY_VALIDATED, StatusEnum.ROUTED]),
        ~ParsedListing.id.in_(reviewed_subquery)
    ).all()
    
    scored_listings = []
    for listing in listings:
        res = calculate_score.fn(listing)
        scored_listings.append({
            "id": listing.id,
            "url": listing.raw_listing.source_url,
            "score": res["score"],
            "max_score": res["max_score"],
            "location_type": res.get("location_type", "ℹ️ LOCATION: Unknown"),
            "reasons": res["reasons"],
            "wkt": res.get("wkt"),
            "lat": res.get("lat"),
            "lon": res.get("lon"),
            "price": res.get("price"),
            "area": res.get("area")
        })
        
    scored_listings.sort(key=lambda x: x["score"], reverse=True)
    return scored_listings[:limit]

async def send_or_edit_parcel(context, chat_id, user_id, query=None):
    db = next(get_db())
    try:
        # First, send the next parcel if available
        parcels = get_pending_parcels(db, user_id, limit=1)
        
        # Recalculate count
        reviewed_subquery = db.query(ParcelReview.listing_id).filter(ParcelReview.user_id == str(user_id)).subquery()
        count = db.query(ParsedListing).filter(
            ParsedListing.status.in_([StatusEnum.SPATIALLY_VALIDATED, StatusEnum.ROUTED]),
            ~ParsedListing.id.in_(reviewed_subquery)
        ).count()
        
        if not parcels:
            msg = "🎉 *No more qualified parcels found!* You've reviewed all of them."
            keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
        else:
            parcel = parcels[0]
            
            msg = "*Why it matched:* \n"
            for reason in parcel['reasons']:
                msg += f"• {reason}\n"
                
            msg += "\n"
            if parcel.get('price'):
                price_str = f"{parcel['price']:,.0f}".replace(",", " ")
                msg += f"💰 *Price:* {price_str} PLN\n"
            if parcel.get('area'):
                msg += f"📐 *Area:* {parcel['area']:,.0f} m²\n"
            msg += f"⭐ *Score:* {parcel['score']}/{parcel['max_score']}\n"
            msg += f"📍 *{parcel['location_type']}*\n"
                
            msg += f"\n*Parcels pending review:* {count}"
                
            keyboard = []
            
            # Action buttons row (Otodom + Maps)
            action_buttons = [InlineKeyboardButton("🔗 Otodom", url=parcel['url'])]
            
            if parcel.get("wkt") or (parcel.get("lat") and parcel.get("lon")):
                params = []
                if parcel.get("wkt"):
                    wkt_str = parcel['wkt']
                    if wkt_str.startswith("SRID="):
                        wkt_str = wkt_str.split(";", 1)[-1]
                    params.append(f"wkt={urllib.parse.quote(wkt_str)}")
                if parcel.get("lat"):
                    params.append(f"lat={parcel['lat']}&lon={parcel['lon']}")
                    
                map_url = f"{WEBAPP_URL}?{'&'.join(params)}"
                action_buttons.append(InlineKeyboardButton("🗺️ Map", url=map_url))
                
                if parcel.get("lat") and parcel.get("lon"):
                    google_maps_url = f"https://www.google.com/maps/search/?api=1&query={parcel['lat']},{parcel['lon']}"
                    action_buttons.append(InlineKeyboardButton("🌍 GMaps", url=google_maps_url))
                    
            keyboard.append(action_buttons)
                
            rating_buttons = [
                InlineKeyboardButton("Wow 🤩", callback_data=f"rate_wow_{parcel['id']}"),
                InlineKeyboardButton("Yes 👍", callback_data=f"rate_yes_{parcel['id']}"),
                InlineKeyboardButton("Maybe 🤔", callback_data=f"rate_maybe_{parcel['id']}"),
                InlineKeyboardButton("No 👎", callback_data=f"rate_no_{parcel['id']}")
            ]
            keyboard.append(rating_buttons)
            keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
        # We always send a new message first, then delete the old one.
        # This forces the client to scroll to the new message, and when the old one is deleted above it, it pulls the top of the new message into view smoothly.
        user_state = db.query(TelegramUserState).filter(TelegramUserState.user_id == str(user_id)).first()
        old_msg_id = user_state.last_menu_msg_id if user_state else None
        
        sent_msg = await context.bot.send_message(
            chat_id=chat_id, 
            text=msg, 
            parse_mode="Markdown", 
            disable_web_page_preview=True, 
            reply_markup=reply_markup
        )
        
        if old_msg_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
            except Exception:
                pass
        
        if not user_state:
            user_state = TelegramUserState(user_id=str(user_id), last_menu_msg_id=sent_msg.message_id)
            db.add(user_state)
        else:
            user_state.last_menu_msg_id = sent_msg.message_id
        db.commit()
            
    finally:
        db.close()

async def send_main_menu(context, chat_id, user_id):
    db = next(get_db())
    try:
        reviewed_subquery = db.query(ParcelReview.listing_id).filter(ParcelReview.user_id == str(user_id)).subquery()
        count = db.query(ParsedListing).filter(
            ParsedListing.status.in_([StatusEnum.SPATIALLY_VALIDATED, StatusEnum.ROUTED]),
            ~ParsedListing.id.in_(reviewed_subquery)
        ).count()
        
        msg = f"🏠 *Main Menu*\n\nWelcome to the Plot Search Bot!\nYou have *{count}* plots waiting for review."
        
        keyboard = [
            [InlineKeyboardButton("🔍 Start Review", callback_data="menu_start_review")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        user_state = db.query(TelegramUserState).filter(TelegramUserState.user_id == str(user_id)).first()
        old_msg_id = user_state.last_menu_msg_id if user_state else None
        
        sent_msg = await context.bot.send_message(
            chat_id=chat_id, 
            text=msg, 
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        
        if old_msg_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
            except Exception:
                pass
        
        if not user_state:
            user_state = TelegramUserState(user_id=str(user_id), last_menu_msg_id=sent_msg.message_id)
            db.add(user_state)
        else:
            user_state.last_menu_msg_id = sent_msg.message_id
        db.commit()
            
    finally:
        db.close()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id not in ALLOWED_USERS:
        return
    user_id = str(update.message.from_user.id)
    chat_id = update.message.chat_id
    current_msg_id = update.message.message_id
    
    # Clear chat by deleting the last 30 messages
    tasks = []
    for i in range(0, 30):
        tasks.append(context.bot.delete_message(chat_id=chat_id, message_id=current_msg_id - i))
    await asyncio.gather(*tasks, return_exceptions=True)
        
    persistent_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("🏠 Main Menu"), KeyboardButton("🔍 Review Mode")]], 
        resize_keyboard=True,
        is_persistent=True
    )
    
    setup_msg = await context.bot.send_message(
        chat_id=chat_id, 
        text="Initializing bot buttons...", 
        reply_markup=persistent_keyboard
    )
    try:
        await setup_msg.delete()
    except Exception:
        pass

    await send_main_menu(context, chat_id, user_id)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id not in ALLOWED_USERS:
        return
    text = update.message.text
    user_id = str(update.message.from_user.id)
    chat_id = update.message.chat_id
    current_msg_id = update.message.message_id
    
    if text == "🔍 Review Mode":
        tasks = []
        for i in range(0, 30):
            tasks.append(context.bot.delete_message(chat_id=chat_id, message_id=current_msg_id - i))
        await asyncio.gather(*tasks, return_exceptions=True)
            
        await send_or_edit_parcel(context, chat_id, user_id)
    elif text == "🏠 Main Menu":
        tasks = []
        for i in range(0, 30):
            tasks.append(context.bot.delete_message(chat_id=chat_id, message_id=current_msg_id - i))
        await asyncio.gather(*tasks, return_exceptions=True)
            
        await send_main_menu(context, chat_id, user_id)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id not in ALLOWED_USERS:
        await query.answer("You are not authorized to use this bot.", show_alert=True)
        return
    await query.answer()
    user_id = str(query.from_user.id)
    chat_id = query.message.chat_id
    data = query.data
    
    if data == "menu_start_review":
        await send_or_edit_parcel(context, chat_id, user_id)
        return
    elif data == "menu_main":
        await send_main_menu(context, chat_id, user_id)
        return
    
    if data.startswith("rate_"):
        parts = data.split("_", 2)
        rating = parts[1]
        parcel_id = parts[2]
        
        db = next(get_db())
        try:
            existing = db.query(ParcelReview).filter_by(user_id=user_id, listing_id=parcel_id).first()
            if not existing:
                review = ParcelReview(user_id=user_id, listing_id=parcel_id, rating=rating)
                db.add(review)
                db.commit()
            
            # We removed the shrink trick as requested by user
        finally:
            db.close()
            
        await send_or_edit_parcel(context, chat_id, user_id)

async def check_new_parcels(context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        for user_id_int in ALLOWED_USERS:
            user_id = str(user_id_int)
            reviewed_subquery = db.query(ParcelReview.listing_id).filter(ParcelReview.user_id == user_id).subquery()
            count = db.query(ParsedListing).filter(
                ParsedListing.status.in_([StatusEnum.SPATIALLY_VALIDATED, StatusEnum.ROUTED]),
                ~ParsedListing.id.in_(reviewed_subquery)
            ).count()
            
            user_state = db.query(TelegramUserState).filter(TelegramUserState.user_id == user_id).first()
            if not user_state:
                user_state = TelegramUserState(user_id=user_id, last_notified_count=0)
                db.add(user_state)
                db.commit()
                db.refresh(user_state)
                
            last_count = user_state.last_notified_count or 0
            if count > last_count:
                diff = count - last_count
                msg = f"🔔 *New parcels!* Found {diff} new plot{'s' if diff > 1 else ''} to review. Total pending: {count}."
                keyboard = [
                    [InlineKeyboardButton("🔍 Start Review", callback_data="menu_start_review")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await context.bot.send_message(
                        chat_id=user_id, 
                        text=msg, 
                        parse_mode="Markdown",
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    print(f"Failed to notify user {user_id}: {e}")
                    
            user_state.last_notified_count = count
            db.commit()
    finally:
        db.close()

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    app.job_queue.run_repeating(check_new_parcels, interval=60, first=10)
    
    print("🤖 Telegram Bot is polling... Send /start to interact!")
    app.run_polling()

if __name__ == "__main__":
    main()
