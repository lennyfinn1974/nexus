"""Telegram bot integration — bridges Telegram messages to the Nexus backend."""

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logger = logging.getLogger("nexus.telegram")


class TelegramChannel:
    """Telegram bot that bridges messages to the Nexus agent."""

    def __init__(self, token: str, allowed_users: list, message_handler):
        """
        Args:
            token: Telegram bot token from @BotFather
            allowed_users: List of allowed Telegram user IDs (empty = allow all)
            message_handler: Async callable(user_id, message) -> response_text
        """
        self.token = token
        self.allowed_users = set(allowed_users) if allowed_users else set()
        self.message_handler = message_handler
        self._app = None

    def _is_authorised(self, user_id: int) -> bool:
        """Check if a user is allowed to interact with the bot."""
        if not self.allowed_users:
            return True  # No restrictions
        return user_id in self.allowed_users

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorised. Your user ID is not in the allowed list.")
            logger.warning(f"Unauthorised access attempt from user {update.effective_user.id}")
            return

        await update.message.reply_text(
            "🧠 *Nexus Agent*\n\n"
            "I'm your personal AI assistant. Send me a message and I'll help.\n\n"
            "*Commands:*\n"
            "/status — Check system status\n"
            "/skills — List learned skills\n"
            "/learn <topic> — Research and learn about a topic\n"
            "/model <claude|local> — Force a specific model\n",
            parse_mode="Markdown",
        )

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update.effective_user.id):
            return
        # Status will be injected by the main app
        status = context.bot_data.get("status_fn")
        if status:
            info = await status()
            await update.message.reply_text(f"📊 *Status*\n```\n{info}\n```", parse_mode="Markdown")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorised.")
            return

        user_id = str(update.effective_user.id)
        text = update.message.text or ""

        if not text.strip():
            return

        # Show typing indicator
        await update.message.chat.send_action("typing")

        try:
            response = await self.message_handler(user_id, text)
            # Telegram has a 4096 char limit
            if len(response) > 4000:
                chunks = [response[i:i + 4000] for i in range(0, len(response), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(response)
        except Exception as e:
            logger.error(f"Error handling Telegram message: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)[:200]}")

    async def start(self, status_fn=None):
        """Start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()

        if status_fn:
            self._app.bot_data["status_fn"] = status_fn

        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("status", self._handle_status))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started")

    async def stop(self):
        """Stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped")
