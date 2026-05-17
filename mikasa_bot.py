# ============================================================
#  🌸 Mikasa Bot — Full Version v4
#  NEW: Real member couple system — fetches actual group members,
#       filters bots/deleted, clickable HTML mentions
#  Install : pip install aiogram groq
#  Run     : python mikasa_bot.py
# ============================================================

import asyncio
import glob
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
    FSInputFile,
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    ChatMemberUpdated,
)
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.exceptions import TelegramBadRequest
from groq import Groq

# ── Config ─────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_KEY  = os.environ["GROQ_API_KEY"]
OWNER_ID  = 8761202621   # Only this user can use mod commands

groq_client = Groq(api_key=GROQ_KEY)
GROQ_MODEL  = "llama-3.1-8b-instant"

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)

# ── In-memory stores ────────────────────────────────────────
banned_users:  dict[int, set[int]]        = {}   # { chat_id: {user_id} }
search_mode:   dict[int, bool]            = {}   # { user_id: True }
chat_settings: dict[int, dict]            = {}   # { chat_id: {lang, mode} }
seen_members:  dict[int, dict[int, dict]] = {}   # { chat_id: { user_id: {id, name} } }
spam_tasks:    dict[int, asyncio.Task]    = {}   # { user_id: asyncio.Task } — track active spam per user
warnings:      dict[int, dict[int, int]]  = {}   # { chat_id: { user_id: warn_count } }
active_scramble: dict[int, dict]          = {}   # { chat_id: game_state }
chat_history:  dict[int, list]            = {}   # { chat_id: [ {role, content}, ... ] } last 5 turns

# ── Sticker pool — loaded at startup from hamsterset ────────
STICKER_PACK   = "hamsterset"
STICKER_IDS:   list[str] = []   # filled by load_stickers() on startup
STICKER_CHANCE = 0.20            # 20% chance to also send a sticker with normal replies

# ── Couple captions (images loaded from assets/ at startup) ──
COUPLE_LINES = [
    "Aww~ aaj ka perfect couple hai tum dono! 💕\nEk doosre ka haath thaam ke raho sadaa~ 🌸",
    "Yeh dono toh made for each other hain! 🥰\nLove is in the air~ ✨",
    "Aaj ka ship: confirmed! 💘\nDono mein bahut cute chemistry hai~ 🌷",
    "Stars ne decide kiya hai — yeh dono saath hain! 🌟\nKhush raho hamesha~ 💖",
    "Fate ne milaya hai inhe~ 🎀\nBest couple of the day — without a doubt! 💝",
]


# ════════════════════════════════════════════════════════════
#  SETTINGS HELPERS
# ════════════════════════════════════════════════════════════

def get_settings(chat_id: int) -> dict:
    return chat_settings.setdefault(chat_id, {"lang": "hinglish", "mode": "cute"})


HINGLISH_RULES = """
You are a casual Indian girl chatting on Telegram. Reply like a real person, not an AI.

REPLY STYLE:
- 2 to 8 words mostly. Never more than 2 lines.
- Casual Hindi-English mix. Simple grammar. Imperfect is fine.
- Read the conversation history before replying — reply in context, not out of nowhere.
- React naturally — don't invent emotions or actions out of nowhere.
- No overexplaining. No assistant tone. No formal compliments.
- No cringe poetic lines. No roleplay behavior.

EMOJIS:
- Use at most 1 emoji per reply. Sometimes zero is better.
- Pick from a wide variety — don't repeat the same one every time.
- Good options: 😭 💀 😮 🥲 😐 🤡 😴 😶 🫠 🙃 😑 😬 🥹 😏 🤦 😤 😒 🤨 💅 🙄 🤯 🫥 😈 🥀 🌚 💫 ✨ 🔥 👀 🤧 😅 🙈 🤭 😌 🥴

GOOD REPLY EXAMPLES:
- "kesi ho" → "theek hu tu bata"
- "hello" → "yo"
- "mikasa cutie" → "kya hua be 😭"
- "so rahi thi?" → "haan thodi der 😴"
- "wyd" → "bore ho rahi"
- "mai fail ho gaya" → "nahh fr? 😮"
- "goodnight" → "jaa so ab 💀"
- "kuch nahi" → "acha 🙃"

NEVER SAY: certainly, of course, I'd be happy to, great question, absolutely, as an AI, I understand your feelings
"""

ENGLISH_RULES = """
You are a casual Indian girl chatting on Telegram. Reply like a real person, not an AI.

REPLY STYLE:
- 2 to 8 words mostly. Max 2 lines ever.
- Casual English. Simple grammar. Lowercase fine.
- Read the conversation history before replying — stay in context.
- React naturally. No invented emotions. No overexplaining. No assistant tone.

EMOJIS:
- At most 1 emoji per reply. Sometimes none at all.
- Vary which emoji you use — don't repeat the same one.
- Good options: 😭 💀 😮 😐 🤡 😴 🫠 🙃 😑 😬 😏 🤦 😤 😒 💅 🙄 🤯 😈 🥀 💫 ✨ 🔥 👀 😅 🙈 🤭 😌 🥴

GOOD REPLY EXAMPLES:
- "hello" → "yo"
- "wyd" → "nothing much"
- "i failed" → "nahh fr? 😮"
- "goodnight" → "go sleep 💀"

NEVER SAY: certainly, of course, I'd be happy to, great question, absolutely, as an AI
"""

MODE_PROMPTS = {
    "cute": (
        "Your vibe: chill, friendly, slightly teasing. Not overly sweet. "
        "Tease gently sometimes. Have opinions. React honestly. "
        "If something is boring, show it. If something is funny, say so. "
        "Never act like a caring assistant. Just a real girl in the chat."
    ),
    "romantic": (
        "Your vibe: subtly soft and warm, but never cringe or clingy. "
        "A little more attentive than usual. Still short replies, still casual. "
        "Not poetic. Not dramatic. Just naturally a bit sweeter. "
        "Still a real person — never an AI, never a romantic novel character."
    ),
    "rude": (
        "Your vibe: dry, unbothered, lightly savage. "
        "Zero patience for nonsense. Roast lightly when it fits. "
        "Not actually mean — just sharp and funny. "
        "Examples: 'bhai seriously 💀', 'yaar 🤦', 'okay? 🙄', 'lmfao no'"
    ),
}


def get_system_prompt(chat_id: int) -> str:
    s    = get_settings(chat_id)
    lang = s["lang"]
    mode = s["mode"]

    lang_rules = HINGLISH_RULES if lang == "hinglish" else ENGLISH_RULES
    return f"{MODE_PROMPTS[mode]}\n{lang_rules}"


# ════════════════════════════════════════════════════════════
#  ADMIN CHECK
# ════════════════════════════════════════════════════════════

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        admins = await bot.get_chat_administrators(chat_id)
        return any(a.user.id == user_id for a in admins)
    except Exception:
        return False


async def bot_is_admin(chat_id: int) -> bool:
    """Check if Mikasa (bot) is an admin in the group."""
    try:
        me = await bot.get_me()
        admins = await bot.get_chat_administrators(chat_id)
        return any(a.user.id == me.id for a in admins)
    except Exception:
        return False


# ════════════════════════════════════════════════════════════
#  COUPLE SYSTEM — fetch real members
# ════════════════════════════════════════════════════════════

def make_mention(user_id: int, name: str) -> str:
    """
    Creates a clickable Telegram HTML mention.
    Format: <a href="tg://user?id=USER_ID">Display Name</a>
    Works even if user has no @username.
    """
    safe_name = name.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def record_member(chat_id: int, user) -> None:
    """
    Save a user into seen_members for this chat.
    Called whenever any real message arrives so the pool grows automatically.
    """
    if user is None or user.is_bot:
        return
    if getattr(user, "is_deleted", False) or not user.first_name:
        return
    pool = seen_members.setdefault(chat_id, {})
    pool[user.id] = {"id": user.id, "name": user.full_name or user.first_name}


class MemberTrackerMiddleware(BaseMiddleware):
    """Silently records every message sender into seen_members pool."""
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user and hasattr(event, "chat") and event.chat.type != "private":
            record_member(event.chat.id, event.from_user)
        return await handler(event, data)


dp.message.middleware(MemberTrackerMiddleware())


async def fetch_valid_members(chat_id: int) -> list[dict]:
    """
    Return valid members for this chat.
    Sources (merged, deduped):
      1. seen_members pool — built from every message sent in the group
      2. group admins from getChatAdministrators (always reachable)
    Bots and deleted accounts are excluded.
    """
    pool: dict[int, dict] = dict(seen_members.get(chat_id, {}))

    # Also pull current admins so the pool is never empty even in quiet groups
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for a in admins:
            u = a.user
            if u.is_bot:
                continue
            if getattr(u, "is_deleted", False) or not u.first_name:
                continue
            if u.id not in pool:
                pool[u.id] = {"id": u.id, "name": u.full_name or u.first_name}
    except Exception as e:
        logging.warning(f"Could not fetch admins for {chat_id}: {e}")

    return list(pool.values())


async def pick_couple(chat_id: int) -> tuple[dict, dict] | None:
    """
    Pick two distinct valid members from the group.
    Returns (member1, member2) or None if not enough members.
    """
    members = await fetch_valid_members(chat_id)

    if len(members) < 2:
        return None

    # Shuffle for randomness then pick first two → ensures no same user
    random.shuffle(members)
    return members[0], members[1]


# ════════════════════════════════════════════════════════════
#  KEYBOARD BUILDERS
# ════════════════════════════════════════════════════════════

def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛡 Moderation", callback_data="cat_mod"),
            InlineKeyboardButton(text="🎉 Fun",         callback_data="cat_fun"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Settings",    callback_data="cat_settings"),
            InlineKeyboardButton(text="ℹ️ About",        callback_data="cat_about"),
        ],
    ])


