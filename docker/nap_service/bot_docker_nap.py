
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baby-care tracker v2 - FIXED
Adds Nap-Start / Nap-End buttons and an adjustable time-picker
FIXES: Custom time input handling, timezone consistency, handler ordering
"""

from datetime import datetime, timedelta, timezone
import csv, os
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

TZ = ZoneInfo("Europe/Rome")

# Configuration from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
AUTHORIZED_IDS = set(map(int, os.getenv("AUTHORIZED_IDS", "").split(","))) if os.getenv("AUTHORIZED_IDS") else set()
CSV_PATH = Path("/app/data/events.csv")  # Store in mounted volume

# InfluxDB Configuration
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://host.docker.internal:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "")

# Initialize InfluxDB client only if configured
influx_client = None
write_api = None

if INFLUXDB_TOKEN and INFLUXDB_ORG and INFLUXDB_BUCKET:
    try:
        from influxdb_client import InfluxDBClient, Point
        from influxdb_client.client.write_api import SYNCHRONOUS
        
        influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
        write_api = influx_client.write_api(write_options=SYNCHRONOUS)
        print("✅ InfluxDB client initialized")
    except Exception as e:
        print(f"❌ InfluxDB initialization failed: {e}")

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ---- NAP STATE KEYS (shared across all users) ----
NAP_STATE_KEY = "nap_active_start"   # active nap start (datetime)
LAST_NAP_START_KEY = "last_nap_start"  # remember last start for friendly messages

def fmt_it(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime('%Y-%m-%d %H:%M')

def _get_user_info(msg_obj):
    if hasattr(msg_obj, 'from_user') and msg_obj.from_user:
        who = msg_obj.from_user.first_name or str(msg_obj.from_user.id)
        user_id = msg_obj.from_user.id
    else:
        who = "Unknown"
        user_id = None
    return who, user_id

async def _confirm_and_broadcast(ctx, msg_obj, text: str, user_id: int | None):
    # Broadcast to other authorized users
    await broadcast(ctx, text, exclude_user_id=user_id)
    # Reply or edit the inline-picker message
    if hasattr(msg_obj, 'edit_message_text'):
        try:
            await msg_obj.edit_message_text(text)
        except Exception as e:
            print(f"Failed to edit message: {e}")
    else:
        await msg_obj.reply_text(text, reply_markup=MAIN_KBD)

def _cleanup_inline_state(ctx):
    # Remove only transient picker flags; keep any nap state
    for k in ("awaiting_custom", "pending_event", "base_time"):
        ctx.user_data.pop(k, None)

async def handle_nap_start(ctx, msg_obj, stamp: datetime):
    who, user_id = _get_user_info(msg_obj)
    italian_stamp = stamp.astimezone(TZ)
    state = ctx.application.bot_data

    # Duplicate: already active
    if state.get(NAP_STATE_KEY) is not None:
        existing = state[NAP_STATE_KEY]
        txt = f"ℹ️ A nap start was already recorded at {fmt_it(existing)}."
        await _confirm_and_broadcast(ctx, msg_obj, txt, user_id)
        _cleanup_inline_state(ctx)
        return

    # Set active state and remember last start
    state[NAP_STATE_KEY] = stamp
    state[LAST_NAP_START_KEY] = stamp

    # CSV: keep unchanged behavior for /csv (log Nap-Start row)
    append_row([italian_stamp.isoformat(timespec="seconds"), "Nap-Start", who])

    txt = f"✅ Nap-Start by {who} at {fmt_it(stamp)} (Italy time). Nap started."
    await _confirm_and_broadcast(ctx, msg_obj, txt, user_id)
    _cleanup_inline_state(ctx)


async def handle_nap_end(ctx, msg_obj, stop: datetime):
    who, user_id = _get_user_info(msg_obj)
    italian_stop = stop.astimezone(TZ)
    state = ctx.application.bot_data

    start = state.get(NAP_STATE_KEY)
    if start is None:
        # No active nap; friendly info if we know the last start time
        last_start = state.get(LAST_NAP_START_KEY)
        if last_start:
            txt = (
                f"ℹ️ No active nap. A nap end may have already been recorded.\n"
                f"Last nap start was at {fmt_it(last_start)}."
            )
        else:
            txt = "ℹ️ No active nap. Please tap “Nap-Start” first."
        await _confirm_and_broadcast(ctx, msg_obj, txt, user_id)
        _cleanup_inline_state(ctx)
        return

    # Validate chronological order
    if stop < start:
        txt = (
            f"❌ The selected end time ({fmt_it(stop)}) is before the start ({fmt_it(start)}).\n"
            f"Please pick a correct end time."
        )
        await _confirm_and_broadcast(ctx, msg_obj, txt, user_id)
        _cleanup_inline_state(ctx)
        return

    duration_sec = int((stop - start).total_seconds())

    # CSV: keep unchanged behavior for /csv (log Nap-End row)
    append_row([italian_stop.isoformat(timespec="seconds"), "Nap-End", who])

    # InfluxDB: write consolidated 'Nap' only (not Nap-Start/End)
    if write_api and influx_client:
        try:
            point = (
                Point("baby_events")
                .tag("event_type", "Nap")
                .tag("parent", who)
                .tag("user_id", str(user_id) if user_id else "unknown")
                .field("start", start.astimezone(TZ).isoformat(timespec="seconds"))
                .field("stop", italian_stop.isoformat(timespec="seconds"))
                .field("duration", duration_sec)  # seconds (numeric)
                .time(stop)  # point timestamp = end time
            )
            write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
            print(f"✅ Saved Nap to InfluxDB: {who}, duration {duration_sec}s")
        except Exception as e:
            print(f"❌ InfluxDB write failed (Nap): {e}")

    # Clear active state but remember last start for friendly messages
    state[LAST_NAP_START_KEY] = start
    state.pop(NAP_STATE_KEY, None)

    # Human-friendly duration H:MM
    h = duration_sec // 3600
    m = (duration_sec % 3600) // 60
    dur_txt = f"{h}:{m:02d}"

    txt = (
        f"✅ Nap saved for {who}:\n"
        f"• Start: {fmt_it(start)}\n"
        f"• End:   {fmt_it(stop)}\n"
        f"• Duration: {dur_txt} (h:mm)"
    )
    await _confirm_and_broadcast(ctx, msg_obj, txt, user_id)
    _cleanup_inline_state(ctx)
    
## NAP change end

###############################################################################
# 2. GUI ELEMENTS ----------------------------------------------------------- #

MAIN_KBD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🍼 Feed-Left"),  KeyboardButton("🍼 Feed-Right")],
        [KeyboardButton("💧 Pee"),        KeyboardButton("💩 Poop")],
        [KeyboardButton("😴 Nap-Start"), KeyboardButton("⏰ Nap-End")],
    ],
    resize_keyboard=True,
)

def time_picker_markup(base: datetime) -> InlineKeyboardMarkup:
    """Offer quick offsets plus a 'Custom' option."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Now", callback_data="NOW"),
                InlineKeyboardButton("-5 min",  callback_data="OFFSET:-5"),
                InlineKeyboardButton("-15 min", callback_data="OFFSET:-15"),
                InlineKeyboardButton("-30 min", callback_data="OFFSET:-30"),
            ],
            [InlineKeyboardButton("Custom ⌚️", callback_data="CUSTOM")],
        ]
    )

