import json
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from sqlalchemy.orm import joinedload
from database import get_db, ParsedListing, StatusEnum
from flows.scorer import calculate_score

TOKEN = "8860337033:AAGtuLkNuBbE4fWdexmPfQQGPUQ73LHnX_A"
NOTIFIED_FILE = "notified_plots.json"

def load_notified():
    if os.path.exists(NOTIFIED_FILE):
        with open(NOTIFIED_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_notified(notified_set):
    with open(NOTIFIED_FILE, "w") as f:
        json.dump(list(notified_set), f)

def get_best_next_parcel():
    db = next(get_db())
    try:
        listings = db.query(ParsedListing).options(
            joinedload(ParsedListing.raw_listing),
            joinedload(ParsedListing.spatial_evaluation),
            joinedload(ParsedListing.route_evaluations)
        ).filter(
            ParsedListing.status.in_([StatusEnum.SPATIALLY_VALIDATED, StatusEnum.ROUTED])
        ).all()
        
        notified = load_notified()
        
        best_parcel = None
        best_score = -9999
        
        for listing in listings:
            if listing.id in notified:
                continue
                
            res = calculate_score.fn(listing)
            if res["score"] > best_score:
                best_score = res["score"]
                best_parcel = {
                    "id": listing.id,
                    "url": listing.raw_listing.source_url,
                    "score": res["score"],
                    "max_score": res["max_score"],
                    "location_type": res.get("location_type", "ℹ️ LOCATION: Unknown"),
                    "reasons": res["reasons"]
                }
                
        return best_parcel
    finally:
        db.close()

async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔍 Calculating scores and finding the best next parcel for you...")
    
    # Run synchronously (it's fast enough for this scale)
    best_parcel = get_best_next_parcel()
    
    if not best_parcel:
        await update.message.reply_text("🎉 No more qualified parcels found! You've reviewed all of them.")
        return
        
    msg = f"🏆 *New Golden Parcel Found!*\n\n"
    msg += f"🔗 [View on Otodom]({best_parcel['url']})\n"
    msg += f"⭐ *Score:* {best_parcel['score']}/{best_parcel['max_score']}\n"
    msg += f"📍 *{best_parcel['location_type']}*\n\n"
    msg += "*Why it matched:* \n"
    for reason in best_parcel['reasons']:
        msg += f"• {reason}\n"
        
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=False)
    
    notified = load_notified()
    notified.add(best_parcel["id"])
    save_notified(notified)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("next", next_command))
    
    print("🤖 Telegram Bot is polling... Send /next to get your Golden Parcel!")
    app.run_polling()

if __name__ == "__main__":
    main()
