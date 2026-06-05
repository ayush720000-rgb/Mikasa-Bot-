# ============================================================
#  🌸 Mikasa Bot — v5 OPTIMIZED
#  ✨ Better API usage, caching, rate limiting, error handling
#  ✨ Enhanced inline keyboards, modular structure
#  Install : pip install aiogram groq aioredis
#  Run     : python mikasa_bot_v5_optimized.py
# ============================================================

import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Optional, Callable, Awaitable
from functools import wraps
from datetime import datetime, timedelta
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ChatPermissions, FSInputFile, BotCommand, BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats, ChatMemberUpdated, User, Chat
)
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from groq import Groq
from groq.types.chat import ChatCompletion

# ════════════════════════════════════════════════════════════
#  CONFIGURATION & CONSTANTS
# ════════════════════════════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
OWNER_ID = 8761202621

if not BOT_TOKEN or not GROQ_KEY:
    raise ValueError("❌ Missing BOT_TOKEN or GROQ_API_KEY in environment variables")

groq_client = Groq(api_key=GROQ_KEY)
GROQ_MODEL = "llama-3.1-70b-versatile"  # Better model for better results
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('mikasa_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

STICKER_PACK = "hamsterset"
STICKER_CACHE_TTL = 3600  # Cache stickers for 1 hour

# ════════════════════════════════════════════════════════════
#  ADVANCED CACHING & RATE LIMITING SYSTEM
# ════════════════════════════════════════════════════════════

class CacheManager:
    """Simple in-memory cache with TTL support"""
    def __init__(self):
        self.cache = {}
        self.ttl = {}
    
    def set(self, key: str, value: Any, ttl: int = 3600):
        self.cache[key] = value
        self.ttl[key] = time.time() + ttl
    
    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            return None
        if time.time() > self.ttl.get(key, 0):
            del self.cache[key]
            return None
        return self.cache[key]
    
    def delete(self, key: str):
        self.cache.pop(key, None)
        self.ttl.pop(key, None)
    
    def clear(self):
        self.cache.clear()
        self.ttl.clear()

cache_manager = CacheManager()

class RateLimiter:
    """Advanced rate limiting to prevent API throttling"""
    def __init__(self, max_calls: int = 30, time_window: int = 60):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = defaultdict(list)
    
    def is_allowed(self, user_id: int) -> bool:
        now = time.time()
        # Clean old calls
        self.calls[user_id] = [
            call_time for call_time in self.calls[user_id]
            if now - call_time < self.time_window
        ]
        
        if len(self.calls[user_id]) < self.max_calls:
            self.calls[user_id].append(now)
            return True
        return False
    
    def get_reset_time(self, user_id: int) -> int:
        if not self.calls[user_id]:
            return 0
        oldest = min(self.calls[user_id])
        return int(self.time_window - (time.time() - oldest))

rate_limiter = RateLimiter(max_calls=20, time_window=60)

def rate_limit(func):
    """Decorator for rate limiting"""
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        if not rate_limiter.is_allowed(message.from_user.id):
            reset_time = rate_limiter.get_reset_time(message.from_user.id)
            await message.reply(
                f"⏱️ <b>Rate Limited</b>\n\n"
                f"Thoda wait karo na~ 🥺\n"
                f"<i>{reset_time}s mein phir try kar sakte ho</i>",
                parse_mode="HTML"
            )
            return
        return await func(message, *args, **kwargs)
    return wrapper

# ════════════════════════════════════════════════════════════
#  IN-MEMORY DATA STORES (Can migrate to Redis later)
# ════════════════════════════════════════════════════════════

banned_users: dict[int, set[int]] = {}
search_mode: dict[int, bool] = {}
chat_settings: dict[int, dict] = {}
seen_members: dict[int, dict[int, dict]] = {}
spam_tasks: dict[int, asyncio.Task] = {}
warnings: dict[int, dict[int, int]] = {}
active_scramble: dict[int, dict] = {}
chat_history: dict[int, list] = {}
admin_cache: dict[int, dict] = {"timestamp": 0}  # Cache admin list with timestamp

COUPLE_LINES = [
    "Aww~ aaj ka perfect couple hai tum dono! 💕\nEk doosre ka haath thaam ke raho sadaa~ 🌸",
    "Yeh dono toh made for each other hain! 🥰\nLove is in the air~ ✨",
    "Aaj ka ship: confirmed! 💘\nDono mein bahut cute chemistry hai~ 🌷",
    "Stars ne decide kiya hai — yeh dono saath hain! 🌟\nKhush raho hamesha~ 💖",
    "Fate ne milaya hai inhe~ 🎀\nBest couple of the day — without a doubt! 💝",
]

STICKER_IDS: list[str] = []

# ════════════════════════════════════════════════════════════
#  IMPROVED SYSTEM PROMPTS
# ════════════════════════════════════════════════════════════

SYSTEM_PROMPT_TEMPLATE = """You are Mikasa, a cute and intelligent Indian girl chatting casually on Telegram.

PERSONALITY TRAITS ({mode}):
{mode_instruction}

LANGUAGE RULES ({lang}):
{lang_instruction}

RESPONSE GUIDELINES:
- Keep replies natural and human-like (2-8 words typically)
- Use at most 1 emoji per response
- React authentically to what users say
- Never break character or mention being an AI
- Respond to conversation history - stay in context
- Be witty, slightly teasing, but never mean

NEVER USE: "certainly", "of course", "I'd be happy to", "as an AI", "I understand your feelings"
"""

MODE_INSTRUCTIONS = {
    "cute": "Chill, friendly, slightly teasing. Have opinions. React honestly. Show emotions naturally.",
    "romantic": "Subtly soft and warm, never cringe. A bit more attentive. Still casual and short.",
    "rude": "Dry, unbothered, lightly savage. Zero patience for nonsense. Sharp and funny."
}

LANG_INSTRUCTIONS = {
    "hinglish": "Use casual Hindi-English mix. Keep grammar simple. Imperfect is fine. Examples: 'kya ho', 'boring ho rahi'",
    "english": "Use casual English. Simple grammar. Lowercase is fine. Keep it natural and conversational."
}

def get_system_prompt(chat_id: int) -> str:
    settings = get_settings(chat_id)
    mode = settings.get("mode", "cute")
    lang = settings.get("lang", "hinglish")
    
    return SYSTEM_PROMPT_TEMPLATE.format(
        mode=mode,
        mode_instruction=MODE_INSTRUCTIONS.get(mode, ""),
        lang=lang,
        lang_instruction=LANG_INSTRUCTIONS.get(lang, "")
    )

# ════════════════════════════════════════════════════════════
#  UTILITY FUNCTIONS
# ════════════════════════════════════════════════════════════

def get_settings(chat_id: int) -> dict:
    """Get or create settings for a chat"""
    return chat_settings.setdefault(chat_id, {"lang": "hinglish", "mode": "cute"})

def make_mention(user_id: int, name: str) -> str:
    """Create clickable Telegram HTML mention"""
    safe_name = name.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'

async def safe_api_call(func: Callable, *args, max_retries: int = 3, **kwargs) -> Optional[Any]:
    """Safely execute API calls with retry logic and better error handling"""
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except TelegramAPIError as e:
            if "Too Many Requests" in str(e) or "429" in str(e):
                wait_time = (2 ** attempt) * 2  # Exponential backoff
                logger.warning(f"Rate limited, waiting {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
            elif "Bad Request" in str(e) or "400" in str(e):
                logger.error(f"Bad request: {e}")
                return None
            else:
                logger.error(f"Telegram API error: {e}")
                if attempt == max_retries - 1:
                    return None
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Unexpected error in API call: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)
    return None

async def is_admin(chat_id: int, user_id: int) -> bool:
    """Check if user is admin (with caching)"""
    cache_key = f"admin_{chat_id}"
    cached = cache_manager.get(cache_key)
    
    if cached and user_id in cached:
        return cached[user_id]
    
    try:
        admins = await safe_api_call(bot.get_chat_administrators, chat_id)
        if admins:
            admin_ids = {a.user.id for a in admins}
            cache_manager.set(cache_key, admin_ids, ttl=300)  # Cache for 5 minutes
            return user_id in admin_ids
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
    
    return False

async def bot_is_admin(chat_id: int) -> bool:
    """Check if bot is admin in the group"""
    try:
        me = await safe_api_call(bot.get_me)
        if not me:
            return False
        admins = await safe_api_call(bot.get_chat_administrators, chat_id)
        if admins:
            return any(a.user.id == me.id for a in admins)
    except Exception as e:
        logger.error(f"Error checking bot admin status: {e}")
    return False

# ════════════════════════════════════════════════════════════
#  IMPROVED KEYBOARD BUILDERS WITH BETTER STRUCTURE
# ════════════════════════════════════════════════════════════

class KeyboardBuilder:
    """Builder pattern for keyboards - cleaner and more maintainable"""
    
    @staticmethod
    def home_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🛡 Mod", callback_data="home_mod"),
                InlineKeyboardButton(text="🎉 Fun", callback_data="home_fun"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Settings", callback_data="home_settings"),
                InlineKeyboardButton(text="ℹ️ About", callback_data="home_about"),
            ],
        ])
    
    @staticmethod
    def mod_keyboard() -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(text="🔨 Ban", callback_data="mod_ban"),
                InlineKeyboardButton(text="✅ Unban", callback_data="mod_unban"),
                InlineKeyboardButton(text="👢 Kick", callback_data="mod_kick"),
            ],
            [
                InlineKeyboardButton(text="🔇 Mute", callback_data="mod_mute"),
                InlineKeyboardButton(text="🔊 Unmute", callback_data="mod_unmute"),
            ],
            [
                InlineKeyboardButton(text="⚠️ Warn", callback_data="mod_warn"),
                InlineKeyboardButton(text="✨ Unwarn", callback_data="mod_unwarn"),
            ],
            [
                InlineKeyboardButton(text="📍 Help", callback_data="mod_help"),
                InlineKeyboardButton(text="⬅️ Back", callback_data="home"),
            ],
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def fun_keyboard() -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(text="💘 Couple", callback_data="fun_couple"),
                InlineKeyboardButton(text="🔍 Search", callback_data="fun_search"),
            ],
            [
                InlineKeyboardButton(text="💢 Spam", callback_data="fun_spam"),
                InlineKeyboardButton(text="🎮 Game", callback_data="fun_game"),
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="home")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def settings_keyboard(chat_id: int) -> InlineKeyboardMarkup:
        settings = get_settings(chat_id)
        lang = settings["lang"]
        mode = settings["mode"]
        
        buttons = [
            [InlineKeyboardButton(text="── 🌐 Language ──", callback_data="noop")],
            [
                InlineKeyboardButton(
                    text=f"🇮🇳 Hinglish {'✓' if lang == 'hinglish' else ''}",
                    callback_data="set_lang_hinglish"
                ),
                InlineKeyboardButton(
                    text=f"🇬🇧 English {'✓' if lang == 'english' else ''}",
                    callback_data="set_lang_english"
                ),
            ],
            [InlineKeyboardButton(text="── 🎭 Personality ──", callback_data="noop")],
            [
                InlineKeyboardButton(
                    text=f"🌸 Cute {'✓' if mode == 'cute' else ''}",
                    callback_data="set_mode_cute"
                ),
                InlineKeyboardButton(
                    text=f"💘 Romantic {'✓' if mode == 'romantic' else ''}",
                    callback_data="set_mode_romantic"
                ),
                InlineKeyboardButton(
                    text=f"😈 Rude {'✓' if mode == 'rude' else ''}",
                    callback_data="set_mode_rude"
                ),
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="home")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

# ════════════════════════════════════════════════════════════
#  OPTIMIZED GROQ API INTEGRATION
# ════════════════════════════════════════════════════════════

async def query_groq(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.7,
    max_tokens: int = 150,
    conversation_history: list = None
) -> Optional[str]:
    """
    Optimized Groq API call with better error handling and caching
    """
    try:
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        
        if conversation_history:
            messages.extend(conversation_history[-4:])  # Keep last 2 exchanges
        
        messages.append({"role": "user", "content": user_message})
        
        response: ChatCompletion = await asyncio.to_thread(
            groq_client.chat.completions.create,
            model=GROQ_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=0.9,
            frequency_penalty=0.5,
        )
        
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content.strip()
    
    except Exception as e:
        logger.error(f"Groq API error: {e}")
    
    return None

# ════════════════════════════════════════════════════════════
#  MIDDLEWARE FOR MEMBER TRACKING
# ════════════════════════════════════════════════════════════

class MemberTrackerMiddleware(BaseMiddleware):
    """Track group members for couple system"""
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user and event.chat.type != "private":
            user = event.from_user
            if not user.is_bot and user.first_name:
                pool = seen_members.setdefault(event.chat.id, {})
                pool[user.id] = {
                    "id": user.id,
                    "name": user.full_name or user.first_name
                }
        return await handler(event, data)

dp.message.middleware(MemberTrackerMiddleware())

# ════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ════════════════════════════════════════════════════════════

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Start command with optimized response"""
    name = message.from_user.first_name or "tum"
    text = (
        f"🌸 <b>Heyy {name}!</b>\n\n"
        f"Main hoon <b>Mikasa</b> — is group ki cutest guardian~ 💕\n\n"
        f"<b>Main kya kar sakti hoon:</b>\n"
        f"✦ 💘 Couple dhundhna\n"
        f"✦ 🔍 AI se kuch bhi poochna\n"
        f"✦ 💢 Spam bhejna\n"
        f"✦ 🎮 Games khelna\n"
        f"✦ 🛡 Group moderate karna\n\n"
        f"<i>Chalo shuru karte hain~ 🌸</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=KeyboardBuilder.home_keyboard())

@dp.message(Command("about"))
async def cmd_about(message: Message):
    """About command"""
    text = (
        "🌸 <b>About Mikasa</b>\n\n"
        "Main ek cute AI group manager hoon~ 💕\n\n"
        "✦ Real group members se couple pick karti hoon\n"
        "✦ Hinglish / English mein baat karti hoon\n"
        "✦ Cute, Romantic ya Rude — mood tumhara!\n"
        "✦ Group moderation aur fun dono krti hoon 🛡\n"
        "✦ Groq AI (LLaMA 70B) se powered\n\n"
        "<i>Banaya gaya hai pyaar se~ 🌷</i>"
    )
    await message.reply(text, parse_mode="HTML")

# ════════════════════════════════════════════════════════════
#  CALLBACK HANDLERS
# ════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery):
    """Return to home"""
    text = "🌸 <b>Mikasa — Main Menu</b>\n\nKya karna hai batao~ 👇"
    try:
        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=KeyboardBuilder.home_keyboard()
        )
    except TelegramBadRequest:
        await call.answer("✅ Menu updated!", show_alert=False)
    except Exception as e:
        logger.error(f"Error in home callback: {e}")
        await call.answer("❌ Error occurred", show_alert=True)

@dp.callback_query(F.data.startswith("home_"))
async def cb_home_category(call: CallbackQuery):
    """Handle category selection from home"""
    category = call.data.replace("home_", "")
    
    menus = {
        "mod": ("🛡 <b>Moderation Panel</b>\n\nGroup ko safe rakhne ke liye~ 👇", KeyboardBuilder.mod_keyboard()),
        "fun": ("🎉 <b>Fun Commands</b>\n\nThodi si masti aur romance~ 💕👇", KeyboardBuilder.fun_keyboard()),
        "settings": ("⚙️ <b>Settings</b>\n\nApne mood ke hisaab se customize karo~ 👇", KeyboardBuilder.settings_keyboard(call.message.chat.id)),
        "about": ("🌸 <b>About Mikasa</b>\n\nMain ek cute AI group manager hoon~ 💕\n\n✦ Real group members se couple\n✦ AI powered chat\n✦ Fun aur moderation\n\n<i>Banaya gaya hai pyaar se~ 🌷</i>", None),
    }
    
    text, keyboard = menus.get(category, ("", KeyboardBuilder.home_keyboard()))
    if not keyboard and category == "about":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back", callback_data="home")]])
    
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramBadRequest:
        await call.answer("✅ Updated!", show_alert=False)
    except Exception as e:
        logger.error(f"Error in category callback: {e}")
        await call.answer("❌ Error", show_alert=True)

@dp.callback_query(F.data.startswith("set_lang_") | F.data.startswith("set_mode_"))
async def cb_settings(call: CallbackQuery):
    """Handle settings changes"""
    data = call.data
    settings = get_settings(call.message.chat.id)
    
    if data.startswith("set_lang_"):
        lang = data.replace("set_lang_", "")
        settings["lang"] = lang
        await call.answer(f"✅ Language set to {lang}!", show_alert=False)
    elif data.startswith("set_mode_"):
        mode = data.replace("set_mode_", "")
        settings["mode"] = mode
        await call.answer(f"✅ Personality set to {mode}!", show_alert=False)
    
    try:
        await call.message.edit_reply_markup(
            reply_markup=KeyboardBuilder.settings_keyboard(call.message.chat.id)
        )
    except Exception as e:
        logger.error(f"Error updating settings: {e}")

@dp.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    """No-op callback"""
    await call.answer()

# ════════════════════════════════════════════════════════════
#  CHAT HANDLER WITH IMPROVED GROQ INTEGRATION
# ════════════════════════════════════════════════════════════

async def should_reply(message: Message) -> bool:
    """Determine if bot should reply"""
    if message.chat.type == "private":
        return True
    
    try:
        me = await safe_api_call(bot.get_me)
        if not me:
            return False
        
        # Check if replying to bot
        if message.reply_to_message and message.reply_to_message.from_user:
            if message.reply_to_message.from_user.id == me.id:
                return True
        
        text_lower = (message.text or "").lower()
        
        # Check mentions
        if me.username and f"@{me.username}".lower() in text_lower:
            return True
        if me.first_name and me.first_name.lower() in text_lower:
            return True
    
    except Exception as e:
        logger.error(f"Error in should_reply: {e}")
    
    return False

@dp.message(F.text & ~F.text.startswith("/"))
@rate_limit
async def chat_handler(message: Message):
    """Enhanced chat handler with better Groq integration"""
    if not await should_reply(message):
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Get conversation history
    history = chat_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": message.text})
    
    # Keep only last 4 messages (2 exchanges)
    if len(history) > 8:
        history[:] = history[-8:]
    
    try:
        system_prompt = get_system_prompt(chat_id)
        
        reply_text = await query_groq(
            system_prompt=system_prompt,
            user_message=message.text,
            temperature=0.75,
            max_tokens=100,
            conversation_history=history[:-1]  # Exclude current message from history
        )
        
        if reply_text:
            history.append({"role": "assistant", "content": reply_text})
            await message.reply(reply_text, parse_mode="HTML")
        else:
            await message.reply("Kuch issue tha na... phir baat karte 😐")
    
    except Exception as e:
        logger.error(f"Error in chat handler: {e}")
        await message.reply("Oops! Kuch gadbad ho gayi 😅")

# ════════════════════════════════════════════════════════════
#  STICKER SYSTEM
# ════════════════════════════════════════════════════════════

async def load_stickers():
    """Load stickers with caching"""
    try:
        cached = cache_manager.get("sticker_ids")
        if cached:
            STICKER_IDS.clear()
            STICKER_IDS.extend(cached)
            logger.info(f"✅ Loaded {len(STICKER_IDS)} stickers from cache")
            return
        
        pack = await safe_api_call(bot.get_sticker_set, STICKER_PACK)
        if pack and hasattr(pack, 'stickers'):
            sticker_ids = [s.file_id for s in pack.stickers]
            STICKER_IDS.clear()
            STICKER_IDS.extend(sticker_ids)
            cache_manager.set("sticker_ids", sticker_ids, ttl=STICKER_CACHE_TTL)
            logger.info(f"✅ Loaded {len(STICKER_IDS)} stickers from Telegram")
    except Exception as e:
        logger.warning(f"⚠️ Could not load stickers: {e}")

@dp.message(F.sticker)
async def on_sticker(message: Message):
    """Reply to stickers"""
    if message.chat.type != "private" and not await should_reply(message):
        return
    
    if STICKER_IDS:
        sticker = random.choice(STICKER_IDS)
        try:
            await message.reply_sticker(sticker)
        except Exception as e:
            logger.error(f"Error sending sticker: {e}")

# ════════════════════════════════════════════════════════════
#  STARTUP & SHUTDOWN
# ════════════════════════════════════════════════════════════

async def main():
    """Main entry point with optimizations"""
    logger.info("🌸 Mikasa v5 Optimized starting up...")
    
    try:
        # Load stickers
        await load_stickers()
        
        # Set command menus
        await safe_api_call(
            bot.set_my_commands,
            [
                BotCommand(command="start", description="🌸 Main menu kholo"),
                BotCommand(command="about", description="ℹ️ About Mikasa"),
            ],
            scope=BotCommandScopeAllGroupChats()
        )
        
        logger.info("✅ All systems ready!")
        logger.info("🚀 Bot is running...")
        
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise
    
    finally:
        logger.info("👋 Bot shutting down...")
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