# 3. UTILITIES -------------------------------------------------------------- #

def append_row(row: List[str]) -> None:
    new_file = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp_Italy", "event", "who"])
        w.writerow(row)

async def broadcast(ctx: ContextTypes.DEFAULT_TYPE, text: str, exclude_user_id: int = None) -> None:
    for uid in AUTHORIZED_IDS:
        if exclude_user_id and uid == exclude_user_id:
            continue  # Skip the sender
        try:
            await ctx.bot.send_message(chat_id=uid, text=text, reply_markup=MAIN_KBD)
        except Exception as e:
            print(f"Failed to broadcast to {uid}: {e}")

# 4. EVENT HANDLERS --------------------------------------------------------- #

EVENT_MAP = {
    "🍼 Feed-Left":  "Feed-Left",
    "🍼 Feed-Right": "Feed-Right",
    "💧 Pee":        "Pee",
    "💩 Poop":       "Poop",
    "😴 Nap-Start":  "Nap-Start",
    "⏰ Nap-End":    "Nap-End",
}

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Only allow authorized users
    if update.effective_user.id not in AUTHORIZED_IDS or not update.message:
        return
    # 1. Custom time input mode
    if ctx.user_data.get("awaiting_custom"):
        event = ctx.user_data.get("pending_event")
        text = update.message.text.strip()
        stamp = None
        # Try parsing as HH:MM today (Italy tz)
        try:
            if ":" in text and len(text.split(":")) == 2:
                h, m = map(int, text.split(":"))
                today = datetime.now(TZ).date()
                stamp = datetime.combine(today, datetime.min.time().replace(hour=h, minute=m)).replace(tzinfo=TZ)
        except Exception:
            pass
        
        # Try parsing as YYYY-MM-DD HH:MM (Italy tz)
        if stamp is None:
            try:
                naive = datetime.strptime(text, "%Y-%m-%d %H:%M")
                stamp = naive.replace(tzinfo=TZ)
            except Exception:
                pass
        if stamp is None:
            await update.message.reply_text(
                "❌ Could not parse time. Use:\n"
                "• HH:MM (e.g. 07:32)\n"
                "• YYYY-MM-DD HH:MM (e.g. 2025-08-04 07:32)\nTry again:"
            )
            return
        # Route naps to custom handlers; others keep existing finalize
        if event == "Nap-Start":
            # Don’t write to InfluxDB; set state and CSV Nap-Start
            await handle_nap_start(ctx, update.message, stamp)
            return
        elif event == "Nap-End":
            # Write consolidated “Nap” to InfluxDB; CSV Nap-End
            await handle_nap_end(ctx, update.message, stamp)
            return
        else:
            # Existing behavior for non-nap events
            ctx.user_data.clear()
            await finalize_event(ctx, update.message, event, stamp)
            return
        
    # 2. Event selection mode
    text = update.message.text
    if text in EVENT_MAP:
        chosen = EVENT_MAP[text]

        # Nap duplicate guards (shared state across all users)
        if chosen == "Nap-Start":
            existing = ctx.application.bot_data.get(NAP_STATE_KEY)
            if existing is not None:
                await update.message.reply_text(
                    f"ℹ️ A nap start was already recorded at {fmt_it(existing)}.",
                    reply_markup=MAIN_KBD,
                )
                return
        if chosen == "Nap-End":
            existing = ctx.application.bot_data.get(NAP_STATE_KEY)
            if existing is None:
                last = ctx.application.bot_data.get(LAST_NAP_START_KEY)
                if last:
                    await update.message.reply_text(
                        f"ℹ️ No active nap. A nap end may have already been recorded.\n"
                        f"Last nap start was at {fmt_it(last)}.",
                        reply_markup=MAIN_KBD,
                    )
                else:
                    await update.message.reply_text(
                        "ℹ️ No active nap. Please tap “Nap-Start” first.",
                        reply_markup=MAIN_KBD,
                    )
                return

        ctx.user_data["pending_event"] = chosen
        ctx.user_data["base_time"] = datetime.now(TZ)
        await update.message.reply_text(
            f"📅 {chosen} – pick the correct time "
            f"(default: {ctx.user_data['base_time'].strftime('%Y-%m-%d %H:%M')})",
            reply_markup=time_picker_markup(ctx.user_data["base_time"]),
        )
        return
    # Anything else: ignore
    return

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in AUTHORIZED_IDS:
        await update.message.reply_text("Private bot – access denied.")
        return

    await update.message.reply_text(
        "Hi! Tap a button when something happens.",
        reply_markup=MAIN_KBD,
    )

