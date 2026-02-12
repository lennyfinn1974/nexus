"""Telegram bot integration — bridges Telegram messages to the Nexus backend.

Uses database-backed pairing codes for authentication instead of a static
allowlist.  Users generate a code from the chat-ui, then send ``/pair CODE``
in Telegram to link their account.  Conversation mapping persists across
server restarts via the ``telegram_pairings`` table.
"""

from __future__ import annotations

import logging
import time
import uuid

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logger = logging.getLogger("nexus.telegram")

# How often (seconds) to refresh the in-memory pairing cache
_CACHE_TTL = 60


class TelegramChannel:
    """Telegram bot that bridges messages to the Nexus agent."""

    def __init__(self, token: str, db, message_handler, agent_name: str = "Nexus"):
        """
        Args:
            token: Telegram bot token from @BotFather
            db: Database instance (for pairing queries)
            message_handler: Async callable(user_id, text, conv_id=None) -> response_text
            agent_name: Display name for user-facing messages (e.g. "Aries")
        """
        self.token = token
        self.db = db
        self.message_handler = message_handler
        self.agent_name = agent_name
        self._app = None
        # In-memory cache of active pairings: {telegram_user_id: pairing_dict}
        self._pairing_cache: dict[str, dict] = {}
        self._cache_updated_at: float = 0

    # ── Auth ──────────────────────────────────────────────────────

    async def _refresh_cache(self):
        """Reload active pairings from DB into memory."""
        try:
            pairings = await self.db.list_telegram_pairings()
            self._pairing_cache = {
                p["telegram_user_id"]: p
                for p in pairings
                if p.get("active")
            }
            self._cache_updated_at = time.time()
            logger.info(f"Pairing cache refreshed: {len(self._pairing_cache)} active users — IDs: {list(self._pairing_cache.keys())}")
        except Exception as e:
            logger.warning(f"Failed to refresh pairing cache: {e}")

    async def _is_paired(self, telegram_user_id: str) -> bool:
        """Check if a Telegram user is paired (uses cache, refreshes periodically)."""
        elapsed = time.time() - self._cache_updated_at
        if elapsed > _CACHE_TTL:
            logger.debug(f"Cache stale ({elapsed:.0f}s > {_CACHE_TTL}s), refreshing...")
            await self._refresh_cache()
        paired = telegram_user_id in self._pairing_cache
        if not paired:
            # Force a fresh DB check if cache says not paired — prevents stale-cache rejections
            logger.info(f"User {telegram_user_id} not in cache ({list(self._pairing_cache.keys())}), checking DB directly...")
            db_pairing = await self.db.get_telegram_pairing(telegram_user_id)
            if db_pairing:
                logger.info(f"User {telegram_user_id} found in DB but missing from cache — refreshing cache")
                await self._refresh_cache()
                return True
            logger.info(f"User {telegram_user_id} not paired (not in DB either)")
        return paired

    # ── Command Handlers ──────────────────────────────────────────

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        logger.info(f"/start from user {user_id} (@{update.effective_user.username})")

        if await self._is_paired(user_id):
            # Update username/first_name if we have newer info from Telegram
            try:
                await self.db.add_telegram_pairing(
                    telegram_user_id=user_id,
                    username=update.effective_user.username,
                    first_name=update.effective_user.first_name,
                )
            except Exception:
                pass  # Non-critical — just updating metadata
            name = update.effective_user.first_name or "there"
            await update.message.reply_text(
                f"Welcome back, {name}! Your account is linked.\n\n"
                "*Commands:*\n"
                "/status — Check system status\n"
                "/skills — List learned skills\n"
                "/learn <topic> — Research a topic\n"
                "/model <claude|local> — Force a model\n"
                "/unpair — Unlink this Telegram account\n\n"
                "Just send a message and I'll help!",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"Welcome to *{self.agent_name}*\n\n"
                "To link this account, copy your Telegram ID below "
                "and paste it in the admin panel → Settings → Telegram Pairing → Pair Now.\n\n"
                f"Your Telegram ID:\n`{user_id}`",
                parse_mode="Markdown",
            )

    async def _handle_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pair CODE — validate and link Telegram account."""
        user_id = str(update.effective_user.id)

        if await self._is_paired(user_id):
            await update.message.reply_text("Your account is already linked! Use /unpair first if you want to re-link.")
            return

        if not context.args:
            await update.message.reply_text("Usage: `/pair CODE`\n\nGet a code from the admin panel → Settings → Telegram Pairing.", parse_mode="Markdown")
            return

        code = context.args[0].upper().strip()

        # Validate the code
        valid = await self.db.validate_pairing_code(code)
        if not valid:
            await update.message.reply_text(
                "Invalid or expired code. Please generate a new one from the admin panel."
            )
            return

        # Consume the code and create the pairing
        await self.db.consume_pairing_code(code, user_id)
        await self.db.add_telegram_pairing(
            telegram_user_id=user_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )

        # Force cache refresh
        await self._refresh_cache()

        name = update.effective_user.first_name or "there"
        await update.message.reply_text(
            f"Linked successfully, {name}!\n\n"
            f"You can now chat with {self.agent_name} directly here. "
            "Send any message to get started.",
        )
        logger.info(f"Telegram user {user_id} (@{update.effective_user.username}) paired successfully")

    async def _handle_unpair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /unpair — unlink Telegram account."""
        user_id = str(update.effective_user.id)

        if not await self._is_paired(user_id):
            await update.message.reply_text("Your account is not linked.")
            return

        await self.db.revoke_telegram_pairing(user_id)
        await self._refresh_cache()

        await update.message.reply_text(
            f"Account unlinked. To use {self.agent_name} again, generate a new pairing code from the admin panel and use /pair."
        )
        logger.info(f"Telegram user {user_id} unpaired")

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        if not await self._is_paired(user_id):
            await update.message.reply_text("Please link your account first. Use /start for instructions.")
            return

        status = context.bot_data.get("status_fn")
        if status:
            info = await status()
            await update.message.reply_text(f"*Status*\n```\n{info}\n```", parse_mode="Markdown")

    # ── Message Handler ───────────────────────────────────────────

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        logger.info(f"Message from Telegram user {user_id} (@{update.effective_user.username}): {(update.message.text or '')[:50]}")

        if not await self._is_paired(user_id):
            logger.warning(f"Rejected message from unpaired user {user_id}")
            await update.message.reply_text(
                "Please link your account first.\nUse /start for instructions."
            )
            return

        text = update.message.text or ""
        if not text.strip():
            return

        # Show typing indicator
        await update.message.chat.send_action("typing")

        # Get or create persistent conversation
        conv_id = await self.db.get_telegram_conversation(user_id)
        if conv_id:
            # Verify conversation still exists
            conv = await self.db.get_conversation(conv_id)
            if not conv:
                conv_id = None

        if not conv_id:
            conv_id = f"tg-{uuid.uuid4().hex[:8]}"
            await self.db.create_conversation(conv_id, title=f"Telegram: {text[:40]}")
            await self.db.update_telegram_conversation(user_id, conv_id)

        try:
            response = await self.message_handler(user_id, text, conv_id=conv_id)
            # Telegram has a 4096 char limit
            if len(response) > 4000:
                chunks = [response[i : i + 4000] for i in range(0, len(response), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(response)
        except Exception as e:
            logger.error(f"Error handling Telegram message: {e}")
            await update.message.reply_text(f"Error: {str(e)[:200]}")

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self, status_fn=None):
        """Start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()

        if status_fn:
            self._app.bot_data["status_fn"] = status_fn

        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("pair", self._handle_pair))
        self._app.add_handler(CommandHandler("unpair", self._handle_unpair))
        self._app.add_handler(CommandHandler("status", self._handle_status))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        # Pre-load pairing cache
        await self._refresh_cache()

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info(f"Telegram bot started ({len(self._pairing_cache)} paired users)")

    async def send_message(self, chat_id: str | int, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a message to a Telegram user/chat proactively.

        Returns True on success, False on failure.
        """
        if not self._app or not self._app.bot:
            logger.error("Cannot send message — bot not running")
            return False
        try:
            await self._app.bot.send_message(
                chat_id=int(chat_id), text=text, parse_mode=parse_mode,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
            return False

    async def get_bot_info(self) -> dict | None:
        """Return bot username and info, or None if bot is not running."""
        if not self._app or not self._app.bot:
            return None
        try:
            bot = self._app.bot
            me = await bot.get_me()
            return {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "link": f"https://t.me/{me.username}",
            }
        except Exception as e:
            logger.error(f"Failed to get bot info: {e}")
            return None

    async def stop(self):
        """Stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped")