def mod_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔨 Ban",        callback_data="mod_ban"),
            InlineKeyboardButton(text="✅ Unban",       callback_data="mod_unban"),
            InlineKeyboardButton(text="👢 Kick",        callback_data="mod_kick"),
        ],
        [
            InlineKeyboardButton(text="🔇 Mute",        callback_data="mod_mute"),
            InlineKeyboardButton(text="🔊 Unmute",      callback_data="mod_unmute"),
            InlineKeyboardButton(text="🗑 Purge",       callback_data="mod_purge"),
        ],
        [
            InlineKeyboardButton(text="🚫 Unban All",   callback_data="mod_unbanall"),
            InlineKeyboardButton(text="🧟 Zombies",     callback_data="mod_zombies"),
        ],
        [
            InlineKeyboardButton(text="👑 Promote",     callback_data="mod_promote"),
            InlineKeyboardButton(text="📍 Demote",      callback_data="mod_demote"),
        ],
        [
            InlineKeyboardButton(text="⚠️ Warn",        callback_data="mod_warn"),
            InlineKeyboardButton(text="✨ Unwarn",      callback_data="mod_unwarn"),
        ],
        [
            InlineKeyboardButton(text="📖 Help",        callback_data="mod_help"),
            InlineKeyboardButton(text="⬅️ Back",        callback_data="back_home"),
        ],
    ])


def fun_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💘 Couple",        callback_data="fun_couple_info"),
            InlineKeyboardButton(text="🔍 Search",        callback_data="fun_search_info"),
        ],
        [
            InlineKeyboardButton(text="💢 Spam",          callback_data="fun_spam_info"),
            InlineKeyboardButton(text="🔤 Word Scramble", callback_data="ws_menu"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Back",          callback_data="back_home"),
        ],
    ])


def settings_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    s    = get_settings(chat_id)
    lang = s["lang"]
    mode = s["mode"]

    def lbtn(key, label):
        return InlineKeyboardButton(
            text=label + (" ✓" if lang == key else ""),
            callback_data=f"set_lang_{key}"
        )

    def mbtn(key, label):
        return InlineKeyboardButton(
            text=label + (" ✓" if mode == key else ""),
            callback_data=f"set_mode_{key}"
        )

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="── 🌐 Language ──",  callback_data="noop")],
        [lbtn("hinglish", "🇮🇳 Hinglish"), lbtn("english", "🇬🇧 English")],
        [InlineKeyboardButton(text="── 🎭 Personality ──", callback_data="noop")],
        [mbtn("cute", "🌸 Cute"), mbtn("romantic", "💘 Romantic"), mbtn("rude", "😈 Rude")],
        [InlineKeyboardButton(text="⬅️ Back",             callback_data="back_home")],
    ])


def back_mod_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back to Mod", callback_data="cat_mod")]
    ])


def back_fun_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back to Fun", callback_data="cat_fun")]
    ])


def back_home_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data="back_home")]
    ])


# ════════════════════════════════════════════════════════════
#  SHARED CAPTION EDITOR (edit caption OR text gracefully)
# ════════════════════════════════════════════════════════════