async def custom_time_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Parse user-typed custom time - FIXED VERSION."""
    
    # Only process if we're awaiting custom input
    if not ctx.user_data.get("awaiting_custom"):
        return
    
    if update.effective_user.id not in AUTHORIZED_IDS or not update.message:
        return

    event = ctx.user_data.get("pending_event")
    text = update.message.text.strip()
    
    if not event:
        await update.message.reply_text("❌ No pending event found. Please start over.")
        ctx.user_data.clear()
        return

    stamp: Optional[datetime] = None
    
    # Try parsing HH:MM format first (today's date in Italy timezone)
    try:
        if ":" in text and len(text.split(":")) == 2:
            time_part = text.split(":")
            if len(time_part[0]) <= 2 and len(time_part[1]) <= 2:  # Looks like HH:MM
                hh, mm = map(int, time_part)
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    # Get today's date in Italy timezone
                    today = datetime.now(TZ).date()
                    # Create datetime with parsed time in Italy timezone
                    stamp = datetime.combine(today, datetime.min.time().replace(hour=hh, minute=mm)).replace(tzinfo=TZ)
    except (ValueError, IndexError) as e:
        print(f"HH:MM parsing failed: {e}")
        pass

    # Try parsing YYYY-MM-DD HH:MM format (in Italy timezone)
    if stamp is None:
        try:
            # Parse as naive datetime first
            naive_dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
            # Make it timezone-aware in Italy timezone
            stamp = naive_dt.replace(tzinfo=TZ)
        except ValueError as e:
            print(f"YYYY-MM-DD HH:MM parsing failed: {e}")
            pass

    if stamp is None:
        await update.message.reply_text(
            "❌ Could not parse time. Please use format:\n"
            "• HH:MM (e.g., 07:32)\n"
            "• YYYY-MM-DD HH:MM (e.g., 2025-08-04 07:32)\n\n"
            "Try again:"
        )
        return

    # Clear the awaiting flag
    ctx.user_data.pop("awaiting_custom", None)
    
    if event == "Nap-Start":
        await handle_nap_start(ctx, update.message, stamp)
    elif event == "Nap-End":
        await handle_nap_end(ctx, update.message, stamp)
    else:
        await finalize_event(ctx, update.message, event, stamp)

async def event_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in AUTHORIZED_IDS or not update.message:
        return
    
    # Skip if we're awaiting custom input
    if ctx.user_data.get("awaiting_custom"):
        return

    text = update.message.text

    if text not in EVENT_MAP:
        return

    # Stash pending event & show time-picker
    ctx.user_data["pending_event"] = EVENT_MAP[text]
    ctx.user_data["base_time"]     = datetime.now(TZ)

    await update.message.reply_text(
        f"📅 {EVENT_MAP[text]} – pick the correct start time "
        f"(default: {ctx.user_data['base_time'].strftime('%Y-%m-%d %H:%M')})",
        reply_markup=time_picker_markup(ctx.user_data["base_time"]),
    )

async def inline_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle presses on the inline time-picker."""
    query = update.callback_query
    await query.answer()

    data = query.data

    event  = ctx.user_data.get("pending_event")
    base_t = ctx.user_data.get("base_time")

    if not event or not base_t:
        await query.edit_message_text("❌ Session expired. Please start over.")
        ctx.user_data.clear()
        return

    if data == "NOW":
        stamp = datetime.now(TZ)

    elif data.startswith("OFFSET:"):
        try:
            mins = int(data.split(":")[1])
            stamp = base_t + timedelta(minutes=mins)
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Invalid offset. Please start over.")
            ctx.user_data.clear()
            return

    elif data == "CUSTOM":
        # Set flag for custom time input
        ctx.user_data["awaiting_custom"] = True
        await query.edit_message_text(
            "⏰ Enter custom time:\n\n"
            "• For today: HH:MM (e.g., 07:32)\n"
            "• For specific date: YYYY-MM-DD HH:MM (e.g., 2025-08-04 07:32)\n\n"
            "All times are in Italy timezone."
        )
        return

    else:
        await query.edit_message_text("❌ Unknown option. Please start over.")
        ctx.user_data.clear()
        return

    # Route naps to their specific handlers; others use finalize_event
    if event == "Nap-Start":
        await handle_nap_start(ctx, query, stamp)
    elif event == "Nap-End":
        await handle_nap_end(ctx, query, stamp)
    else:
        await finalize_event(ctx, query, event, stamp)

