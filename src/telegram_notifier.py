"""Telegram notification service using REST API."""

import html
import logging
import os
import time
import requests
from typing import List, Optional


class TelegramNotifier:
    """Sends notifications to Telegram using Bot API."""

    def __init__(self, bot_token: str, chat_id: str, allowed_user_ids: Optional[List[int]] = None) -> None:
        """Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot token.
            chat_id: Target chat ID to send messages to.
            allowed_user_ids: List of allowed Telegram user IDs. If provided and the
                configured chat_id is a user ID not in this list, messages will be
                rejected and a one-time unauthorized warning will be sent.
        """
        self.bot_token = bot_token
        try:
            self.chat_id = int(str(chat_id))
        except (TypeError, ValueError):
            self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.logger = logging.getLogger(__name__)
        self.allowed_user_ids = allowed_user_ids or []
        self._warned_unauthorized = False

    def _is_authorized_chat(self) -> bool:
        """Check if configured chat_id is authorized based on allowlist.

        Returns:
            True if chat_id is authorized or allowlist is empty.
        """
        if not self.allowed_user_ids:
            return True
        try:
            chat_int = int(str(self.chat_id))
        except (TypeError, ValueError):
            return True
        return chat_int in self.allowed_user_ids

    def _maybe_send_unauthorized(self) -> None:
        """Send a one-time unauthorized warning to the configured chat."""
        if self._warned_unauthorized:
            return
        text = (
            "<b>Unauthorized</b>\n\n"
            "You are not allowed to receive notifications."
        )
        try:
            requests.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except requests.exceptions.RequestException:
            pass
        self._warned_unauthorized = True

    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """Send a text message to Telegram.

        Args:
            text: Message text to send.
            parse_mode: Parse mode for formatting (HTML or Markdown).
            disable_notification: Send message silently.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        if not self._is_authorized_chat():
            self.logger.warning("Telegram chat_id is not authorized; sending unauthorized notice")
            self._maybe_send_unauthorized()
            return False

        url = f"{self.base_url}/sendMessage"

        def _chunks(s: str, n: int = 4096) -> List[str]:
            return [s[i : i + n] for i in range(0, len(s), n)] or [""]

        success = True
        for part in _chunks(text):
            payload = {
                "chat_id": self.chat_id,
                "text": part,
                "parse_mode": parse_mode,
                "disable_notification": disable_notification,
                "disable_web_page_preview": True,
            }

            attempts = 0
            last_error = None
            while attempts < 3:
                attempts += 1
                try:
                    response = requests.post(url, json=payload, timeout=20)
                    if response.ok:
                        self.logger.info("Message sent to Telegram successfully.")
                        last_error = None
                        break
                    try:
                        details = response.json()
                    except Exception:
                        details = {"text": response.text}
                    self.logger.error(
                        "Telegram API error (attempt %d): status=%s details=%s",
                        attempts,
                        response.status_code,
                        details,
                    )
                    if 500 <= response.status_code < 600:
                        time.sleep(1.0 * attempts)
                        continue
                    response.raise_for_status()
                except requests.exceptions.RequestException as e:
                    last_error = e
                    self.logger.error("Telegram request failed (attempt %d): %s", attempts, e)
                    time.sleep(1.0 * attempts)
            if last_error is not None:
                success = False
        return success

    def send_media_auto(
        self,
        file_url: str,
        caption: str = "",
        disable_notification: bool = False,
    ) -> bool:
        """Download the file_url and send to Telegram using the appropriate endpoint.

        Supports: photo, video, animation, document, audio, voice. Uses caption when provided.
        """
        if not self._is_authorized_chat():
            self.logger.warning("Telegram chat_id is not authorized; sending unauthorized notice")
            self._maybe_send_unauthorized()
            return False

        try:
            resp = requests.get(file_url, timeout=30, stream=True)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Failed to download media: {e}.")
            return False

        content_type = resp.headers.get("Content-Type", "application/octet-stream").lower()
        filename = os.path.basename(file_url.split("?")[0]) or "file"
        data = {
            "chat_id": str(self.chat_id),
            "caption": caption,
            "parse_mode": "HTML",
            "disable_notification": str(disable_notification).lower(),
        }

        def _post(endpoint: str, field_name: str) -> bool:
            url = f"{self.base_url}/{endpoint}"
            files = {
                field_name: (filename, resp.content, content_type),
            }
            try:
                r = requests.post(url, data=data, files=files, timeout=30)
                if r.ok:
                    self.logger.info(f"Media sent to Telegram successfully via {endpoint}.")
                    return True
                try:
                    details = r.json()
                except Exception:
                    details = r.text
                self.logger.error(f"Failed to send media via {endpoint}: {details}.")
                return False
            except Exception as ex:
                self.logger.error(f"Exception sending media via {endpoint}: {ex}.")
                return False

        ext = (os.path.splitext(filename)[1] or "").lower()
        if "image/" in content_type or ext in {".jpg", ".jpeg", ".png", ".webp"}:
            return _post("sendPhoto", "photo")
        if "video/" in content_type or ext in {".mp4", ".mov", ".mkv", ".webm"}:
            return _post("sendVideo", "video")
        if "audio/" in content_type and "mpeg" in content_type or ext in {".mp3", ".m4a", ".aac"}:
            return _post("sendAudio", "audio")
        if "audio/ogg" in content_type or ext in {".oga", ".ogg"}:
            return _post("sendVoice", "voice")
        if "gif" in content_type or ext == ".gif":
            return _post("sendAnimation", "animation")
        return _post("sendDocument", "document")

    def send_photo_with_caption(
        self,
        photo_url: str,
        caption: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """Send a photo with caption to Telegram.

        Args:
            photo_url: Publicly accessible image URL.
            caption: Message caption (HTML escaped by caller if needed).
            parse_mode: Telegram parse mode.
            disable_notification: Send silently.

        Returns:
            True if photo was sent successfully.
        """
        if not self._is_authorized_chat():
            self.logger.warning("Telegram chat_id is not authorized; sending unauthorized notice")
            self._maybe_send_unauthorized()
            return False

        url = f"{self.base_url}/sendPhoto"
        attempts = 0
        while attempts < 3:
            attempts += 1
            try:
                img_resp = requests.get(photo_url, timeout=20, stream=True)
                img_resp.raise_for_status()
                content_type = img_resp.headers.get("Content-Type", "application/octet-stream")
                filename = "avatar"
                if "jpeg" in content_type:
                    filename += ".jpg"
                elif "png" in content_type:
                    filename += ".png"
                else:
                    filename += ".bin"

                files = {
                    "photo": (filename, img_resp.content, content_type),
                }
                data = {
                    "chat_id": str(self.chat_id),
                    "caption": caption,
                    "parse_mode": parse_mode,
                    "disable_notification": str(disable_notification).lower(),
                }
                resp = requests.post(url, data=data, files=files, timeout=30)
                if resp.ok:
                    self.logger.info("Photo sent to Telegram successfully.")
                    return True
                try:
                    details = resp.json()
                except Exception:
                    details = {"text": resp.text}
                self.logger.error(
                    "Telegram sendPhoto error (attempt %d): status=%s details=%s",
                    attempts,
                    resp.status_code,
                    details,
                )
                if 500 <= resp.status_code < 600:
                    time.sleep(attempts)
                    continue
                resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                self.logger.error("Telegram sendPhoto failed (attempt %d): %s", attempts, e)
                time.sleep(attempts)
        return False

    def send_dm_notification(
        self,
        display_name: str,
        user_id: str,
        content: str,
        time_short: str,
        time_full: str,
        message_id: Optional[str] = None,
        profile_url: Optional[str] = None,
        message_url: Optional[str] = None,
    ) -> bool:
        """Send DM notification with links and bullet styling.

        Args:
            display_name: Sender display name.
            user_id: Sender user ID (string).
            content: Message content.
            time_short: Short time string (MM/DD HH:MM:SS).
            time_full: Full time string for tooltip/context.
            message_id: Optional message ID.
            profile_url: Optional link to sender profile DM channel.
            message_url: Optional link directly to message.

        Returns:
            True if notification was sent successfully.
        """
        es = html.escape
        name_text = es(display_name)
        time_text = es(time_short)
        if profile_url:
            name_html = f"<a href=\"{es(profile_url)}\">{name_text}</a>"
        else:
            name_html = name_text
        if message_url:
            time_html = f"<a href=\"{es(message_url)}\">{time_text}</a>"
        else:
            time_html = time_text

        text = f"<b>📩 New DM</b>\n\n"
        text += f"• <b>From:</b> {name_html}\n"
        text += f"• <b>Time:</b> {time_html}\n\n"
        text += f"{es(content)}"

        return self.send_message(text)

    def send_online_summary(
        self,
        guild_count: int,
        friend_total: int,
        online_entries: list,
    ) -> bool:
        """Send a compact statistics summary (minimal, counts only)."""
        es = html.escape
        text = (
            f"<b>👤 Statistics</b>\n\n"
            f"• <b>Total Guilds:</b> {guild_count}\n"
            f"• <b>Total Friends:</b> {friend_total}"
        )
        return self.send_message(text)

    def send_status_notification(
        self,
        display_name: str,
        user_id: str,
        status: str,
        time_short: str,
        time_full: str,
        profile_url: Optional[str] = None,
    ) -> bool:
        """Send online status notification with links and bullets."""
        es = html.escape
        status_map = {
            "online": "🟢",
            "idle": "🌙",
            "dnd": "🔴",
        }
        emoji = status_map.get(status.lower(), "🟢")
        name_html = es(display_name)
        if profile_url:
            name_html = f"<a href=\"{es(profile_url)}\">{name_html}</a>"
        time_html = es(time_short)

        text = f"<b>{emoji} Status Change</b>\n\n"
        text += f"• <b>User:</b> {name_html}\n"
        text += f"• <b>Status:</b> {es(status)}\n"
        text += f"• <b>Time:</b> {time_html}"
        return self.send_message(text)

    def send_mention_notification(
        self,
        guild_name: str,
        channel_name: str,
        sender_display: str,
        message_url: str,
        content: str,
        time_short: str,
        time_full: str,
    ) -> bool:
        """Send a notification when we are mentioned in a guild channel."""
        es = html.escape
        time_html = f"<a href=\"{es(message_url)}\">{es(time_short)}</a>"
        text = f"<b>@ Mention</b>\n\n"
        text += f"• <b>Guild:</b> {es(guild_name)}\n"
        text += f"• <b>Channel:</b> {es(channel_name)}\n"
        text += f"• <b>From:</b> {es(sender_display)}\n"
        text += f"• <b>Time:</b> {time_html}\n\n"
        text += f"{es(content)}"
        return self.send_message(text)

    def send_message_edit_notification(
        self,
        sender: str,
        old_content: str,
        new_content: str,
        timestamp: str,
    ) -> bool:
        """Send message edit notification.

        Args:
            sender: Username of the message sender.
            old_content: Original message content.
            new_content: Edited message content.
            timestamp: Formatted timestamp.

        Returns:
            True if notification was sent successfully.
        """
        es = html.escape
        text = f"<b>✏️ Message Edited</b>\n\n"
        text += f"• <b>From:</b> {es(sender)}\n"
        text += f"• <b>Time:</b> {es(timestamp)}\n\n"
        text += f"• <b>Old:</b> {es(old_content)}\n"
        text += f"• <b>New:</b> {es(new_content)}"

        return self.send_message(text)

    def send_message_delete_notification(
        self,
        sender: str,
        content: str,
        timestamp: str,
    ) -> bool:
        """Send message delete notification.

        Args:
            sender: Username of the message sender.
            content: Deleted message content.
            timestamp: Formatted timestamp.

        Returns:
            True if notification was sent successfully.
        """
        es = html.escape
        text = f"<b>🗑️ Message Deleted</b>\n\n"
        text += f"• <b>From:</b> {es(sender)}\n"
        text += f"• <b>Time:</b> {es(timestamp)}\n\n"
        text += f"• <b>Content:</b> {es(content)}"

        return self.send_message(text)

    def send_reaction_notification(
        self,
        sender: str,
        emoji: str,
        message_content: str,
        timestamp: str,
    ) -> bool:
        """Send reaction notification.

        Args:
            sender: Username who added the reaction.
            emoji: Reaction emoji.
            message_content: Content of the message that was reacted to.
            timestamp: Formatted timestamp.

        Returns:
            True if notification was sent successfully.
        """
        es = html.escape
        text = f"<b>👍 Reaction Added</b>\n\n"
        text += f"• <b>From:</b> {es(sender)}\n"
        text += f"• <b>Emoji:</b> {es(emoji)}\n"
        text += f"• <b>Time:</b> {es(timestamp)}\n\n"
        text += f"• <b>Message:</b> {es(message_content)}"

        return self.send_message(text)


    def send_profile_update_notification(
        self,
        username: str,
        user_id: int,
        change_type: str,
        old_value: str,
        new_value: str,
        timestamp: str,
    ) -> bool:
        """Send profile update notification.

        Args:
            username: User's username (cleaned).
            user_id: User's Discord ID.
            change_type: Type of change (avatar, bio, username).
            old_value: Old value.
            new_value: New value.
            timestamp: Formatted timestamp (short).

        Returns:
            True if notification was sent successfully.
        """
        es = html.escape
        profile_url = f"https://discord.com/channels/@me/{user_id}"
        user_html = f"<a href=\"{es(profile_url)}\">{es(username)}</a>"
        text = f"<b>👤 Profile Updated</b>\n\n"
        text += f"• <b>User:</b> {user_html}\n"
        text += f"• <b>Changed:</b> {es(change_type)}\n"
        text += f"• <b>Time:</b> {es(timestamp)}\n\n"
        text += f"• <b>Old:</b> {es(old_value)}\n"
        text += f"• <b>New:</b> {es(new_value)}"

        return self.send_message(text)

    def send_friend_removed_notification(
        self,
        username: str,
        timestamp: str,
    ) -> bool:
        """Send friend removed notification.

        Args:
            username: Friend's username.
            timestamp: Formatted timestamp.

        Returns:
            True if notification was sent successfully.
        """
        text = f"<b>💔 Friend Removed</b>\n\n"
        text += f"• <b>User:</b> {username}\n"
        text += f"• <b>Time:</b> {timestamp}"

        return self.send_message(text)

    def send_voice_channel_notification(
        self,
        username: str,
        user_id: int,
        action: str,
        channel_name: str,
        channel_id: int,
        server_name: str,
        guild_id: int,
        members: list,
        timestamp: str,
    ) -> bool:
        """Send voice channel activity notification.

        Args:
            username: User's username (cleaned).
            user_id: User's Discord ID.
            action: Action type (in, joined, left).
            channel_name: Voice channel name.
            channel_id: Voice channel ID.
            server_name: Server name.
            guild_id: Guild ID.
            members: List of dicts with 'username' and 'user_id'.
            timestamp: Formatted timestamp (short).

        Returns:
            True if notification was sent successfully.
        """
        action_emoji = "🔊" if action in ("joined", "in") else "🔇"

        es = html.escape
        profile_url = f"https://discord.com/channels/@me/{user_id}"
        user_html = f"<a href=\"{es(profile_url)}\">{es(username)}</a>"
        
        channel_url = f"https://discord.com/channels/{guild_id}/{channel_id}"
        channel_html = f"<a href=\"{es(channel_url)}\">{es(channel_name)}</a>"
        
        text = f"<b>{action_emoji} Voice Channel</b>\n\n"
        text += f"• <b>User:</b> {user_html}\n"
        text += f"• <b>Channel:</b> {channel_html}\n"
        text += f"• <b>Server:</b> {es(server_name)}\n"
        text += f"• <b>Time:</b> {es(timestamp)}\n"

        if members:
            member_links = []
            for m in members:
                m_name = es(m.get("username", "Unknown"))
                m_id = m.get("user_id")
                if m_id:
                    m_url = f"https://discord.com/channels/@me/{m_id}"
                    member_links.append(f"<a href=\"{es(m_url)}\">{m_name}</a>")
                else:
                    member_links.append(m_name)
            text += f"\n• <b>With:</b> {', '.join(member_links)}"

        return self.send_message(text)
