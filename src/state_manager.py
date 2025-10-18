"""State management for tracking Discord changes between runs."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional


class StateManager:
    """Manages persistent state for tracking changes between runs."""

    def __init__(self, state_file: str = "state.json") -> None:
        """Initialize state manager.

        Args:
            state_file: Path to the state file.
        """
        self.state_file = Path(state_file)
        self.logger = logging.getLogger(__name__)
        self._state: Dict[str, Any] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
                self.logger.info("State loaded successfully.")
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to load state: {e}.")
                self._state = {}
        else:
            self.logger.info("No existing state file found, starting fresh.")
            self._state = {}

    def save_state(self) -> None:
        """Save current state to file."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
            self.logger.info("State saved successfully.")
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}.")

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from state.

        Args:
            key: State key.
            default: Default value if key doesn't exist.

        Returns:
            State value or default.
        """
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set value in state.

        Args:
            key: State key.
            value: Value to set.
        """
        self._state[key] = value

    def delete(self, key: str) -> None:
        """Delete a key from state if present.

        Args:
            key: State key to remove.
        """
        try:
            self._state.pop(key, None)
        except Exception:
            pass

    def get_last_dm_id(self, channel_id: int) -> Optional[int]:
        """Get last processed DM message ID for a channel.

        Args:
            channel_id: Discord channel ID.

        Returns:
            Last message ID or None.
        """
        dms = self.get("last_dm_ids", {})
        return dms.get(str(channel_id))

    def set_last_dm_id(self, channel_id: int, message_id: int) -> None:
        """Set last processed DM message ID for a channel.

        Args:
            channel_id: Discord channel ID.
            message_id: Last processed message ID.
        """
        dms = self.get("last_dm_ids", {})
        dms[str(channel_id)] = message_id
        self.set("last_dm_ids", dms)

    def get_user_state(self, user_id: int) -> Dict[str, Any]:
        """Get stored state for a user.

        Args:
            user_id: Discord user ID.

        Returns:
            User state dictionary.
        """
        users = self.get("users", {})
        return users.get(str(user_id), {})

    def set_user_state(self, user_id: int, state: Dict[str, Any]) -> None:
        """Set state for a user.

        Args:
            user_id: Discord user ID.
            state: User state dictionary.
        """
        users = self.get("users", {})
        users[str(user_id)] = state
        self.set("users", users)

    def get_voice_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get voice channel state for a user.

        Args:
            user_id: Discord user ID.

        Returns:
            Voice state dictionary or None.
        """
        voice_states = self.get("voice_states", {})
        return voice_states.get(str(user_id))

    def set_voice_state(self, user_id: int, state: Optional[Dict[str, Any]]) -> None:
        """Set voice channel state for a user.

        Args:
            user_id: Discord user ID.
            state: Voice state dictionary or None to clear.
        """
        voice_states = self.get("voice_states", {})
        if state is None:
            voice_states.pop(str(user_id), None)
        else:
            voice_states[str(user_id)] = state
        self.set("voice_states", voice_states)

    def get_message_content(self, message_id: int) -> Optional[str]:
        """Get stored message content.

        Args:
            message_id: Discord message ID.

        Returns:
            Message content or None.
        """
        messages = self.get("messages", {})
        return messages.get(str(message_id))

    def set_message_content(self, message_id: int, content: str) -> None:
        """Store message content for tracking edits/deletes.

        Args:
            message_id: Discord message ID.
            content: Message content.
        """
        messages = self.get("messages", {})
        messages[str(message_id)] = content
        self.set("messages", messages)

    def remove_message_content(self, message_id: int) -> Optional[str]:
        """Remove and return stored message content.

        Args:
            message_id: Discord message ID.

        Returns:
            Removed message content or None.
        """
        messages = self.get("messages", {})
        content = messages.pop(str(message_id), None)
        self.set("messages", messages)
        return content

    # ---------------- Notified message tracking ----------------
    def get_notified_message_ids(self) -> set:
        """Return a set of message IDs that were already notified."""
        ids = self.get("notified_message_ids", []) or []
        return set(str(x) for x in ids)

    def mark_notified(self, message_id: int) -> None:
        """Mark a message ID as notified."""
        ids = list(self.get_notified_message_ids())
        sid = str(message_id)
        if sid not in ids:
            ids.append(sid)
        if len(ids) > 5000:
            ids = ids[-3000:]
        self.set("notified_message_ids", ids)