async def finalize_event(ctx, msg_obj, event: str, stamp: datetime):
    """Finalize and log the event - IMPROVED VERSION."""
    
    # Get user info
    if hasattr(msg_obj, 'from_user'):
        who = msg_obj.from_user.first_name or str(msg_obj.from_user.id)
        user_id = msg_obj.from_user.id
    else:
        who = "Unknown"
        user_id = None

    # Keep Italian time for CSV storage
    italian_stamp = stamp.astimezone(TZ)
    
    # Save to CSV with Italian timestamp
    append_row([italian_stamp.isoformat(timespec="seconds"), event, who])
    
    # Format for display (already in Italy timezone)
    display_time = italian_stamp.strftime('%Y-%m-%d %H:%M')
    
    # Send confirmation message
    confirmation_text = f"✅ {event} by {who} at {display_time} (Italy time)"
    
    # Save to InfluxDB (if configured)
    if write_api and influx_client:
        try:
            point = (
                Point("baby_events")
                .tag("event_type", event)
                .tag("parent", who)
                .tag("user_id", str(user_id) if user_id else "unknown")
                .field("count", 1)
                .time(stamp)
            )
            write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
            print(f"✅ Saved to InfluxDB: {event} by {who}")
        except Exception as e:
            print(f"❌ InfluxDB write failed: {e}")
    
    # Broadcast to all authorized users
    await broadcast(ctx, confirmation_text, exclude_user_id=user_id)

    # Clean up user_data
    ctx.user_data.clear()

    # Remove inline keyboard if this came from a callback query
    if hasattr(msg_obj, 'edit_message_text'):
        try:
            await msg_obj.edit_message_text(confirmation_text)
        except Exception as e:
            print(f"Failed to edit message: {e}")
    else:
        # This was a regular message, send confirmation
        await msg_obj.reply_text(confirmation_text, reply_markup=MAIN_KBD)

async def send_csv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in AUTHORIZED_IDS:
        return

    if CSV_PATH.exists():
        await ctx.bot.send_document(
            chat_id=update.effective_user.id,
            document=CSV_PATH.open("rb"),
            filename="events.csv",
            caption="Current log",
        )
    else:
        await update.message.reply_text("No data yet.")

# 5. MAIN ------------------------------------------------------------------- #

def main():
    if not BOT_TOKEN:
        print("❌ Please set BOT_TOKEN in the configuration section")
        return
    
    if not AUTHORIZED_IDS:
        print("❌ Please set AUTHORIZED_IDS in the configuration section")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("csv", send_csv))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(inline_choice))

    print("Bot running… Ctrl-C to stop.")
    print(f"Authorized users: {len(AUTHORIZED_IDS)}")
    print(f"CSV file: {CSV_PATH}")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

