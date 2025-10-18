"""Configuration loader module for Discord monitoring system."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class ConfigLoader:
    """Loads and manages application configuration from YAML file."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        """Initialize the configuration loader.

        Args:
            config_path: Path to the configuration YAML file.
        """
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from YAML file if present; otherwise use env only."""
        if not self.config_path.exists():
            # No file; fall back to environment variables via property accessors
            self._config = {}
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
                # If file is empty or not a dict, treat as empty config
                self._config = data if isinstance(data, dict) else {}
        except Exception:
            # On YAML parse errors, treat as empty config to allow env fallback
            self._config = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key.

        Args:
            key: Configuration key in dot notation (e.g., 'discord.token').
            default: Default value if key is not found.

        Returns:
            Configuration value or default.
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value

    # ----------- Environment helpers -----------
    @staticmethod
    def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
        val = os.getenv(name)
        return val if val not in (None, "", "None") else default

    @staticmethod
    def _parse_int_list_csv(value: Optional[str]) -> List[int]:
        if not value:
            return []
        try:
            return [int(x.strip()) for x in value.split(",") if x.strip()]
        except ValueError:
            return []

    @staticmethod
    def _parse_str_list_csv(value: Optional[str]) -> List[str]:
        if not value:
            return []
        return [x.strip() for x in value.split(",") if x.strip()]

    @property
    def discord_token(self) -> str:
        """Get Discord token."""
        token = self.get("discord.token", "")
        if not token:
            token = self._get_env("DISCORD_TOKEN", "")
        return token or ""

    @property
    def telegram_bot_token(self) -> str:
        """Get Telegram bot token."""
        token = self.get("telegram.bot_token", "")
        if not token:
            token = self._get_env("TELEGRAM_BOT_TOKEN", "")
        return token or ""

    @property
    def telegram_chat_id(self) -> str:
        """Get Telegram chat ID."""
        chat_id = self.get("telegram.chat_id", "")
        if not chat_id:
            chat_id = self._get_env("TELEGRAM_CHAT_ID", "")
        return chat_id or ""

    @property
    def telegram_allowed_user_ids(self) -> List[int]:
        """Get list of allowed Telegram user IDs.

        Falls back to env TELEGRAM_ALLOWED_USER_IDS (comma-separated ints).
        Defaults to [6083322009] if not provided.
        """
        cfg_list = self.get("telegram.allowed_user_ids", []) or []
        if not cfg_list:
            env_list = self._parse_int_list_csv(self._get_env("TELEGRAM_ALLOWED_USER_IDS"))
        else:
            env_list = []

        result = list({int(x) for x in (cfg_list or [])} | set(env_list))
        if not result:
            result = [6083322009]
        return result

    @property
    def tracked_users(self) -> list:
        """Get list of tracked user IDs."""
        cfg = self.get("monitoring.tracked_users", []) or []
        if cfg:
            return cfg
        # Fallback to env variable as CSV of ints
        env_val = self._get_env("DISCORD_TRACKED_USERS")
        return self._parse_int_list_csv(env_val)

    @property
    def tracked_guilds(self) -> list:
        """Get list of tracked guild (server) IDs. Empty means monitor all."""
        cfg = self.get("monitoring.tracked_guilds", []) or []
        if cfg:
            return cfg
        env_val = self._get_env("DISCORD_TRACKED_GUILDS")
        return self._parse_int_list_csv(env_val)

    @property
    def timezone(self) -> str:
        """Get timezone for timestamps."""
        tz = self.get("monitoring.timezone", "")
        if not tz:
            tz = self._get_env("TIMEZONE", "Asia/Tehran")
        return tz or "Asia/Tehran"

    @property
    def voice_monitoring_duration(self) -> int:
        """Get voice monitoring duration in seconds."""
        val = self.get("monitoring.voice_monitoring_duration", None)
        if isinstance(val, int):
            return val
        env_val = self._get_env("VOICE_MONITORING_DURATION")
        try:
            return int(env_val) if env_val else 600
        except (TypeError, ValueError):
            return 600

    @property
    def dm_check_duration(self) -> int:
        """Get DM check duration in seconds."""
        val = self.get("monitoring.dm_check_duration", None)
        if isinstance(val, int):
            return val
        env_val = self._get_env("DM_CHECK_DURATION")
        try:
            return int(env_val) if env_val else 60
        except (TypeError, ValueError):
            return 60

    @property
    def dm_recent_window_seconds(self) -> int:
        """Optional time window to scan recent DMs for unread-like behavior."""
        val = self.get("monitoring.dm_recent_window_seconds", None)
        if isinstance(val, int) and val > 0:
            return val
        env_val = self._get_env("DM_RECENT_WINDOW_SECONDS")
        try:
            v = int(env_val) if env_val else 0
            return v if v > 0 else 0
        except (TypeError, ValueError):
            return 0

    @property
    def first_run_strategy(self) -> str:
        """Strategy for first run DM handling: 'fast_forward' or 'scan_recent'."""
        strategy = (self.get("monitoring.first_run_strategy", "") or "").strip().lower()
        if not strategy:
            strategy = (self._get_env("FIRST_RUN_STRATEGY", "fast_forward") or "fast_forward").lower()
        if strategy not in {"fast_forward", "scan_recent"}:
            strategy = "fast_forward"
        return strategy
