# ════════════════════════════════════════════════════════════
#  INLINE MODE HANDLER — @BotUsername <question>
# ════════════════════════════════════════════════════════════

from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

# System prompt for inline mode — clean, helpful, no personality
INLINE_SYSTEM = """You are a helpful AI assistant. Provide clear, concise answers in 2–5 sentences.
No roleplay, no personality quirks — just direct, accurate information."""

# Note: groq_client, GROQ_MODEL, and dp are imported from the main bot file
# Import this handler into mikasa_bot.py and register it with the dispatcher


async def inline_query_handler(query: InlineQuery):
    """
    Handle inline queries: users type @BotUsername <question> in any chat.
    Returns an AI-powered answer using Groq.
    """
    user_question = query.query.strip()
    
    # ── Case 1: Empty query ──────────────────────────────────────
    if not user_question:
        empty_result = InlineQueryResultArticle(
            id="empty",
            title="🤖 Ask AI",
            description="Type your question after the bot username…",
            input_message_content=InputTextMessageContent(
                message_text="❓ Koi question type karo~"
            ),
        )
        await query.answer(results=[empty_result], cache_time=10, is_personal=True)
        return
    
    # ── Case 2: Query with content ──────────────────────────────
    try:
        # Call Groq API
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": INLINE_SYSTEM},
                {"role": "user", "content": user_question},
            ],
            max_tokens=300,
            temperature=0.7,
        )
        
        # Extract answer from response
        answer = response.choices[0].message.content.strip()
        
    except Exception as e:
        # Fallback message on any error
        print(f"Inline query error: {e}")
        answer = "⚠️ AI se jawab nahi mila, thodi der baad try karo~"
    
    # ── Create description (first 120 chars + "…" if longer) ────
    description = (answer[:120] + "…") if len(answer) > 120 else answer
    
    # ── Create inline result article ────────────────────────────
    result = InlineQueryResultArticle(
        id="ai_answer",
        title="🤖 Ask AI",
        description=description,
        input_message_content=InputTextMessageContent(
            message_text=f"❓ <b>{user_question}</b>\n\n{answer}",
            parse_mode="HTML",
        ),
    )
    
    # ── Answer the inline query ─────────────────────────────────
    await query.answer(results=[result], cache_time=10, is_personal=True)
