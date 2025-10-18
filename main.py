"""Main entry point for Discord monitoring system."""

import asyncio
import logging
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import sys

import discord

from src.config_loader import ConfigLoader
from src.discord_monitor import DiscordMonitor
from src.state_manager import StateManager
from src.telegram_notifier import TelegramNotifier


class _ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",    # cyan
        "INFO": "\033[32m",     # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[35m", # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        levelname = f"{color}{record.levelname}{self.RESET}"
        record.levelname = levelname
        msg = super().format(record)
        return msg

def setup_logging() -> None:
    """Configure colored logging for the application and silence noisy libs."""
    handler = logging.StreamHandler()
    handler.setFormatter(_ColorFormatter("%(asctime)s - %(levelname)s - %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]

    logging.getLogger("discord.state").setLevel(logging.ERROR)
    logging.getLogger("discord.client").setLevel(logging.INFO)

    logger = logging.getLogger(__name__)
    now_utc = datetime.now(timezone.utc)
    log_file_path = Path("discord_monitor.log")
    
    try:
        if log_file_path.exists():
            with open(log_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            cutoff_time = now_utc.timestamp() - 86400
            filtered_lines = []
            removed_count = 0
            
            for line in lines:
                try:
                    timestamp_str = line.split(" - ")[0]
                    log_dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                    log_dt = log_dt.replace(tzinfo=timezone.utc)
                    
                    if log_dt.timestamp() >= cutoff_time:
                        filtered_lines.append(line)
                    else:
                        removed_count += 1
                except Exception:
                    filtered_lines.append(line)
            
            if removed_count > 0:
                with open(log_file_path, "w", encoding="utf-8") as f:
                    f.writelines(filtered_lines)
                logger.info("Pruned %d old log entries from discord_monitor.log", removed_count)
            else:
                logger.info("No log entries older than 24h to prune.")
        else:
            logger.info("No existing log file to prune.")
    except Exception as exc:
        logger.warning("Failed to prune old log entries: %s", exc)

    file_handler = TimedRotatingFileHandler(
        "discord_monitor.log",
        when="midnight",
        interval=1,
        backupCount=1,
        encoding="utf-8",
        utc=True,
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    root.addHandler(file_handler)


def validate_config(config: ConfigLoader) -> bool:
    """Validate required configuration values.

    Args:
        config: Configuration loader instance.

    Returns:
        True if configuration is valid, False otherwise.
    """
    logger = logging.getLogger(__name__)

    if not config.discord_token:
        logger.error("Discord token is not configured.")
        return False

    if not config.telegram_bot_token:
        logger.error("Telegram bot token is not configured.")
        return False

    if not config.telegram_chat_id:
        logger.error("Telegram chat ID is not configured.")
        return False

    return True


async def main() -> None:
    """Main application entry point."""
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        # Load configuration
        config = ConfigLoader("config.yaml")
        logger.info("Configuration loaded successfully.")

        # Validate configuration
        if not validate_config(config):
            logger.error("Configuration validation failed.")
            sys.exit(1)

        # Initialize components
        state = StateManager("state.json")
        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
            allowed_user_ids=config.telegram_allowed_user_ids,
        )

        client_kwargs = {
            "config": config,
            "state": state,
            "notifier": notifier,
        }
        try:
            intents = getattr(discord, "Intents").default()
            intents.guilds = True
            intents.members = True
            intents.presences = True
            intents.messages = True
            intents.dm_messages = True
            client_kwargs["intents"] = intents
            client_kwargs["chunk_guilds_at_startup"] = False
        except Exception:
            pass

        try:
            client = DiscordMonitor(**client_kwargs)
        except TypeError:
            client_kwargs.pop("chunk_guilds_at_startup", None)
            client = DiscordMonitor(**client_kwargs)
        try:
            from discord.state import State  # type: ignore

            if hasattr(State, "parse_ready_supplemental"):
                _orig_parse_ready_supplemental = State.parse_ready_supplemental  # type: ignore[attr-defined]

                def _patched_parse_ready_supplemental(self, data):  # type: ignore[no-redef]
                    try:
                        if data.get("pending_payments") is None:
                            data["pending_payments"] = []
                    except Exception:
                        pass
                    return _orig_parse_ready_supplemental(self, data)  # type: ignore[misc]

                State.parse_ready_supplemental = _patched_parse_ready_supplemental  # type: ignore[assignment]
        except Exception:
            logger.debug("No patch needed or patch failed; continuing.")

        try:
            from discord import http as _discord_http  # type: ignore

            def _fixed_ua() -> str:
                return (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/141.0.0.0 Safari/537.36"
                )

            if hasattr(_discord_http, "get_user_agent"):
                _discord_http.get_user_agent = _fixed_ua  # type: ignore[assignment]
        except Exception:
            logger.debug("Could not set fixed Discord UA; continuing.")

        logger.info("Starting Discord monitor.")
        await client.start(config.discord_token, reconnect=False)

    except FileNotFoundError as e:
        logger.error(f"Configuration file not found: {e}.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}.", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