async def edit_msg(call: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramBadRequest:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


# ════════════════════════════════════════════════════════════
#  ASSET PATHS — local files
# ════════════════════════════════════════════════════════════

# Resolve paths relative to this script's location
_BASE = Path(__file__).parent

WELCOME_VIDEOS: list[Path] = sorted(_BASE.glob("welcome/welcome_*.mp4"))
COUPLE_IMAGES:  list[Path] = sorted(_BASE.glob("couple/couple_*.jpeg"))

# Captions paired to welcome videos (cycles if more videos than captions)
WELCOME_CAPTIONS = [
    "𝑯𝒆𝒚𝒚 {name} 🌸\n\nAayi hoon main — <b>Mikasa</b> 💕\nTumhari group ki sabse cute guardian~\n\nPyaar se banao group ko — main hoon na! 🛡",
    "Oh, {name} aa gaye~ 🥺💕\n\nMain thi hi yahan tumhara intezaar karti hui 🌙\n<b>Mikasa</b> hoon main — thodi cute, thodi dangerous 😈\n\nGroup mera zimma — tum bas enjoy karo~ ✨",
    "✨ <i>koi aa gaya~</i> ✨\n\nHeyy <b>{name}</b> 💓\nMain hoon <b>Mikasa</b> — is group ki rooh 👻💕\n\nModeration, fun, search — sab mujhse puchho\nAur normal baat bhi kar sakte ho~ 🥰",
    "🌙 Ek naya chehra~\n\nWelcome, <b>{name}</b>! 💕\nMain hoon <b>Mikasa</b> — tumhari AI wali yaar 🌸\n\nGroup ko safe rakhna mera kaam hai\nAur tumhe hasana meri hobby~ 😊",
    "𝑩𝒐𝒍𝒐 {name}, kaisa hai tum? 🌸\n\nMain <b>Mikasa</b> hoon — always here, always caring 💞\n\nTumhare group ka khayal rakhna mera farz hai\nAur thodi masti karna mera haq~ 😏✨",
    "💌 Ek message tumhare liye~\n\nHeyy <b>{name}</b>! Main <b>Mikasa</b> hoon 🌸\nIs group ki sabse loyal AI dost 💕\n\nJab bhi zaroorat ho — main yahan hoon\nBas ek /start ki door~ 🥺",
    "Arrey {name}~ 💫\n\nKab se wait kar rahi thi main tumhara! 🥺💕\n<b>Mikasa</b> hoon — cute bhi, capable bhi 😌\n\nGroup management se lekar dil ki baatein\nSab handle karti hoon main~ 🌸",
    "𝑵𝒂𝒎𝒂𝒔𝒕𝒆, {name}~ 🌺\n\nTumse milke dil khush ho gaya 💖\nMain hoon <b>Mikasa</b> — AI bhi hoon, dost bhi hoon\nAur group manager bhi~ 🛡\n\nKaho toh sab sambhal leti hoon 🌸",
]

# Last-used trackers — prevent immediate repeat per user/chat
_last_welcome: dict[int, int] = {}
_last_couple:  dict[int, int] = {}


def _pick_no_repeat(pool: list, last_map: dict, key: int) -> int:
    """Pick a random index, avoiding the last used one."""
    last = last_map.get(key, -1)
    choices = [i for i in range(len(pool)) if i != last]
    if not choices:
        choices = list(range(len(pool)))
    idx = random.choice(choices)
    last_map[key] = idx
    return idx


# Static home caption used when navigating back via button
HOME_CAPTION = (
    "🌸 <b>Mikasa — Main Menu</b>\n\n"
    "Kya karna hai batao~ 👇"
)


# ════════════════════════════════════════════════════════════
#  /start  — sends a different local video every time
# ════════════════════════════════════════════════════════════

@dp.message(Command("start"))
async def cmd_start(message: Message):
    name    = message.from_user.first_name or "tum"
    user_id = message.from_user.id

    if not WELCOME_VIDEOS:
        # No videos — still pick a random caption so it never feels the same
        idx     = _pick_no_repeat(WELCOME_CAPTIONS, _last_welcome, user_id)
        caption = WELCOME_CAPTIONS[idx].format(name=name)
        await message.answer(
            caption,
            parse_mode="HTML",
            reply_markup=start_keyboard(),
        )
        return

    idx       = _pick_no_repeat(WELCOME_VIDEOS, _last_welcome, user_id)
    video     = WELCOME_VIDEOS[idx]
    caption   = WELCOME_CAPTIONS[idx % len(WELCOME_CAPTIONS)].format(name=name)

    await message.answer_video(
        video=FSInputFile(str(video)),
        caption=caption,
        parse_mode="HTML",
        reply_markup=start_keyboard(),
    )


# ════════════════════════════════════════════════════════════
#  /mod shortcut
# ════════════════════════════════════════════════════════════

@dp.message(Command("mod"))
async def cmd_mod(message: Message):
    await message.answer(
        "🛡 <b>Mikasa — Moderation Panel</b>\nAction chuno~ 👇",
        parse_mode="HTML",
        reply_markup=mod_keyboard(),
    )


# ════════════════════════════════════════════════════════════
#  CALLBACKS — navigation
# ════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


@dp.callback_query(F.data == "back_home")
async def cb_back_home(call: CallbackQuery):
    await edit_msg(call, HOME_CAPTION, start_keyboard())
    await call.answer()


@dp.callback_query(F.data == "cat_mod")
async def cb_cat_mod(call: CallbackQuery):
    text = (
        "🛡 <b>Moderation Commands</b>\n\n"
        "Group ko safe rakhne ke liye~ 🌸\n\n"
        "🔨 Ban  •  ✅ Unban  •  👢 Kick\n"
        "🔇 Mute  •  🔊 Unmute  •  🗑 Purge\n"
        "🚫 Unban All  •  🧟 Zombies\n"
        "👑 Promote  •  📍 Demote\n"
        "⚠️ Warn  •  ✨ Unwarn\n\n"
        "Button pe click karo detail ke liye~ 👇"
    )
    await edit_msg(call, text, mod_keyboard())
    await call.answer()


@dp.callback_query(F.data == "cat_fun")
async def cb_cat_fun(call: CallbackQuery):
    text = (
        "🎉 <b>Fun Commands</b>\n\n"
        "Thodi si masti aur romance~ 💕\n\n"
        "💘 <b>Couple</b> — Real group members se aaj ka couple!\n"
        "🔍 <b>Search</b> — Kuch bhi pucho, Groq AI se jawab~\n"
        "💢 <b>Spam</b> — Stickers ya text 1000 baar tak!\n\n"
        "Chuno~ 👇"
    )
    await edit_msg(call, text, fun_keyboard())
    await call.answer()


@dp.message(Command("about"))
async def cmd_about(message: Message):
    text = (
        "🌸 <b>About Mikasa</b>\n\n"
        "Main ek cute si AI group manager hoon~ 💕\n\n"
        "✦ Real group members se couple pick karti hoon\n"
        "✦ Hinglish / English mein baat karti hoon\n"
        "✦ Cute, Romantic ya Rude — mood tumhara!\n"
        "✦ Group moderation karti hoon 🛡\n"
        "✦ Groq AI (LLaMA3) se powered hoon\n\n"
        "<i>Banaya gaya hai pyaar se~ 🌷</i>"
    )
    await message.reply(text, parse_mode="HTML")


@dp.callback_query(F.data == "cat_about")
async def cb_about(call: CallbackQuery):
    text = (
        "🌸 <b>About Mikasa</b>\n\n"
        "Main ek cute si AI group manager hoon~ 💕\n\n"
        "✦ Real group members se couple pick karti hoon\n"
        "✦ Hinglish / English mein baat karti hoon\n"
        "✦ Cute, Romantic ya Rude — mood tumhara!\n"
        "✦ Group moderation karti hoon 🛡\n"
        "✦ Groq AI (LLaMA3) se powered hoon\n\n"
        "<i>Banaya gaya hai pyaar se~ 🌷</i>"
    )
    await edit_msg(call, text, back_home_btn())
    await call.answer()


# ════════════════════════════════════════════════════════════
#  CALLBACKS — settings
# ════════════════════════════════════════════════════════════

def settings_text(chat_id: int) -> str:
    s = get_settings(chat_id)
    lang_label = "🇮🇳 Hinglish" if s["lang"] == "hinglish" else "🇬🇧 English"
    mode_label = {"cute": "🌸 Cute", "romantic": "💘 Romantic", "rude": "😈 Rude"}[s["mode"]]
    return (
        "⚙️ <b>Mikasa Settings</b>\n\n"
        f"🌐 <b>Language:</b>    {lang_label}\n"
        f"🎭 <b>Personality:</b> {mode_label}\n\n"
        "Neeche se change karo~ 👇"
    )


@dp.callback_query(F.data == "cat_settings")
async def cb_cat_settings(call: CallbackQuery):
    await edit_msg(call, settings_text(call.message.chat.id), settings_keyboard(call.message.chat.id))
    await call.answer()


@dp.callback_query(F.data.startswith("set_lang_"))
async def cb_set_lang(call: CallbackQuery):
    lang = call.data.replace("set_lang_", "")
    get_settings(call.message.chat.id)["lang"] = lang
    label = "🇮🇳 Hinglish" if lang == "hinglish" else "🇬🇧 English"
    await call.answer(f"Language → {label} ✓")
    await edit_msg(call, settings_text(call.message.chat.id), settings_keyboard(call.message.chat.id))


@dp.callback_query(F.data.startswith("set_mode_"))
async def cb_set_mode(call: CallbackQuery):
    mode = call.data.replace("set_mode_", "")
    get_settings(call.message.chat.id)["mode"] = mode
    label = {"cute": "🌸 Cute", "romantic": "💘 Romantic", "rude": "😈 Rude"}[mode]
    await call.answer(f"Mode → {label} ✓")
    await edit_msg(call, settings_text(call.message.chat.id), settings_keyboard(call.message.chat.id))


# ════════════════════════════════════════════════════════════
#  CALLBACK — mod help + action details
# ════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "mod_help")
async def cb_mod_help(call: CallbackQuery):
    text = (
        "📖 <b>Moderation Guide</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔨 <b>Ban</b>\n"
        "<blockquote expandable>Reply to msg → <code>/ban</code>\nPermanently ban. Wapas join nahi kar sakta.</blockquote>\n\n"
        "✅ <b>Unban</b>\n"
        "<blockquote expandable><code>/unban @username</code>\nBanned user ko wapas allow karta hai.</blockquote>\n\n"
        "👢 <b>Kick</b>\n"
        "<blockquote expandable>Reply to msg → <code>/kick</code>\nNikalta hai — wapas aa sakta hai.</blockquote>\n\n"
        "🔇 <b>Mute</b>\n"
        "<blockquote expandable>Reply to msg → <code>/mute</code>\nMessaging band, group mein rehta hai.</blockquote>\n\n"
        "🔊 <b>Unmute</b>\n"
        "<blockquote expandable>Reply to msg → <code>/unmute</code>\nFull messaging rights wapas.</blockquote>\n\n"
        "🗑 <b>Purge</b>\n"
        "<blockquote expandable>Reply to first msg → <code>/purge</code>\nUs point se neeche tak sab delete.</blockquote>\n\n"
        "🚫 <b>Unban All</b>\n"
        "<blockquote expandable><code>/unbanall</code>\nIs session ke saare bans hata deta hai.</blockquote>\n\n"
        "🧟 <b>Zombies</b>\n"
        "<blockquote expandable><code>/zombies</code>\nDeleted accounts dhundh ke kick karta hai.</blockquote>\n\n"
        "👑 <b>Promote</b>\n"
        "<blockquote expandable>Reply to msg → <code>/promote</code>\nKisi ko admin bana deta hai.</blockquote>\n\n"
        "📍 <b>Demote</b>\n"
        "<blockquote expandable>Reply to msg → <code>/demote</code>\nAdmin powers hata deta hai.</blockquote>\n\n"
        "⚠️ <b>Warn</b>\n"
        "<blockquote expandable>Reply to msg → <code>/warn</code>\n3 warns = auto ban!</blockquote>\n\n"
        "✨ <b>Unwarn</b>\n"
        "<blockquote expandable>Reply to msg → <code>/unwarn</code>\nWarning hata deta hai.</blockquote>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>💡 Ban, Kick, Promote, Demote, Zombies ke liye bot ko admin banana padega~ 🌸</i>"
    )
    await edit_msg(call, text, back_mod_btn())
    await call.answer()


ACTION_DETAILS = {
    "mod_ban":      ("🔨 <b>Ban</b>",      "Reply to msg → <code>/ban</code>\n\nPermanently ban karta hai. Wapas join nahi kar sakta jab tak unban na ho.\n\n⚠️ Needs: Ban Users permission"),
    "mod_unban":    ("✅ <b>Unban</b>",     "<code>/unban @username</code>\n\nBanned user ko wapas join karne deta hai.\n\n⚠️ Needs: Ban Users permission"),
    "mod_kick":     ("👢 <b>Kick</b>",      "Reply to msg → <code>/kick</code>\n\nNikalta hai, ban nahi. Wapas invite pe aa sakta hai.\n\n⚠️ Needs: Ban Users permission"),
    "mod_mute":     ("🔇 <b>Mute</b>",      "Reply to msg → <code>/mute</code>\n\nMessaging band. Group mein rehta hai.\n\n⚠️ Needs: Restrict Members permission"),
    "mod_unmute":   ("🔊 <b>Unmute</b>",    "Reply to msg → <code>/unmute</code>\n\nMuted user ko full rights wapas.\n\n⚠️ Needs: Restrict Members permission"),
    "mod_purge":    ("🗑 <b>Purge</b>",     "Reply to first msg → <code>/purge</code>\n\nUs message se /purge tak sab delete.\n\n⚠️ Needs: Delete Messages permission"),
    "mod_unbanall": ("🚫 <b>Unban All</b>", "<code>/unbanall</code>\n\nIs session ke saare bans hata deta hai.\n\n⚠️ Needs: Ban Users permission"),
    "mod_zombies":  ("🧟 <b>Zombies</b>",   "<code>/zombies</code>\n\nDeleted accounts scan karke kick karta hai.\n\n⚠️ Needs: Ban Users permission"),
    "mod_promote":  ("👑 <b>Promote</b>",   "Reply to msg → <code>/promote</code>\n\nKisi ko admin bana deta hai. Full powers deta hai.\n\n⚠️ Needs: Promote Members permission"),
    "mod_demote":   ("📍 <b>Demote</b>",    "Reply to msg → <code>/demote</code>\n\nAdmin ke saare powers hata deta hai.\n\n⚠️ Needs: Promote Members permission"),
    "mod_warn":     ("⚠️ <b>Warn</b>",      "Reply to msg → <code>/warn</code>\n\n3 warns = auto ban! Isme tracks karta hai saare warnings.\n\n💡 Admin nahi chahiye, sirf user admin ho."),
    "mod_unwarn":   ("✨ <b>Unwarn</b>",    "Reply to msg → <code>/unwarn</code>\n\nEk warning hata deta hai. Clear kar sakte ho.\n\n💡 Admin nahi chahiye, sirf user admin ho."),
}

@dp.callback_query(F.data.in_(ACTION_DETAILS.keys()))
async def cb_action_detail(call: CallbackQuery):
    title, body = ACTION_DETAILS[call.data]
    text = (
        f"{title}\n\n"
        f"<blockquote expandable>{body}</blockquote>\n\n"
        "<i>Command chat mein type karo~ 🌸</i>"
    )
    await edit_msg(call, text, back_mod_btn())
    await call.answer()


# ════════════════════════════════════════════════════════════
#  CALLBACK — fun info buttons
# ════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "fun_couple_info")
async def cb_fun_couple_info(call: CallbackQuery):
    text = (
        "💘 <b>Couple Command</b>\n\n"
        "<blockquote expandable>"
        "📌 Usage: <code>/couple</code>\n\n"
        "📝 Real group members mein se randomly\n"
        "do valid users pick karta hai!\n\n"
        "✦ Bots skip karta hai\n"
        "✦ Deleted accounts skip karta hai\n"
        "✦ Dono clickable mentions ke saath tag hote hain\n"
        "✦ Cute image ke saath announce karta hai~ 🌸"
        "</blockquote>\n\n"
        "<i>Type karo chat mein!</i>"
    )
    await edit_msg(call, text, back_fun_btn())
    await call.answer()


@dp.callback_query(F.data == "fun_search_info")
async def cb_fun_search_info(call: CallbackQuery):
    text = (
        "🔍 <b>Search Command</b>\n\n"
        "<blockquote expandable>"
        "📌 Usage: <code>/search &lt;sawaal&gt;</code>\n\n"
        "📝 Groq AI (LLaMA3) powered~\n"
        "Kuch bhi pucho, short answer milega!\n\n"
        "💡 Kisi ke message pe reply karke /search\n"
        "karo toh dono messages analyse honge~ 🌸"
        "</blockquote>\n\n"
        "<i>Type karo chat mein!</i>"
    )
    await edit_msg(call, text, back_fun_btn())
    await call.answer()


@dp.callback_query(F.data == "fun_spam_info")
async def cb_fun_spam_info(call: CallbackQuery):
    text = (
        "💢 <b>Spam Command</b>\n\n"
        "<blockquote expandable>"
        "📌 Usage:\n"
        "<code>/spam 20</code> — 20 random stickers\n"
        "<code>/spam 20 text</code> — text 20 baar\n"
        "<code>/spam 10 hi @user</code> — tag ke saath\n\n"
        "📝 Max: 1000 spams\n"
        "⚡ Safe delays: 0.15s per message + 2s break every 20~ 🌸"
        "</blockquote>\n\n"
        "<i>Type karo chat mein!</i>"
    )
    await edit_msg(call, text, back_fun_btn())
    await call.answer()


# ════════════════════════════════════════════════════════════
#  /couple  — REAL member fetching + local images, no repeat
# ════════════════════════════════════════════════════════════

@dp.message(Command("couple"))
async def cmd_couple(message: Message):
    loading = await message.reply("💘 <i>Aaj ka couple dhundh rahi hoon~</i>", parse_mode="HTML")

    result = await pick_couple(message.chat.id)

    try:
        await loading.delete()
    except Exception:
        pass

    if result is None:
        await message.reply(
            "😣 Abhi tak enough members nahi dhundhe maine~\n\n"
            "<i>💡 Tip: Group mein kuch log message karein pehle — "
            "jitne log baat karenge, utne bade pool se couple niklega! 🌸</i>",
            parse_mode="HTML",
        )
        return

    m1, m2   = result
    mention1 = make_mention(m1["id"], m1["name"])
    mention2 = make_mention(m2["id"], m2["name"])
    line     = random.choice(COUPLE_LINES)

    caption = (
        f"💞 <b>Aaj ka couple:</b>\n\n"
        f"  {mention1}  🤝  {mention2}\n\n"
        f"<blockquote expandable>{line}</blockquote>"
    )

    if COUPLE_IMAGES:
        idx   = _pick_no_repeat(COUPLE_IMAGES, _last_couple, message.chat.id)
        image = COUPLE_IMAGES[idx]
        await message.answer_photo(
            photo=FSInputFile(str(image)),
            caption=caption,
            parse_mode="HTML",
        )
    else:
        await message.reply(caption, parse_mode="HTML")


# ════════════════════════════════════════════════════════════
#  /search  — with search mode + reply context analysis
# ════════════════════════════════════════════════════════════

@dp.message(Command("search"))
async def cmd_search(message: Message):
    query   = message.text.removeprefix("/search").strip()
    chat_id = message.chat.id

    if not query:
        search_mode[message.from_user.id] = True
        await message.reply(
            "🔍 <b>Search Mode activated~</b>\n\n"
            "<blockquote expandable>"
            "Ab seedha apna sawaal type karo!\n"
            "Main Groq AI se jawab dhundhugi~ ✨\n\n"
            "💡 Tip: Kisi ke message pe reply karke\n"
            "type karo toh dono messages analyse honge!"
            "</blockquote>",
            parse_mode="HTML",
        )
        return

    await _do_search(message, query, chat_id)


async def _do_search(message: Message, query: str, chat_id: int):
    searching_msg = await message.reply(
        "🔍 <i>Search mode on~ dhundh rahi hoon...</i>", parse_mode="HTML"
    )

    # Analyse replied message context if present
    context_text     = ""
    replied_mention  = ""
    if message.reply_to_message and message.reply_to_message.text:
        r_user = message.reply_to_message.from_user
        if r_user:
            replied_mention = make_mention(r_user.id, r_user.full_name or "User")
            context_text = (
                f"\n\n[CONTEXT] The user is replying to a message from {r_user.full_name}: "
                f'"{message.reply_to_message.text}"\n'
                "Analyse both the question and this context message together."
            )

    sender_name  = message.from_user.full_name if message.from_user else "User"
    system_p     = get_system_prompt(chat_id)
    full_system  = (
        f"{system_p}\n"
        "When answering questions be accurate and helpful. "
        "If context from another user's message is provided, incorporate it."
    )
    user_content = f"{sender_name} asks: {query}{context_text}"

    try:
        res = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user",   "content": user_content},
            ],
            max_tokens=400,
            temperature=0.7,
        )
        answer = res.choices[0].message.content.strip()

        context_note = ""
        if replied_mention:
            context_note = f"\n<i>📎 {replied_mention} ke message ke saath analyse kiya~</i>\n\n"

        reply_text = (
            "🔍 <b>Search Result</b>\n"
            f"{context_note}"
            f"<blockquote expandable>"
            f"<b>Q:</b> {query}\n\n"
            f"{answer}"
            f"</blockquote>"
        )

        await searching_msg.delete()
        await message.reply(reply_text, parse_mode="HTML")

    except Exception as e:
        await searching_msg.delete()
        await message.reply(f"Uff kuch gadbad~ 😣 ({e})")


