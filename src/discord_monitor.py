"""Discord monitoring client for tracking DMs, friends, and voice channels."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

import discord
import pytz

from src.config_loader import ConfigLoader
from src.state_manager import StateManager
from src.telegram_notifier import TelegramNotifier


class DiscordMonitor(discord.Client):
    """Discord self-bot client for monitoring activities."""

    def __init__(
        self,
        config: ConfigLoader,
        state: StateManager,
        notifier: TelegramNotifier,
        *args,
        **kwargs,
    ) -> None:
        """Initialize Discord monitor.

        Args:
            config: Configuration loader instance.
            state: State manager instance.
            notifier: Telegram notifier instance.
        """
        super().__init__(*args, **kwargs)
        self.config = config
        self.state = state
        self.notifier = notifier
        self.logger = logging.getLogger(__name__)
        self.timezone = pytz.timezone(config.timezone)
        self.should_monitor_voice = False
        self.monitoring_start_time = None
        self._startup_phase = False
        self._statistics_sent: bool = False

    def _format_timestamp(self, dt: datetime) -> str:
        """Format datetime to local timezone string.

        Args:
            dt: Datetime object.

        Returns:
            Formatted timestamp string.
        """
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        local_dt = dt.astimezone(self.timezone)
        return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")

    def _format_timestamp_short(self, dt: datetime) -> str:
        """Format datetime to MM/DD HH:MM:SS in local timezone."""
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        local_dt = dt.astimezone(self.timezone)
        return local_dt.strftime("%m/%d %H:%M:%S")

    @staticmethod
    def _clean_username(username: str) -> str:
        """Remove discriminator (#0) from username."""
        if username.endswith("#0"):
            return username[:-2]
        return username

    async def on_ready(self) -> None:
        """Handle client ready event."""
        self.logger.info(f"Logged in as {self.user}")
        self.monitoring_start_time = datetime.now(timezone.utc)
        try:
            self.state.delete("messages")
            self.state.delete("voice_states")
            if self.state.get("last_statistics_date") and not self.state.get("last_statistics_sent_at"):
                pass
        except Exception:
            pass
        try:
            self.logger.info(f"Discovered {len(self.guilds)} guild(s).")
        except Exception:
            pass

        await self._check_dms()

        await self._snapshot_tracked_users()

        try:
            await asyncio.sleep(1.0)
        except Exception:
            pass
        self._startup_phase = True
        await self._check_friends()
        self._startup_phase = False
        try:
            guild_count = len(self.guilds)
        except Exception:
            guild_count = 0
        now_utc = datetime.now(timezone.utc)
        today_local = self._format_timestamp(now_utc)
        today_date = today_local.split(" ")[0]
        last_sent_at = self.state.get("last_statistics_sent_at") or self.state.get("last_statistics_date")
        last_sent_date = str(last_sent_at).split(" ")[0] if last_sent_at else None
        if last_sent_date != today_date and not self._statistics_sent:
            self.logger.info("Sending daily Statistics summary")
            sent = self.notifier.send_online_summary(
                guild_count=guild_count,
                friend_total=getattr(self, "_startup_friend_total", 0),
                online_entries=[],
            )
            if sent:
                self.state.set("last_statistics_sent_at", today_local)
                self.state.delete("last_statistics_date")
                self._statistics_sent = True
                self.logger.info("Daily Statistics summary sent")
            else:
                self.logger.error("Failed to send daily Statistics summary; will retry on next run")

        await self._check_voice_channels()

        if self.should_monitor_voice:
            duration = self.config.voice_monitoring_duration
            self.logger.info(f"Monitoring voice channels for {duration} seconds.")
            await asyncio.sleep(duration)
        else:
            duration = self.config.dm_check_duration
            self.logger.info(f"Quick check completed, waiting {duration} seconds.")
            await asyncio.sleep(duration)

        self.state.save_state()
        await self.close()

    async def _check_dms(self) -> None:
        """Check for new DM messages."""
        self.logger.info("Checking DMs.")

        for channel in self.private_channels:
            is_dm = isinstance(channel, discord.DMChannel)
            group_cls = getattr(discord, "GroupChannel", None)
            is_group_dm = group_cls is not None and isinstance(channel, group_cls)
            if is_dm or is_group_dm:
                await self._process_dm_channel(channel)

    async def _process_dm_channel(self, channel: discord.DMChannel) -> None:
        """Process a single DM channel.

        Args:
            channel: Discord DM channel.
        """
        last_message_id = self.state.get_last_dm_id(channel.id)

        if not last_message_id:
            try:
                latest_id: Optional[int] = None
                async for m in channel.history(limit=1):
                    latest_id = m.id
                if latest_id:
                    self.state.set_last_dm_id(channel.id, latest_id)
                    return
            except Exception:
                pass

        async def fetch_messages_with_retries(retries: int = 3) -> List[discord.Message]:
            delay = 1
            for attempt in range(1, retries + 1):
                try:
                    msgs: List[discord.Message] = []
                    async for message in channel.history(limit=50):
                        if last_message_id and message.id <= last_message_id:
                            break
                        msgs.append(message)
                    return msgs
                except Exception as ex:
                    if attempt == retries:
                        raise ex
                    self.logger.warning(
                        f"DM history fetch failed (attempt {attempt}/{retries}) for {channel.id}: {ex}"
                    )
                    await asyncio.sleep(delay)
                    delay *= 2

            return []

        try:
            messages = await fetch_messages_with_retries()

            messages.reverse()

            grouped_messages: List[List[discord.Message]] = []
            for message in messages:
                if message.author.id == self.user.id:
                    continue

                try:
                    has_reply = False
                    async for later_msg in channel.history(limit=10, after=message):
                        if later_msg.author.id == self.user.id:
                            has_reply = True
                            break
                    if has_reply:
                        self.state.set_last_dm_id(channel.id, message.id)
                        continue
                except Exception:
                    pass

                if grouped_messages and grouped_messages[-1]:
                    last_group = grouped_messages[-1]
                    last_msg = last_group[-1]
                    time_diff = (message.created_at - last_msg.created_at).total_seconds()
                    if last_msg.author.id == message.author.id and time_diff <= 600:
                        last_group.append(message)
                    else:
                        grouped_messages.append([message])
                else:
                    grouped_messages.append([message])

            for group in grouped_messages:
                if not group:
                    continue

                first_msg = group[0]
                last_msg = group[-1]
                author = first_msg.author
                display_name = getattr(author, "display_name", str(author))
                user_id = author.id
                profile_url = f"https://discord.com/channels/@me/{user_id}"
                message_url = f"https://discord.com/channels/@me/{user_id}/{last_msg.id}"
                timestamp_short = self._format_timestamp_short(last_msg.created_at)
                timestamp_full = self._format_timestamp(last_msg.created_at)

                combined_content = "\n".join(msg.content or "" for msg in group if msg.content)

                has_attachments = any(msg.attachments for msg in group)

                if has_attachments:
                    caption = combined_content.strip()
                    first = True
                    for msg in group:
                        for att in msg.attachments:
                            url = getattr(att, "url", None) or getattr(att, "proxy_url", None)
                            if not url:
                                continue
                            cap = caption if first else ""
                            self.notifier.send_media_auto(file_url=url, caption=cap)
                            first = False
                else:
                    self.notifier.send_dm_notification(
                        display_name=display_name,
                        user_id=str(user_id),
                        content=combined_content or "[No text content]",
                        time_short=timestamp_short,
                        time_full=timestamp_full,
                        message_id=str(last_msg.id),
                        profile_url=profile_url,
                        message_url=message_url,
                    )

                self.state.set_last_dm_id(channel.id, last_msg.id)

        except Exception as e:
            self.logger.error(f"Error processing DM channel {channel.id}: {e}")

    async def _check_friends(self) -> None:
        """Check for friend profile changes."""
        self.logger.info("Checking friends.")
        attempts = 5
        for i in range(attempts):
            friends: List[discord.User] = []
            seen_ids: set[int] = set()
            try:
                rels_list = getattr(self, "friends", []) or []
                for rel in rels_list:
                    try:
                        u = getattr(rel, "user", None)
                        if u and u.id not in seen_ids:
                            seen_ids.add(u.id)
                            friends.append(u)
                    except Exception:
                        continue
            except Exception:
                pass
            try:
                rels = getattr(self, "relationships", []) or []
                for r in rels:
                    if r.type == discord.RelationshipType.friend:
                        u = r.user
                        if u and u.id not in seen_ids:
                            seen_ids.add(u.id)
                            friends.append(u)
            except Exception:
                pass

            try:
                for f in getattr(self.user, "friends", []) or []:
                    if f and f.id not in seen_ids:
                        seen_ids.add(f.id)
                        friends.append(f)
            except Exception:
                pass

            tracked = set(self.config.tracked_users or [])
            for uid in tracked:
                try:
                    u = self.get_user(uid)
                    if u and u.id not in seen_ids:
                        seen_ids.add(u.id)
                        friends.append(u)
                    if not u:
                        try:
                            fu = await self.fetch_user(uid)
                            if fu and fu.id not in seen_ids:
                                seen_ids.add(fu.id)
                                friends.append(fu)
                        except Exception:
                            pass
                except Exception:
                    continue

            if not friends and i < attempts - 1:
                await asyncio.sleep(1.0)
                continue

            self.logger.info(f"Discovered {len(friends)} friend(s).")
            if self._startup_phase:
                try:
                    self._startup_friend_total = len(friends)
                except Exception:
                    self._startup_friend_total = len(friends)
            for friend in friends:
                await self._process_friend(friend)
            break

    async def _process_friend(self, friend: discord.User) -> None:
        """Process a single friend for changes.

        Args:
            friend: Discord user object.
        """
        user_id = friend.id
        stored_state = self.state.get_user_state(user_id)
        now = datetime.now(timezone.utc)
        timestamp = self._format_timestamp(now)
        timestamp_short = self._format_timestamp_short(now)



        current_state = {
            "username": str(friend),
            "avatar": str(friend.avatar.url) if friend.avatar else None,
        }

        if current_state["avatar"] != stored_state.get("avatar"):
            new_avatar = current_state["avatar"]
            clean_user = self._clean_username(current_state["username"])
            if new_avatar:
                profile_url = f"https://discord.com/channels/@me/{friend.id}"
                user_html = f"<a href=\"{profile_url}\">{clean_user}</a>"
                caption = (
                    f"<b>👤 Profile Updated</b>\n\n"
                    f"• <b>User:</b> {user_html}\n"
                    f"• <b>Changed:</b> avatar\n"
                    f"• <b>Time:</b> {timestamp_short}"
                )
                sent = self.notifier.send_photo_with_caption(photo_url=new_avatar, caption=caption)
                if not sent:
                    self.notifier.send_profile_update_notification(
                        username=clean_user,
                        user_id=friend.id,
                        change_type="avatar",
                        old_value=stored_state.get("avatar", "None"),
                        new_value=current_state["avatar"] or "None",
                        timestamp=timestamp_short,
                    )
                avatar_changed = True
            else:
                self.notifier.send_profile_update_notification(
                    username=clean_user,
                    user_id=friend.id,
                    change_type="avatar",
                    old_value=stored_state.get("avatar", "None"),
                    new_value="None",
                    timestamp=timestamp_short,
                )
                avatar_changed = True
        else:
            avatar_changed = False

        if not avatar_changed and current_state["username"] != stored_state.get("username"):
            clean_user = self._clean_username(current_state["username"])
            self.notifier.send_profile_update_notification(
                username=clean_user,
                user_id=friend.id,
                change_type="username",
                old_value=self._clean_username(stored_state.get("username", "Unknown")),
                new_value=clean_user,
                timestamp=timestamp_short,
            )

        self.state.set_user_state(user_id, current_state)

    async def _check_voice_channels(self) -> None:
        """Check for tracked friends in voice channels."""
        self.logger.info("Checking voice channels.")

        tracked_users = self.config.tracked_users
        if not tracked_users:
            return

        for guild in self.guilds:
            for voice_channel in guild.voice_channels:
                await self._process_voice_channel(voice_channel, tracked_users, guild.id)

    async def _process_voice_channel(
        self,
        channel: discord.VoiceChannel,
        tracked_users: List[int],
        guild_id: int,
    ) -> None:
        """Process a single voice channel.

        Args:
            channel: Discord voice channel.
            tracked_users: List of user IDs to track.
            guild_id: Guild ID for building channel URL.
        """
        for member in channel.members:
            if member.id not in tracked_users:
                continue

            other_members = [
                {"username": self._clean_username(str(m)), "user_id": m.id}
                for m in channel.members if m.id != member.id
            ]
            timestamp_short = self._format_timestamp_short(datetime.now(timezone.utc))

            self.notifier.send_voice_channel_notification(
                username=self._clean_username(str(member)),
                user_id=member.id,
                action="in",
                channel_name=channel.name,
                channel_id=channel.id,
                server_name=channel.guild.name,
                guild_id=guild_id,
                members=other_members,
                timestamp=timestamp_short,
            )
            self.should_monitor_voice = True

    async def on_message(self, message: discord.Message) -> None:
        """Handle new message event.

        Args:
            message: Discord message object.
        """
        if isinstance(message.channel, discord.DMChannel):
            if message.author.id == self.user.id:
                return

            timestamp_full = self._format_timestamp(message.created_at)
            timestamp_short = self._format_timestamp_short(message.created_at)
            content = message.content or "[No text content]"

            if message.attachments:
                content += f"\n[{len(message.attachments)} attachment(s)]"

            author = message.author
            display_name = getattr(author, "display_name", str(author))
            user_id = author.id
            profile_url = f"https://discord.com/channels/@me/{user_id}"
            message_url = f"https://discord.com/channels/@me/{user_id}/{message.id}"

            self.notifier.send_dm_notification(
                display_name=display_name,
                user_id=str(user_id),
                content=content,
                time_short=timestamp_short,
                time_full=timestamp_full,
                message_id=str(message.id),
                profile_url=profile_url,
                message_url=message_url,
            )

            self.state.set_last_dm_id(message.channel.id, message.id)
            return

        try:
            if getattr(message, "mentions", None):
                if any(u.id == self.user.id for u in message.mentions):
                    if message.guild:
                        tg = getattr(self.config, "tracked_guilds", [])
                        if tg and message.guild.id not in tg:
                            return
                    guild_name = getattr(message.guild, "name", "Unknown") if message.guild else "Unknown"
                    channel_name = getattr(message.channel, "name", "DM")
                    sender_display = getattr(message.author, "display_name", str(message.author))
                    time_full = self._format_timestamp(message.created_at)
                    time_short = self._format_timestamp_short(message.created_at)
                    if message.guild and hasattr(message.channel, "id"):
                        message_url = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
                    else:
                        message_url = ""
                    content = message.content or "[No text content]"
                    if message.attachments:
                        content += f"\n[{len(message.attachments)} attachment(s)]"
                    self.notifier.send_mention_notification(
                        guild_name=guild_name,
                        channel_name=channel_name,
                        sender_display=sender_display,
                        message_url=message_url,
                        content=content,
                        time_short=time_short,
                        time_full=time_full,
                    )
        except Exception:
            pass
        return

    async def _snapshot_tracked_users(self) -> None:
        """Build and persist snapshot for all tracked users, sending diffs if any."""
        tracked = self.config.tracked_users or []
        if not tracked:
            return
        for uid in tracked:
            user = self.get_user(uid)
            if not user:
                try:
                    user = await self.fetch_user(uid)
                except Exception:
                    user = None
            if not user:
                continue
            await self._process_friend(user)

    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        """Handle message edit event.

        Args:
            before: Message before edit.
            after: Message after edit.
        """
        if not isinstance(after.channel, discord.DMChannel):
            return

        if after.author.id == self.user.id:
            return

        timestamp = self._format_timestamp(after.edited_at or datetime.now(timezone.utc))

        self.notifier.send_message_edit_notification(
            sender=str(after.author),
            old_content=before.content or "[No text content]",
            new_content=after.content or "[No text content]",
            timestamp=timestamp,
        )

    async def on_message_delete(self, message: discord.Message) -> None:
        """Handle message delete event.

        Args:
            message: Deleted message object.
        """
        if not isinstance(message.channel, discord.DMChannel):
            return

        if message.author.id == self.user.id:
            return

        timestamp = self._format_timestamp(datetime.now(timezone.utc))
        content = message.content or "[Unknown content]"

        self.notifier.send_message_delete_notification(
            sender=str(message.author),
            content=content,
            timestamp=timestamp,
        )

    async def on_reaction_add(
        self,
        reaction: discord.Reaction,
        user: discord.User,
    ) -> None:
        """Handle reaction add event.

        Args:
            reaction: Reaction object.
            user: User who added the reaction.
        """
        if not isinstance(reaction.message.channel, discord.DMChannel):
            return

        if user.id == self.user.id:
            return

        timestamp = self._format_timestamp(datetime.now())
        message_content = reaction.message.content or "[No text content]"

        self.notifier.send_reaction_notification(
            sender=str(user),
            emoji=str(reaction.emoji),
            message_content=message_content,
            timestamp=timestamp,
        )

    async def on_relationship_remove(self, relationship: discord.Relationship) -> None:
        """Handle relationship removal event.

        Args:
            relationship: Removed relationship object.
        """
        if relationship.type == discord.RelationshipType.friend:
            timestamp = self._format_timestamp(datetime.now())
            self.notifier.send_friend_removed_notification(
                username=str(relationship.user),
                timestamp=timestamp,
            )

            self.state.set_user_state(relationship.user.id, {})