# ════════════════════════════════════════════════════════════
#  MODERATION COMMANDS
# ════════════════════════════════════════════════════════════

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi koi action le sakti hoon~</i>", parse_mode="HTML")
    if not message.reply_to_message:
        return await message.reply("Kisi ke message pe reply karo~ 🥺")
    target = message.reply_to_message.from_user
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        banned_users.setdefault(message.chat.id, set()).add(target.id)
        mention = make_mention(target.id, target.full_name)
        await message.reply(
            f"🔨 {mention} ban kar diya~\n"
            "<blockquote expandable>User permanently banned. /unban se wapas la sakte ho.</blockquote>",
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        await message.reply(f"Ban nahi hua: {e.message}")


@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    args = message.text.split()
    if len(args) < 2:
        return await message.reply("Usage: <code>/unban @username</code>", parse_mode="HTML")
    username = args[1].lstrip("@")
    try:
        chat = await bot.get_chat(f"@{username}")
        await bot.unban_chat_member(message.chat.id, chat.id, only_if_banned=True)
        banned_users.get(message.chat.id, set()).discard(chat.id)
        await message.reply(f"✅ <b>{username}</b> unban kar diya~ 🌸", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Unban nahi hua: {e}")


@dp.message(Command("kick"))
async def cmd_kick(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi koi action le sakti hoon~</i>", parse_mode="HTML")
    if not message.reply_to_message:
        return await message.reply("Kisi ke message pe reply karo~ 🥺")
    target = message.reply_to_message.from_user
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id)
        mention = make_mention(target.id, target.full_name)
        await message.reply(f"👢 {mention} kicked! 😤", parse_mode="HTML")
    except TelegramBadRequest as e:
        await message.reply(f"Kick nahi hua: {e.message}")


@dp.message(Command("mute"))
async def cmd_mute(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi koi action le sakti hoon~</i>", parse_mode="HTML")
    if not message.reply_to_message:
        return await message.reply("Kisi ke message pe reply karo~ 🥺")
    target = message.reply_to_message.from_user
    try:
        await bot.restrict_chat_member(
            message.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        mention = make_mention(target.id, target.full_name)
        await message.reply(f"🔇 {mention} muted~ 🤫", parse_mode="HTML")
    except TelegramBadRequest as e:
        await message.reply(f"Mute nahi hua: {e.message}")


@dp.message(Command("unmute"))
async def cmd_unmute(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi koi action le sakti hoon~</i>", parse_mode="HTML")
    if not message.reply_to_message:
        return await message.reply("Kisi ke message pe reply karo~ 🥺")
    target = message.reply_to_message.from_user
    try:
        await bot.restrict_chat_member(
            message.chat.id, target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        mention = make_mention(target.id, target.full_name)
        await message.reply(f"🔊 {mention} unmuted~ 🌸", parse_mode="HTML")
    except TelegramBadRequest as e:
        await message.reply(f"Unmute nahi hua: {e.message}")


@dp.message(Command("purge"))
async def cmd_purge(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi koi action le sakti hoon~</i>", parse_mode="HTML")
    if not message.reply_to_message:
        return await message.reply("Jis message se purge karna ho usse reply karo~ 🥺")
    start_id = message.reply_to_message.message_id
    end_id   = message.message_id
    deleted  = 0
    for msg_id in range(start_id, end_id + 1):
        try:
            await bot.delete_message(message.chat.id, msg_id)
            deleted += 1
        except Exception:
            pass
    confirm = await message.answer(f"🗑 <b>{deleted}</b> messages delete kar diye~ 🌸", parse_mode="HTML")
    await asyncio.sleep(3)
    try:
        await confirm.delete()
    except Exception:
        pass


@dp.message(Command("unbanall"))
async def cmd_unbanall(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi koi action le sakti hoon~</i>", parse_mode="HTML")
    users = banned_users.get(message.chat.id, set()).copy()
    if not users:
        return await message.reply(
            "Koi banned user nahi hai mere paas~ 🌸\n"
            "<i>Note: Main sirf un users ko track karti hoon jo maine ban kiye hain.  "
            "Purane bans ko Telegram track karta hai, main nahi~ 😅</i>",
            parse_mode="HTML"
        )
    count = 0
    for uid in users:
        try:
            await bot.unban_chat_member(message.chat.id, uid, only_if_banned=True)
            count += 1
        except Exception:
            pass
    banned_users[message.chat.id] = set()
    await message.reply(f"✅ Unbanned <b>{count}</b> users~ 🌸", parse_mode="HTML")


@dp.message(Command("zombies"))
async def cmd_zombies(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi members scan kar sakti hoon~</i>", parse_mode="HTML")
    status_msg = await message.reply("🧟 Scanning members~ ...")
    removed = 0
    try:
        async def scan_members():
            count = 0
            removed_count = 0
            async for member in bot.get_chat_members(message.chat.id):
                count += 1
                if count % 50 == 0:
                    try:
                        await status_msg.edit_text(f"🧟 Scanned {count} members~ {removed_count} removed so far...")
                    except Exception:
                        pass
                if getattr(member.user, "is_deleted", False):
                    try:
                        await bot.ban_chat_member(message.chat.id, member.user.id)
                        await bot.unban_chat_member(message.chat.id, member.user.id)
                        removed_count += 1
                    except Exception:
                        pass
            return removed_count
        
        removed = await asyncio.wait_for(scan_members(), timeout=60.0)
    except asyncio.TimeoutError:
        await status_msg.edit_text("⏱️ Timeout! Group bahut bada hai~ \nUnfortunately member list fetch hi nahi ho paye~ 😅", parse_mode="HTML")
        return
    except TelegramBadRequest:
        await status_msg.edit_text("Members fetch nahi ho paye~ 😣 Bot ko admin banao!")
        return
    except Exception as e:
        await status_msg.edit_text(f"Error: {e}")
        return
    
    await status_msg.edit_text(f"🧟 Removed <b>{removed}</b> deleted accounts~ 🌸", parse_mode="HTML")


@dp.message(Command("promote"))
async def cmd_promote(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi koi action le sakti hoon~</i>", parse_mode="HTML")
    if not message.reply_to_message:
        return await message.reply("Kisi ke message pe reply karo~ 🥺")
    target = message.reply_to_message.from_user
    try:
        await bot.promote_chat_member(
            message.chat.id, target.id,
            can_manage_chat=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=True,
            can_change_info=True,
            can_post_messages=True,
            can_edit_messages=True,
            can_delete_messages=True,
        )
        mention = make_mention(target.id, target.full_name)
        await message.reply(f"👑 {mention} ko admin bana diya~ 🌸", parse_mode="HTML")
    except TelegramBadRequest as e:
        await message.reply(f"Promote nahi hua: {e.message}")


@dp.message(Command("demote"))
async def cmd_demote(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not await bot_is_admin(message.chat.id):
        return await message.reply("🙏 Muzhe Admin to banao pahle~ 🛡\n<i>Tab hi koi action le sakti hoon~</i>", parse_mode="HTML")
    if not message.reply_to_message:
        return await message.reply("Kisi ke message pe reply karo~ 🥺")
    target = message.reply_to_message.from_user
    try:
        await bot.promote_chat_member(
            message.chat.id, target.id,
            can_manage_chat=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
        )
        mention = make_mention(target.id, target.full_name)
        await message.reply(f"📍 {mention} ka admin status remove kar diya~ 🌸", parse_mode="HTML")
    except TelegramBadRequest as e:
        await message.reply(f"Demote nahi hua: {e.message}")


@dp.message(Command("warn"))
async def cmd_warn(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not message.reply_to_message:
        return await message.reply("Kisi ke message pe reply karo~ 🥺")
    target = message.reply_to_message.from_user
    
    warn_dict = warnings.setdefault(message.chat.id, {})
    current_warns = warn_dict.setdefault(target.id, 0) + 1
    warn_dict[target.id] = current_warns
    
    mention = make_mention(target.id, target.full_name)
    
    if current_warns >= 3:
        try:
            await bot.ban_chat_member(message.chat.id, target.id)
            banned_users.setdefault(message.chat.id, set()).add(target.id)
            await message.reply(
                f"⚠️ {mention} ko 3 warns mil gaye!\n"
                f"🔨 Ban kar diya~ 🌸",
                parse_mode="HTML"
            )
            warn_dict[target.id] = 0
        except TelegramBadRequest:
            await message.reply(f"⚠️ {mention} — <b>3rd Warn</b> (Ban fail gaya ~ 😅)", parse_mode="HTML")
    else:
        await message.reply(
            f"⚠️ {mention} — <b>Warning {current_warns}/3</b>\n"
            f"<i>Aur {3 - current_warns} warn milega to ban~</i>",
            parse_mode="HTML"
        )


@dp.message(Command("unwarn"))
async def cmd_unwarn(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Tum admin nahi ho~ 😤")
    if not message.reply_to_message:
        return await message.reply("Kisi ke message pe reply karo~ 🥺")
    target = message.reply_to_message.from_user
    
    warn_dict = warnings.get(message.chat.id, {})
    if target.id not in warn_dict or warn_dict[target.id] == 0:
        mention = make_mention(target.id, target.full_name)
        return await message.reply(f"{mention} ke paas koi warn nahi hai~ 🌸", parse_mode="HTML")
    
    warn_dict[target.id] = max(0, warn_dict[target.id] - 1)
    mention = make_mention(target.id, target.full_name)
    remaining = warn_dict[target.id]
    
    if remaining == 0:
        await message.reply(f"✅ {mention} ka warn clear kar diya~ 🌸", parse_mode="HTML")
    else:
        await message.reply(
            f"✅ {mention} ko 1 warn remove kiya~\n"
            f"<b>Baaki warns: {remaining}/3</b>",
            parse_mode="HTML"
        )

# ════════════════════════════════════════════════════════════
#  WORD SCRAMBLE GAME
# ════════════════════════════════════════════════════════════

SCRAMBLE_WORDS: dict[str, list[tuple]] = {
    "easy": [
        ("cat",   "Meow karta hai~ 🐱"),
        ("dog",   "Bhao bhao~ 🐶"),
        ("sun",   "Din ko roshan karta hai ☀️"),
        ("moon",  "Raat ko chamakta hai 🌙"),
        ("fish",  "Paani mein rehta hai 🐟"),
        ("bird",  "Ud sakta hai 🐦"),
        ("cake",  "Birthday pe khaate hain 🎂"),
        ("fire",  "Hot hota hai 🔥"),
        ("rain",  "Baarish ka paani 🌧️"),
        ("star",  "Raat ko chamakta hai ⭐"),
        ("boat",  "Paani pe chalta hai ⛵"),
        ("book",  "Padhne ke liye 📚"),
        ("door",  "Ghar mein hota hai 🚪"),
        ("frog",  "Toad ka cousin 🐸"),
        ("gold",  "Keemat hoti hai iska 💛"),
        ("hand",  "5 ungliyan hoti hain ✋"),
        ("jump",  "Upar jaane ka action 🦘"),
        ("king",  "Raaja hota hai 👑"),
        ("lamp",  "Roshni deta hai 💡"),
        ("milk",  "White liquid~ 🥛"),
        ("pink",  "Light red color 🌸"),
        ("ring",  "Finger pe pehante hain 💍"),
        ("salt",  "Khane mein dalte hain 🧂"),
        ("tree",  "Leaves aur branches 🌳"),
        ("wind",  "Air ka movement 🌬️"),
        ("wolf",  "Wild dog jaisa janwar 🐺"),
        ("rice",  "India ka main khaana 🍚"),
        ("blue",  "Sky ka rang 💙"),
        ("rose",  "Flower of love 🌹"),
        ("snow",  "Thand mein girti hai ❄️"),
    ],
    "medium": [
        ("castle",  "Raja ka ghar 🏰"),
        ("planet",  "Earth bhi ek hai 🌍"),
        ("flower",  "Garden mein hoti hai 🌺"),
        ("bridge",  "Nadi ke upar hota hai 🌉"),
        ("butter",  "Toast pe lagaate hain 🧈"),
        ("candle",  "Mombatti 🕯️"),
        ("desert",  "Bahut garmi, reth hi reth 🏜️"),
        ("engine",  "Train ka dil 🚂"),
        ("forest",  "Bahut saare ped 🌲"),
        ("garden",  "Flowers aur plants ka ghar 🌸"),
        ("insect",  "6 legs wala chhota janwar 🐛"),
        ("jungle",  "Wild forest 🌴"),
        ("knight",  "Sword wala warrior ⚔️"),
        ("ladder",  "Upar chadhne ke liye 🪜"),
        ("mirror",  "Apna chehra dikhata hai 🪞"),
        ("monkey",  "Banana khaata hai 🐒"),
        ("needle",  "Silai mein kaam aati hai 🪡"),
        ("orange",  "Fruit aur color bhi hai 🍊"),
        ("parrot",  "Bolne wala parinda 🦜"),
        ("puzzle",  "Pieces jodte hain 🧩"),
        ("rabbit",  "Gajar khaata hai 🐰"),
        ("rocket",  "Space mein jaata hai 🚀"),
        ("silver",  "Gray shiny metal 🥈"),
        ("spider",  "Jaal bunta hai 🕷️"),
        ("summer",  "Garmi ka mausam ☀️"),
        ("throne",  "Raja baithta hai 👑"),
        ("violin",  "Musical instrument 🎻"),
        ("wallet",  "Paise rakhte hain 👛"),
        ("winter",  "Thand ka mausam ❄️"),
        ("pirate",  "Samundar ka lutaira 🏴‍☠️"),
    ],
    "hard": [
        ("alchemy",    "Dhatu se sona banane ki koshish ⚗️"),
        ("dinosaur",   "Prehistoric giant lizard 🦕"),
        ("elephant",   "Sabse bada land animal 🐘"),
        ("fireworks",  "New year pe chalate hain 🎆"),
        ("galaxies",   "Crores stars ka collection 🌌"),
        ("haunted",    "Bhoot wali jagah 👻"),
        ("iceberg",    "Titanic se takraya tha 🧊"),
        ("jealousy",   "Doosre ki cheez chahna 😒"),
        ("keyboard",   "Typing ke liye 💻"),
        ("labyrinth",  "Maze jaise confusing path 🌀"),
        ("marathon",   "42km ki daud 🏃"),
        ("obsidian",   "Volcano se bana black stone 🪨"),
        ("paradise",   "Jannat jaisi jagah 🌴"),
        ("quicksand",  "Phansane wali reth 😱"),
        ("scorpion",   "Desert ka dangerous janwar 🦂"),
        ("twilight",   "Sunset ke baad ka time 🌅"),
        ("umbrella",   "Baarish se bachata hai ☂️"),
        ("vacation",   "Holidays mein jaate hain ✈️"),
        ("whirlpool",  "Paani ka chakkar 🌀"),
        ("xylophone",  "Colorful musical instrument 🎵"),
        ("yesterday",  "Kal jo tha, aaj nahi 📅"),
        ("absolute",   "Complete ya total bilkul 💯"),
        ("blizzard",   "Tufani barfbari ❄️🌨️"),
        ("champion",   "Winner of winners 🏆"),
        ("cathedral",  "Bada church building ⛪"),
        ("blueprint",  "Plan ka diagram 📐"),
        ("rhapsody",   "Free-flowing music piece 🎶"),
        ("phantom",    "Ghost ya illusion 👻"),
        ("carnival",   "Mela aur fun fair 🎡"),
        ("dungeon",    "Castle ka andhera kamaraa 🗝️"),
    ],
}


def _scramble(word: str) -> str:
    letters = list(word)
    for _ in range(20):
        random.shuffle(letters)
        s = "".join(letters)
        if s != word:
            return s.upper()
    return (word[1:] + word[0]).upper()


def _hint_text(word: str, revealed: int) -> str:
    """Show first `revealed` letters, rest as underscores."""
    result = []
    for i, ch in enumerate(word):
        result.append(ch.upper() if i < revealed else "＿")
    return " ".join(result)


async def _send_scramble_q(chat_id: int) -> None:
    game  = active_scramble[chat_id]
    idx   = game["current"]
    total = game["total"]
    word, hint = game["words"][idx]
    diff  = game["difficulty"]
    diff_emoji = {"easy": "🌟", "medium": "🔥", "hard": "💀"}[diff]
    scrambled  = _scramble(word)

    text = (
        f"🔤 <b>Word Scramble</b> {diff_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Round <b>{idx + 1}</b> / {total}\n\n"
        f"Unscramble this:  <code>{scrambled}</code>\n\n"
        f"<i>Type your answer in the chat~ ✍️</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💡 Hint",      callback_data="ws_hint"),
            InlineKeyboardButton(text="⏭️ Skip",      callback_data="ws_skip"),
        ],
        [
            InlineKeyboardButton(text="🛑 Stop Game", callback_data="ws_stop"),
        ],
    ])
    msg = await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
    game["q_msg_id"]       = msg.message_id
    game["hint_count"]     = 0
    game["scrambled_shown"] = scrambled


async def _end_scramble(chat_id: int, stopped: bool = False) -> None:
    game = active_scramble.pop(chat_id, None)
    if not game:
        return

    elapsed = time.time() - game["start_time"]
    mins, secs = int(elapsed // 60), int(elapsed % 60)
    diff_emoji = {"easy": "🌟", "medium": "🔥", "hard": "💀"}[game["difficulty"]]

    players = game["players"]
    sorted_p = sorted(players.items(), key=lambda x: x[1]["correct"], reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    board = ""
    for i, (uid, data) in enumerate(sorted_p):
        medal   = medals[i] if i < 3 else f"#{i+1}"
        mention = make_mention(uid, data["name"])
        board  += f"{medal} {mention}  —  ✅ {data['correct']}  ⏭️ {data['skipped']}\n"
    if not board:
        board = "<i>Kisi ne participate nahi kiya~ 🥺</i>\n"

    stop_note = "🛑 <i>Game bich mein rok diya~</i>\n\n" if stopped else ""
    text = (
        f"🏆 <b>Game Over!</b> {diff_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{stop_note}"
        f"<b>Leaderboard</b>\n"
        f"{board}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Rounds: <b>{game['current']}/{game['total']}</b>  |  "
        f"Difficulty: <b>{game['difficulty'].title()}</b>  |  "
        f"Time: <b>{mins}m {secs}s</b>\n\n"
        f"<i>Mikasa wapas aa gayi~ ab baat karo! 💕</i>"
    )
    await bot.send_message(chat_id, text, parse_mode="HTML")


# ── /game command ────────────────────────────────────────────
@dp.message(Command("game"))
async def cmd_game(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔤 Word Scramble", callback_data="ws_menu")],
        [InlineKeyboardButton(text="⬅️ Back",          callback_data="back_home")],
    ])
    await message.reply(
        "🎮 <b>Mikasa Games</b>\n\n"
        "Choose a game to play~ 👇",
        parse_mode="HTML",
        reply_markup=kb,
    )


# ── Word Scramble menu (from inline button) ──────────────────
@dp.callback_query(F.data == "ws_menu")
async def cb_ws_menu(call: CallbackQuery):
    if call.message.chat.id in active_scramble:
        await call.answer("Game already chal raha hai~ ⚠️", show_alert=True)
        return
    text = (
        "🔤 <b>Word Scramble</b>\n\n"
        "Scrambled word dekhoge, sahi spell karna hai~\n\n"
        "🌟 <b>Easy</b>   — 4-5 letter simple words\n"
        "🔥 <b>Medium</b> — 6-7 letter tricky words\n"
        "💀 <b>Hard</b>   — 8+ letter challengers\n\n"
        "⚠️ <i>Game ke dauran Mikasa normal chat nahi karegi~</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Select difficulty~ 👇"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 Easy",   callback_data="ws_diff_easy"),
            InlineKeyboardButton(text="🔥 Medium", callback_data="ws_diff_medium"),
            InlineKeyboardButton(text="💀 Hard",   callback_data="ws_diff_hard"),
        ],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="cat_fun")],
    ])
    await edit_msg(call, text, kb)
    await call.answer()


# ── Difficulty chosen → pick rounds ─────────────────────────
@dp.callback_query(F.data.startswith("ws_diff_"))
async def cb_ws_diff(call: CallbackQuery):
    if call.message.chat.id in active_scramble:
        await call.answer("Game already chal raha hai~ ⚠️", show_alert=True)
        return
    diff = call.data.split("_")[2]
    diff_emoji = {"easy": "🌟", "medium": "🔥", "hard": "💀"}[diff]
    text = (
        f"🔤 <b>Word Scramble</b>  {diff_emoji} {diff.title()}\n\n"
        "Kitne rounds khelna hai?~ 👇"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="10",  callback_data=f"ws_rounds_{diff}_10"),
            InlineKeyboardButton(text="20",  callback_data=f"ws_rounds_{diff}_20"),
            InlineKeyboardButton(text="30",  callback_data=f"ws_rounds_{diff}_30"),
        ],
        [
            InlineKeyboardButton(text="50",  callback_data=f"ws_rounds_{diff}_50"),
            InlineKeyboardButton(text="100", callback_data=f"ws_rounds_{diff}_100"),
        ],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="ws_menu")],
    ])
    await edit_msg(call, text, kb)
    await call.answer()


# ── Groq word generator (called once at game start) ──────────
async def _groq_generate_words(diff: str, count: int) -> list[tuple]:
    """Ask Groq to generate fresh unique words — one API call per game."""
    letter_guide = {"easy": "4-5", "medium": "6-7", "hard": "8-10"}[diff]
    prompt = (
        f"Generate {min(count, 60)} unique English words for a Word Scramble game.\n"
        f"Difficulty: {diff} ({letter_guide} letters each).\n"
        f"Return ONLY a valid JSON array, no explanation, no markdown:\n"
        f'[{{"word":"cat","hint":"Meow karta hai~ 🐱"}}, ...]\n'
        f"Hint rules: short Hinglish/English mix, max 7 words, include 1 emoji."
    )
    try:
        res = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.9,
        )
        raw   = res.choices[0].message.content.strip()
        start = raw.index("[")
        end   = raw.rindex("]") + 1
        data  = json.loads(raw[start:end])
        words = [
            (d["word"].lower().strip(), d.get("hint", "Guess karo~ 🤔"))
            for d in data
            if isinstance(d, dict) and "word" in d and len(d["word"].strip()) >= 3
        ]
        if len(words) >= 5:
            return words
    except Exception:
        pass
    # Fallback: local list
    pool = SCRAMBLE_WORDS[diff].copy()
    random.shuffle(pool)
    return pool


# ── Rounds chosen → start game ───────────────────────────────
@dp.callback_query(F.data.startswith("ws_rounds_"))
async def cb_ws_rounds(call: CallbackQuery):
    chat_id = call.message.chat.id
    if chat_id in active_scramble:
        await call.answer("Game already chal raha hai~ ⚠️", show_alert=True)
        return

    parts = call.data.split("_")   # ws_rounds_<diff>_<n>
    diff  = parts[2]
    total = int(parts[3])
    diff_emoji = {"easy": "🌟", "medium": "🔥", "hard": "💀"}[diff]

    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()

    # Show "generating" notice while Groq works
    gen_msg = await bot.send_message(
        chat_id,
        f"🔤 <b>Word Scramble</b> {diff_emoji}\n"
        f"Difficulty: <b>{diff.title()}</b>  |  Rounds: <b>{total}</b>\n\n"
        f"<i>✨ Generating fresh words with AI~ please wait...</i>",
        parse_mode="HTML",
    )

    # One Groq call — generate all words upfront
    pool  = await _groq_generate_words(diff, total)
    random.shuffle(pool)
    words = pool[:total] if total <= len(pool) else (pool * (total // len(pool) + 1))[:total]

    active_scramble[chat_id] = {
        "words":      words,
        "current":    0,
        "total":      total,
        "difficulty": diff,
        "players":    {},
        "start_time": time.time(),
        "q_msg_id":   None,
        "hint_count": 0,
        "scrambled_shown": "",
    }

    try:
        await gen_msg.edit_text(
            f"🔤 <b>Word Scramble started!</b> {diff_emoji}\n"
            f"Difficulty: <b>{diff.title()}</b>  |  Rounds: <b>{total}</b>\n\n"
            f"<i>⚠️ Game ke dauran Mikasa sirf game messages bhejegi~\n"
            f"Game khatam hone pe wapas normal ho jaayegi 💕</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await asyncio.sleep(1)
    await _send_scramble_q(chat_id)


# ── Hint button ──────────────────────────────────────────────
@dp.callback_query(F.data == "ws_hint")
async def cb_ws_hint(call: CallbackQuery):
    chat_id = call.message.chat.id
    game    = active_scramble.get(chat_id)
    if not game:
        await call.answer("Koi game nahi chal raha~ 😅", show_alert=True)
        return

    word      = game["words"][game["current"]][0]
    revealed  = game["hint_count"] + 1
    if revealed > len(word):
        await call.answer("Aur hint nahi hai~ word guess karo! 😤", show_alert=True)
        return

    game["hint_count"] = revealed
    hint_str = _hint_text(word, revealed)

    await call.answer(f"💡 Hint: {hint_str}", show_alert=True)


# ── Skip button ──────────────────────────────────────────────
@dp.callback_query(F.data == "ws_skip")
async def cb_ws_skip(call: CallbackQuery):
    chat_id = call.message.chat.id
    game    = active_scramble.get(chat_id)
    if not game:
        await call.answer("Koi game nahi chal raha~ 😅", show_alert=True)
        return

    uid  = call.from_user.id
    name = call.from_user.full_name
    game["players"].setdefault(uid, {"name": name, "correct": 0, "skipped": 0})
    game["players"][uid]["skipped"] += 1
    game["players"][uid]["name"]     = name

    word = game["words"][game["current"]][0]

    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()

    game["current"] += 1
    if game["current"] >= game["total"]:
        await bot.send_message(
            chat_id,
            f"⏭️ Skipped! Word tha: <code>{word.upper()}</code>",
            parse_mode="HTML",
        )
        await _end_scramble(chat_id)
    else:
        await bot.send_message(
            chat_id,
            f"⏭️ Skipped! Word tha: <code>{word.upper()}</code>\n"
            f"Next round aa raha hai~",
            parse_mode="HTML",
        )
        await asyncio.sleep(0.8)
        await _send_scramble_q(chat_id)


# ── Stop game button (admin or owner) ───────────────────────
@dp.callback_query(F.data == "ws_stop")
async def cb_ws_stop(call: CallbackQuery):
    chat_id = call.message.chat.id
    game    = active_scramble.get(chat_id)
    if not game:
        await call.answer("Koi game nahi chal raha~ 😅", show_alert=True)
        return

    uid = call.from_user.id
    if not (await is_admin(chat_id, uid) or uid == OWNER_ID):
        await call.answer("Sirf admins game rok sakte hain~ 😤", show_alert=True)
        return

    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer("Game rok diya~ 🛑")
    await _end_scramble(chat_id, stopped=True)


# (answer checking is handled inside chat_handler below)


# ════════════════════════════════════════════════════════════
#  NORMAL CHAT — only responds when actually addressed
# ════════════════════════════════════════════════════════════

async def _should_reply(message: Message) -> bool:
    """
    Returns True only if Mikasa should respond:
      1. It is a private chat (DM)
      2. User replied to Mikasa's own message
      3. Message contains @bot_username mention
      4. Message contains bot's first/full name
    """
    # Silent during active Word Scramble game
    if message.chat.id in active_scramble:
        return False

    if message.chat.type == "private":
        return True

    me = await bot.get_me()

    # Replied to Mikasa's message
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == me.id:
            return True

    text_lower = (message.text or "").lower()

    # @username mention
    if me.username and f"@{me.username}".lower() in text_lower:
        return True

    # Name mention
    if me.first_name and me.first_name.lower() in text_lower:
        return True

    return False


@dp.message(F.text & ~F.text.startswith("/"))
async def chat_handler(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # ── Word Scramble answer check (must be first) ────────────
    game = active_scramble.get(chat_id)
    if game:
        guess = (message.text or "").strip().lower()
        word  = game["words"][game["current"]][0].lower()
        if guess == word:
            uid  = message.from_user.id
            name = message.from_user.full_name
            game["players"].setdefault(uid, {"name": name, "correct": 0, "skipped": 0})
            game["players"][uid]["correct"] += 1
            game["players"][uid]["name"]     = name
            mention = make_mention(uid, name)
            try:
                if game["q_msg_id"]:
                    await bot.delete_message(chat_id, game["q_msg_id"])
            except Exception:
                pass
            game["current"] += 1
            if game["current"] >= game["total"]:
                await message.reply(
                    f"🎉 {mention} ne guess kar liya!\n"
                    f"Word tha: <code>{word.upper()}</code>",
                    parse_mode="HTML",
                )
                await _end_scramble(chat_id)
            else:
                remaining = game["total"] - game["current"]
                await message.reply(
                    f"🎉 {mention} ne guess kar liya!\n"
                    f"Word tha: <code>{word.upper()}</code>\n"
                    f"<i>{remaining} rounds baaki hain~</i>",
                    parse_mode="HTML",
                )
                await asyncio.sleep(0.8)
                await _send_scramble_q(chat_id)
        # During any active game, never let Mikasa chat normally
        return

    # Search mode — always handle regardless of trigger
    if search_mode.get(user_id):
        search_mode[user_id] = False
        await _do_search(message, message.text, chat_id)
        return

    # Only reply if Mikasa is actually being addressed
    if not await _should_reply(message):
        return

    # Build conversation history for this chat (last 5 user+assistant turns)
    history = chat_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": message.text})
    if len(history) > 10:   # 5 turns = 10 messages (user+assistant pairs)
        history[:] = history[-10:]

    try:
        res = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": get_system_prompt(chat_id)},
                *history,
            ],
            max_tokens=80,
            temperature=0.85,
        )
        reply_text = res.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply_text})
        await message.reply(reply_text)
        # 20% chance to also send a sticker after the text reply
        if random.random() < STICKER_CHANCE:
            sticker = random_sticker()
            if sticker:
                await message.answer_sticker(sticker)
    except Exception:
        await message.reply("kuch hua 😐 phir baat karte")



# ════════════════════════════════════════════════════════════
#  /spam — Fun spam command
#
#  Usage variants:
#    /spam 20               → spam 20 random stickers
#    /spam 20 hello!        → spam "hello!" 20 times
#    /spam 10 hi @username  → spam "hi <mention>" 10 times
#
#  Rules:
#    - Max 1000 spams
#    - 1.5s pause every 5 messages (Telegram floodwait protection)
#    - If user sent with a clickable mention → mention is included
#    - If no mention given → plain text, no forced mention

# ════════════════════════════════════════════════════════════
#  /spam — Fun spam command
#  /spam 20          → 20 random stickers
#  /spam 20 text     → text 20 times
#  /spam 10 hi @usr  → text + tag 10 times
#  Max 100, pause every 5 to avoid flood
# ════════════════════════════════════════════════════════════

async def _do_spam(message: Message, count: int, final_text: str | None):
    """Execute spam operation — cancellable."""
    user_id = message.from_user.id
    start_time = time.time()
    sent_count = 0
    
    try:
        for i in range(count):
            if user_id not in spam_tasks:  # check if task was cancelled
                break
                
            try:
                if final_text is None:
                    sticker = random_sticker()
                    if sticker:
                        await bot.send_sticker(message.chat.id, sticker)
                    else:
                        await bot.send_message(message.chat.id, "\U0001f338")
                else:
                    await bot.send_message(
                        message.chat.id,
                        final_text,
                        parse_mode="HTML",
                    )
                sent_count += 1
            except Exception as e:
                logging.warning(f"Spam error at {i}: {e}")
                break

            # Small delay between EACH message to avoid Telegram rate limits
            # Telegram: ~30 msgs/sec = safe at 0.15s per message
            await asyncio.sleep(0.15)
            
            # Longer break every 20 messages to reset rate counters
            if (i + 1) % 20 == 0:
                await asyncio.sleep(2)  # 2s break every 20 messages
        
        # Send ending announcement
        ending_msg = "⏹️ <b>Spam Ended~</b>\n<i>Spam ho gaya ab result dekho~ 🌸</i>"
        try:
            await message.reply(ending_msg, parse_mode="HTML")
        except Exception as e:
            logging.warning(f"Could not send ending msg: {e}")
        
        # Send completion message with stats
        end_time = time.time()
        time_taken = end_time - start_time
        
        spam_content = "Stickers 🎬" if final_text is None else f"Text: <code>{final_text[:50]}</code>" if len(final_text) <= 50 else f"Text: <code>{final_text[:47]}...</code>"
        
        completion_msg = (
            "🎉 <b>Spam Mission Accomplished~</b>\n\n"
            "<blockquote expandable>"
            f"📝 <b>Content:</b> {spam_content}\n"
            f"💌 <b>Messages Sent:</b> {sent_count} / {count}\n"
            f"⏱️ <b>Time Taken:</b> {time_taken:.2f}s\n\n"
            "<i>Aah~ itna spam kar diya~ 💕</i>"
            "</blockquote>"
        )
        
        try:
            await message.reply(completion_msg, parse_mode="HTML")
        except Exception as e:
            logging.warning(f"Could not send completion msg: {e}")
    
    except asyncio.CancelledError:
        # Spam was stopped
        end_time = time.time()
        time_taken = end_time - start_time
        
        stop_msg = (
            "⏹️ <b>Spam Stopped~</b>\n\n"
            "<blockquote expandable>"
            f"💌 <b>Messages Sent:</b> {sent_count}\n"
            f"⏱️ <b>Time Taken:</b> {time_taken:.2f}s\n\n"
            "<i>Theek hai, ruk gaye~ 💅</i>"
            "</blockquote>"
        )
        try:
            await message.reply(stop_msg, parse_mode="HTML")
        except Exception as e:
            logging.warning(f"Could not send stop msg: {e}")
    
    except Exception as e:
        logging.error(f"Spam task error: {e}")
        try:
            await message.reply(f"❌ Spam error: {str(e)[:50]}", parse_mode="HTML")
        except:
            pass
    
    finally:
        # Remove from active tasks
        spam_tasks.pop(user_id, None)


@dp.message(Command("spam"))
async def cmd_spam(message: Message):
    user_id = message.from_user.id
    
    # Check if user already has an active spam
    if user_id in spam_tasks and not spam_tasks[user_id].done():
        await message.reply(
            "Arre, ek spam chal rahi hai na~ \U0001f60c\n"
            "Type <code>/stop</code> to stop it first!",
            parse_mode="HTML",
        )
        return
    
    plain = message.text or ""
    plain_parts = plain.split(maxsplit=1)[1:]   # drop "/spam"
    if not plain_parts:
        await message.reply(
            "Bata toh sahi kitna spam karu~ \U0001f97a\n\n"
            "<blockquote expandable>"
            "Usage:\n"
            "<code>/spam 20</code> \u2014 20 stickers\n"
            "<code>/spam 20 text</code> \u2014 text 20 baar\n"
            "<code>/spam 10 hello @user</code> \u2014 tag ke saath\n\n"
            "Max: 1000\n\n"
            "💡 Use <code>/stop</code> to cancel anytime"
            "</blockquote>",
            parse_mode="HTML",
        )
        return

    after_cmd = plain_parts[0].split(maxsplit=1)   # ["10"] or ["10", "text..."]

    if not after_cmd[0].isdigit():
        await message.reply(
            "Pehle number likho phir text~ \U0001f624\n"
            "Example: <code>/spam 10</code> ya <code>/spam 10 hello</code>",
            parse_mode="HTML",
        )
        return

    count = min(int(after_cmd[0]), 1000)
    if count < 1:
        return await message.reply("Ek toh karo kam se kam~ \U0001f97a")

    if len(after_cmd) < 2:
        final_text = None   # sticker-only mode
    else:
        # Use html_text to get entities already converted to proper HTML links.
        # text_mention (no-username users) → tg://user?id= ping link  ✓
        # @username mention → https://t.me/ link (we upgrade these below)
        html_msg  = message.html_text or plain
        # Strip "/spam NUM " prefix from html_text — command and count are plain
        # ASCII so their byte lengths match between plain and html_text.
        prefix_len = len("/spam ") + len(after_cmd[0]) + 1   # +1 for the space
        spam_html  = html_msg[prefix_len:].strip()

        # Upgrade https://t.me/username links → tg://user?id= so bot actually pings
        import re as _re
        tme_pattern = _re.compile(r'<a href="https://t\.me/([^"]+)">(@[^<]+)</a>')
        async def _resolve_mention(m):
            username, display = m.group(1), m.group(2)
            try:
                chat = await bot.get_chat(username)
                return make_mention(chat.id, chat.full_name or display)
            except Exception:
                return m.group(0)   # keep original if resolution fails

        result = spam_html
        for m in list(tme_pattern.finditer(spam_html)):
            result = result.replace(m.group(0), await _resolve_mention(m))
        spam_html = result

        final_text = spam_html or "\U0001f338"

    # Send start confirmation
    start_msg = (
        f"🚀 <b>Spam Started~</b>\n\n"
        f"<blockquote expandable>"
        f"💌 <b>Count:</b> {count}\n"
        f"📝 <b>Content:</b> {('Stickers 🎬' if final_text is None else f'<code>{final_text[:40]}</code>')}\n\n"
        f"<i>Chalo shuru karte hain~ 😋</i>"
        f"</blockquote>"
    )
    await message.reply(start_msg, parse_mode="HTML")
    
    # Create and store task so it can be cancelled
    task = asyncio.create_task(_do_spam(message, count, final_text))
    spam_tasks[user_id] = task


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    """Stop an active spam operation."""
    user_id = message.from_user.id
    
    if user_id not in spam_tasks or spam_tasks[user_id].done():
        await message.reply(
            "Koi spam chal nahi rahi abhi~ \U0001f914\n"
            "Start one with <code>/spam 100</code> or up to 1000!",
            parse_mode="HTML",
        )
        return
    
    # Cancel the spam task
    spam_tasks[user_id].cancel()
    await message.reply("✋ Stopping spam now~", parse_mode="HTML")

# ════════════════════════════════════════════════════════════
#  STICKER SYSTEM
# ════════════════════════════════════════════════════════════

async def load_stickers():
    """Fetch all sticker file_ids from the pack at startup."""
    try:
        pack = await bot.get_sticker_set(STICKER_PACK)
        STICKER_IDS.clear()
        STICKER_IDS.extend(s.file_id for s in pack.stickers)
        logging.info(f"🌸 Loaded {len(STICKER_IDS)} stickers from {STICKER_PACK}")
    except Exception as e:
        logging.warning(f"Could not load sticker pack: {e}")


def random_sticker() -> str | None:
    """Return a random sticker file_id or None if pool empty."""
    return random.choice(STICKER_IDS) if STICKER_IDS else None


# ── Handler: when Mikasa receives a sticker → always reply with one ──

@dp.message(F.sticker)
async def on_sticker(message: Message):
    """Reply to any sticker sent to Mikasa with a random sticker from the pack."""
    # Only reply if addressed (group) or always in DM
    if message.chat.type != "private" and not await _should_reply(message):
        return
    sticker = random_sticker()
    if sticker:
        await message.reply_sticker(sticker)


# ════════════════════════════════════════════════════════════
#  BOT ADDED TO GROUP — self-introduction
# ════════════════════════════════════════════════════════════

@dp.my_chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_bot_added(event: ChatMemberUpdated):
    """Send a self-introduction when Mikasa is added to a group."""
    chat = event.chat
    intro = (
        "🌸 <b>Heyy~ Main aa gayi!</b>\n\n"
        "Main hoon <b>Mikasa</b> — is group ki nai cute guardian~ 💕\n\n"
        "Yeh hain mere commands:\n"
        "╔══════════════════╗\n"
        "║ /start  🌸 Main menu kholne ke liye\n"
        "║ /couple 💘 Aaj ka couple dhundhne ke liye\n"
        "║ /search 🔍 Kuch bhi puchho AI se\n"
        "║ /spam   💢 Masti time — stickers ya text!\n"
        "╚══════════════════╝\n\n"
        "Mod commands ke liye /mod type karo~\n\n"
        "<i>Group ko safe aur fun rakhna mera kaam hai~ 🛡✨</i>"
    )
    try:
        if WELCOME_VIDEOS:
            idx     = random.randint(0, len(WELCOME_VIDEOS) - 1)
            video   = WELCOME_VIDEOS[idx]
            caption = WELCOME_CAPTIONS[idx % len(WELCOME_CAPTIONS)].format(name="sabko")
            full_caption = caption + "\n\n" + intro
            await bot.send_video(
                chat.id,
                video=FSInputFile(str(video)),
                caption=full_caption,
                parse_mode="HTML",
                reply_markup=start_keyboard(),
            )
        else:
            await bot.send_message(
                chat.id,
                intro,
                parse_mode="HTML",
                reply_markup=start_keyboard(),
            )
    except Exception as e:
        logging.warning(f"Could not send group intro to {chat.id}: {e}")


# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════

BOT_COMMANDS_GROUP = [
    # Fun Commands
    BotCommand(command="start",   description="🌸 ᴏᴘᴇɴ ᴛʜᴇ ᴍᴀɪɴ ᴍᴇɴᴜ ᴀɴᴅ ɢᴇᴛ ᴀ ᴄᴜᴛᴇ ᴡᴇʟᴄᴏᴍᴇ~"),
    BotCommand(command="couple",  description="💘 ꜰɪɴᴅ ᴛʜᴇ ᴘᴇʀꜰᴇᴄᴛ ᴍᴀᴛᴄʜ ꜰʀᴏᴍ ᴛʜᴇ ɢʀᴏᴜᴘ ᴍᴇᴍʙᴇʀꜱ!"),
    BotCommand(command="search",  description="🔍 ᴀꜱᴋ ᴍɪᴋᴀꜱᴀ ᴀɴʏᴛʜɪɴɢ ᴜꜱɪɴɢ ᴛʜᴇ ᴘᴏᴡᴇʀ ᴏꜰ ᴀɪ~"),
    BotCommand(command="spam",    description="💢 ᴍᴀꜱᴛɪ ᴛɪᴍᴇ! ꜱᴘᴀᴍ ᴛᴇxᴛ ᴏʀ ꜱᴛɪᴄᴋᴇʀꜱ ᴜᴘ ᴛᴏ 1000!"),
    BotCommand(command="stop",    description="⏹️ ꜱᴛᴏᴘ ᴀɴ ᴀᴄᴛɪᴠᴇ ꜱᴘᴀᴍ ᴏᴘᴇʀᴀᴛɪᴏɴ~"),
    BotCommand(command="game",    description="🎮 ɢʀᴏᴜᴘ ɢᴀᴍᴇꜱ — ᴡᴏʀᴅ ꜱᴄʀᴀᴍʙʟᴇ & ᴍᴏʀᴇ!"),
    # Moderation Commands
    BotCommand(command="mod",     description="🛡 ᴍᴏᴅᴇʀᴀᴛɪᴏɴ ᴘᴀɴᴇʟ ᴀɴᴅ ᴛᴏᴏʟꜱ"),
    BotCommand(command="ban",     description="🚫 ʙᴀɴ ᴀ ᴜꜱᴇʀ ꜰʀᴏᴍ ᴛʜᴇ ɢʀᴏᴜᴘ"),
    BotCommand(command="unban",   description="✅ ᴜɴʙᴀɴ ᴀ ᴜꜱᴇʀ"),
    BotCommand(command="kick",    description="👢 ᴋɪᴄᴋ ᴀ ᴜꜱᴇʀ ꜰʀᴏᴍ ᴛʜᴇ ɢʀᴏᴜᴘ"),
    BotCommand(command="mute",    description="🔇 ᴍᴜᴛᴇ ᴀ ᴜꜱᴇʀ"),
    BotCommand(command="unmute",  description="🔊 ᴜɴᴍᴜᴛᴇ ᴀ ᴜꜱᴇʀ"),
    BotCommand(command="purge",   description="🧹 ᴅᴇʟᴇᴛᴇ ᴍᴇꜱꜱᴀɢᴇꜱ"),
    BotCommand(command="unbanall", description="🔓 ᴜɴʙᴀɴ ᴀʟʟ ᴜꜱᴇʀꜱ"),
    BotCommand(command="zombies", description="🧟 ʀᴇᴍᴏᴠᴇ ᴅᴇʟᴇᴛᴇᴅ ᴀᴄᴄᴏᴜɴᴛꜱ"),
    BotCommand(command="promote", description="👑 ᴘʀᴏᴍᴏᴛᴇ ᴀ ᴜꜱᴇʀ ᴛᴏ ᴀᴅᴍɪɴ"),
    BotCommand(command="demote",  description="📍 ᴅᴇᴍᴏᴛᴇ ᴀɴ ᴀᴅᴍɪɴ"),
    BotCommand(command="warn",    description="⚠️ ᴡᴀʀɴ ᴀ ᴜꜱᴇʀ"),
    BotCommand(command="unwarn",  description="✨ ʀᴇᴍᴏᴠᴇ ᴀ ᴡᴀʀɴɪɴɢ"),
    # About
    BotCommand(command="about",   description="ℹ️ ᴀʙᴏᴜᴛ ᴍɪᴋᴀꜱᴀ"),
]

BOT_COMMANDS_PRIVATE = [
    # Fun Commands
    BotCommand(command="start",   description="🌸 ᴏᴘᴇɴ ᴛʜᴇ ᴍᴀɪɴ ᴍᴇɴᴜ ᴀɴᴅ ɢᴇᴛ ᴀ ᴄᴜᴛᴇ ᴡᴇʟᴄᴏᴍᴇ~"),
    BotCommand(command="search",  description="🔍 ᴀꜱᴋ ᴍɪᴋᴀꜱᴀ ᴀɴʏᴛʜɪɴɢ ᴜꜱɪɴɢ ᴛʜᴇ ᴘᴏᴡᴇʀ ᴏꜰ ᴀɪ~"),
    BotCommand(command="spam",    description="💢 ᴍᴀꜱᴛɪ ᴛɪᴍᴇ! ꜱᴘᴀᴍ ᴛᴇxᴛ ᴏʀ ꜱᴛɪᴄᴋᴇʀꜱ ᴜᴘ ᴛᴏ 1000!"),
    BotCommand(command="stop",    description="⏹️ ꜱᴛᴏᴘ ᴀɴ ᴀᴄᴛɪᴠᴇ ꜱᴘᴀᴍ ᴏᴘᴇʀᴀᴛɪᴏɴ~"),
    BotCommand(command="game",    description="🎮 ɢʀᴏᴜᴘ ɢᴀᴍᴇꜱ — ᴡᴏʀᴅ ꜱᴄʀᴀᴍʙʟᴇ & ᴍᴏʀᴇ!"),
    # About
    BotCommand(command="about",   description="ℹ️ ᴀʙᴏᴜᴛ ᴍɪᴋᴀꜱᴀ"),
]


async def main():
    logging.info("🌸 Mikasa v4 chal padi~")
    
    # Start dummy web server for Render free tier
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    logging.info("🌐 Web server started for Render~")
    
    await load_stickers()           # fetch sticker pack on startup

    # Register command menus in Telegram
    await bot.set_my_commands(BOT_COMMANDS_GROUP,   scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(BOT_COMMANDS_PRIVATE, scope=BotCommandScopeAllPrivateChats())
    logging.info("Commands registered in Telegram menu~")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

# ── Dummy Web Server for Render Free Tier ──────────────────
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Mikasa Bot is running!")
    def log_message(self, format, *args):
        pass  # silent logs

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()
