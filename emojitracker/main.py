import asyncio
import contextlib
import io
import json
import logging
import re
import typing
from datetime import datetime, timezone

import discord
from redbot.core import Config, app_commands, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import bold, box, humanize_list, humanize_number, inline, pagify
from redbot.core.utils.views import ConfirmView, SimpleMenu

log = logging.getLogger("red.unknown.emojitracker")

# Regex for matching custom Discord emojis: <:name:id> or <a:name:id>
_CUSTOM_EMOJI_RE = re.compile(r"<(a?):([a-zA-Z0-9_]{2,32}):([0-9]{10,22})>")

# Regex for matching common standard Unicode emojis in Python 3
_UNICODE_EMOJI_RE = re.compile(
    r"("
    r"[\U0001F1E6-\U0001F1FF]{2}|"  # Regional indicator symbols / Flags
    r"[\U0001F300-\U0001FAD6\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF]"  # Symbols & Pictographs
    r"(?:[\U0001F3FB-\U0001F3FF])?"  # Skin tone modifiers
    r"|"
    r"[\u2600-\u27BF\u2300-\u23FF\u2B50\u2B55\u203C\u2049\u2122\u2139\u2194-\u2199\u21A9-\u21AA\u2934-\u2935\u3030\u303D\u3297\u3299\u00A9\u00AE]"
    r"(?:\uFE0F)?"  # Optional variation selector
    r")"
)


class EmojiTracker(commands.Cog):
    """
    Track custom emoji, unicode emoji, and sticker usage in your server.
    """

    __author__ = "unknown.in"
    __version__ = "0.1.0"

    def __init__(self, bot: Red):
        super().__init__()
        self.bot: Red = bot
        self.config: Config = Config.get_conf(self, identifier=800721211893481515, force_registration=True)

        default_guild = {
            "enabled": True,
            "track_unicode": False,
            "ignore_bots": True,
            "ignored_channels": [],
            "ignored_roles": [],
            "emojis": {},
            "stickers": {},
        }
        self.config.register_guild(**default_guild)

        # In-memory storage for high-throughput counting and zero-latency reads
        self.guild_cache: dict[int, dict] = {}
        self._dirty_guilds: set[int] = set()
        self._sync_task: asyncio.Task | None = None

    def format_help_for_context(self, ctx: commands.Context) -> str:
        helpcmd = super().format_help_for_context(ctx)
        txt = f"Version: {self.__version__}\nAuthor: {self.__author__}"
        return f"{helpcmd}\n\n{txt}"

    async def red_delete_data_for_user(
        self,
        *,
        requester: typing.Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ) -> None:
        """
        Delete a user's usage counts across all guilds.
        """
        str_user_id = str(user_id)
        for guild_id, data in self.guild_cache.items():
            dirty = False
            for emoji_entry in data.get("emojis", {}).values():
                if "users" in emoji_entry and str_user_id in emoji_entry["users"]:
                    del emoji_entry["users"][str_user_id]
                    dirty = True
            for sticker_entry in data.get("stickers", {}).values():
                if "users" in sticker_entry and str_user_id in sticker_entry["users"]:
                    del sticker_entry["users"][str_user_id]
                    dirty = True
            if dirty:
                self._dirty_guilds.add(guild_id)

    async def red_get_data_for_user(self, *, user_id: int) -> typing.Dict[str, io.BytesIO]:
        """
        Export a user's usage statistics across all guilds.
        """
        str_user_id = str(user_id)
        user_data: dict[str, dict] = {}
        for guild_id, data in self.guild_cache.items():
            guild_emojis = {}
            guild_stickers = {}
            for emoji_key, emoji_entry in data.get("emojis", {}).items():
                if "users" in emoji_entry and str_user_id in emoji_entry["users"]:
                    guild_emojis[emoji_key] = {
                        "name": emoji_entry.get("name"),
                        "uses": emoji_entry["users"][str_user_id],
                    }
            for sticker_key, sticker_entry in data.get("stickers", {}).items():
                if "users" in sticker_entry and str_user_id in sticker_entry["users"]:
                    guild_stickers[sticker_key] = {
                        "name": sticker_entry.get("name"),
                        "uses": sticker_entry["users"][str_user_id],
                    }
            if guild_emojis or guild_stickers:
                user_data[str(guild_id)] = {
                    "emojis": guild_emojis,
                    "stickers": guild_stickers,
                }
        raw_json = json.dumps(user_data, indent=2).encode("utf-8")
        return {"emoji_tracker_user_data.json": io.BytesIO(raw_json)}

    async def cog_load(self) -> None:
        asyncio.create_task(self.initialize())

    async def cog_unload(self) -> None:
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
        await self._sync_cache_to_config(force_all=True)

    async def initialize(self) -> None:
        await self.bot.wait_until_red_ready()
        all_guilds = await self.config.all_guilds()
        for guild_id, data in all_guilds.items():
            self.guild_cache[guild_id] = data
        self._sync_task = asyncio.create_task(self._sync_loop())

    async def _sync_loop(self) -> None:
        """
        Periodic task saving modified guild cache data to persistent Config every 60 seconds.
        """
        try:
            while True:
                await asyncio.sleep(60)
                await self._sync_cache_to_config()
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            log.exception("Unexpected error in EmojiTracker periodic sync loop:", exc_info=ex)

    async def _sync_cache_to_config(self, force_all: bool = False) -> None:
        """
        Flushes dirty in-memory cache to disk/Config.
        """
        guild_ids = list(self.guild_cache.keys()) if force_all else list(self._dirty_guilds)
        self._dirty_guilds.clear()
        for guild_id in guild_ids:
            if guild_id in self.guild_cache:
                try:
                    await self.config.guild_from_id(guild_id).set(self.guild_cache[guild_id])
                except Exception as ex:
                    log.error(f"Failed to persist emoji tracker data for guild {guild_id}: {ex}")
                    self._dirty_guilds.add(guild_id)

    def _get_guild_data(self, guild_id: int) -> dict:
        if guild_id not in self.guild_cache:
            self.guild_cache[guild_id] = {
                "enabled": True,
                "track_unicode": False,
                "ignore_bots": True,
                "ignored_channels": [],
                "ignored_roles": [],
                "emojis": {},
                "stickers": {},
            }
        return self.guild_cache[guild_id]

    def _is_tracking_allowed(
        self,
        guild: discord.Guild,
        channel: typing.Union[discord.abc.GuildChannel, discord.Thread, None],
        member: typing.Union[discord.Member, discord.User, None],
    ) -> bool:
        if not guild:
            return False
        guild_data = self._get_guild_data(guild.id)
        if not guild_data.get("enabled", True):
            return False

        if member:
            if guild_data.get("ignore_bots", True) and member.bot:
                return False
            if isinstance(member, discord.Member):
                ignored_roles = set(guild_data.get("ignored_roles", []))
                if ignored_roles and any(r.id in ignored_roles for r in member.roles):
                    return False

        if channel:
            ignored_channels = set(guild_data.get("ignored_channels", []))
            channel_id = channel.id
            parent_id = getattr(channel, "parent_id", None)
            if channel_id in ignored_channels or (parent_id and parent_id in ignored_channels):
                return False

        return True

    def _record_emoji_usage(
        self,
        guild_id: int,
        user_id: int,
        emoji_id: str,
        emoji_name: str,
        animated: bool,
        is_unicode: bool,
        is_reaction: bool,
    ) -> None:
        guild_data = self._get_guild_data(guild_id)
        emojis = guild_data.setdefault("emojis", {})

        now_iso = datetime.now(timezone.utc).isoformat()
        if emoji_id not in emojis:
            emojis[emoji_id] = {
                "name": emoji_name,
                "animated": animated,
                "is_unicode": is_unicode,
                "total": 0,
                "messages": 0,
                "reactions": 0,
                "last_used": now_iso,
                "users": {},
            }

        entry = emojis[emoji_id]
        entry["name"] = emoji_name
        entry["animated"] = animated
        entry["is_unicode"] = is_unicode
        entry["total"] = entry.get("total", 0) + 1
        if is_reaction:
            entry["reactions"] = entry.get("reactions", 0) + 1
        else:
            entry["messages"] = entry.get("messages", 0) + 1
        entry["last_used"] = now_iso

        users = entry.setdefault("users", {})
        str_user_id = str(user_id)
        users[str_user_id] = users.get(str_user_id, 0) + 1

        self._dirty_guilds.add(guild_id)

    def _record_sticker_usage(
        self,
        guild_id: int,
        user_id: int,
        sticker_id: str,
        sticker_name: str,
        format_name: str,
    ) -> None:
        guild_data = self._get_guild_data(guild_id)
        stickers = guild_data.setdefault("stickers", {})

        now_iso = datetime.now(timezone.utc).isoformat()
        if sticker_id not in stickers:
            stickers[sticker_id] = {
                "name": sticker_name,
                "format": format_name,
                "total": 0,
                "last_used": now_iso,
                "users": {},
            }

        entry = stickers[sticker_id]
        entry["name"] = sticker_name
        entry["format"] = format_name
        entry["total"] = entry.get("total", 0) + 1
        entry["last_used"] = now_iso

        users = entry.setdefault("users", {})
        str_user_id = str(user_id)
        users[str_user_id] = users.get(str_user_id, 0) + 1

        self._dirty_guilds.add(guild_id)

    # -------------------------------------------------------------------------
    # Event Listeners
    # -------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.webhook_id:
            return
        if not self._is_tracking_allowed(message.guild, message.channel, message.author):
            return

        guild_id = message.guild.id
        author_id = message.author.id
        guild_data = self._get_guild_data(guild_id)
        track_unicode = guild_data.get("track_unicode", False)

        # 1. Custom Emojis in message content
        if message.content:
            custom_matches = _CUSTOM_EMOJI_RE.findall(message.content)
            for anim_str, name, eid in custom_matches:
                self._record_emoji_usage(
                    guild_id=guild_id,
                    user_id=author_id,
                    emoji_id=eid,
                    emoji_name=name,
                    animated=bool(anim_str),
                    is_unicode=False,
                    is_reaction=False,
                )

            # 2. Standard Unicode Emojis in message content (if enabled)
            if track_unicode:
                unicode_matches = _UNICODE_EMOJI_RE.findall(message.content)
                for u_char in unicode_matches:
                    self._record_emoji_usage(
                        guild_id=guild_id,
                        user_id=author_id,
                        emoji_id=u_char,
                        emoji_name=u_char,
                        animated=False,
                        is_unicode=True,
                        is_reaction=False,
                    )

        # 3. Stickers attached to message
        if message.stickers:
            for sticker_item in message.stickers:
                format_str = getattr(sticker_item.format, "name", "UNKNOWN")
                self._record_sticker_usage(
                    guild_id=guild_id,
                    user_id=author_id,
                    sticker_id=str(sticker_item.id),
                    sticker_name=sticker_item.name,
                    format_name=format_str,
                )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        channel = guild.get_channel(payload.channel_id) or guild.get_thread(payload.channel_id)
        member = payload.member
        if not member and payload.user_id:
            member = guild.get_member(payload.user_id)

        if not self._is_tracking_allowed(guild, channel, member):
            return

        guild_data = self._get_guild_data(guild.id)
        track_unicode = guild_data.get("track_unicode", False)

        if payload.emoji.is_custom_emoji():
            self._record_emoji_usage(
                guild_id=guild.id,
                user_id=payload.user_id,
                emoji_id=str(payload.emoji.id),
                emoji_name=payload.emoji.name or "custom_emoji",
                animated=payload.emoji.animated,
                is_unicode=False,
                is_reaction=True,
            )
        elif payload.emoji.is_unicode_emoji() and track_unicode:
            self._record_emoji_usage(
                guild_id=guild.id,
                user_id=payload.user_id,
                emoji_id=payload.emoji.name,
                emoji_name=payload.emoji.name,
                animated=False,
                is_unicode=True,
                is_reaction=True,
            )

    # -------------------------------------------------------------------------
    # Helper Display Functions
    # -------------------------------------------------------------------------

    @staticmethod
    def _format_emoji_display(guild: discord.Guild, emoji_key: str, emoji_entry: dict) -> str:
        if emoji_entry.get("is_unicode", False):
            return emoji_entry.get("name", emoji_key)
        emoji_id = int(emoji_key) if emoji_key.isdigit() else None
        if emoji_id:
            guild_emoji = guild.get_emoji(emoji_id)
            if guild_emoji:
                return str(guild_emoji)
            anim_str = "a" if emoji_entry.get("animated", False) else ""
            return f"<{anim_str}:{emoji_entry.get('name', 'emoji')}:{emoji_id}>"
        return emoji_entry.get("name", "custom_emoji")

    @staticmethod
    def _create_embed_pages(
        title: str,
        lines: list[str],
        color: discord.Color,
        per_page: int = 10,
        empty_msg: str = "No data recorded yet.",
    ) -> list[discord.Embed]:
        if not lines:
            embed = discord.Embed(title=title, description=empty_msg, color=color)
            return [embed]

        chunks = [lines[i : i + per_page] for i in range(0, len(lines), per_page)]
        pages = []
        total_pages = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            embed = discord.Embed(title=title, description="\n".join(chunk), color=color)
            embed.set_footer(text=f"Page {idx} of {total_pages} • Total items: {len(lines)}")
            pages.append(embed)
        return pages

    async def _send_paginated_embed(
        self,
        ctx: commands.Context | discord.Interaction,
        title: str,
        lines: list[str],
        per_page: int = 10,
        empty_msg: str = "No data recorded yet.",
    ) -> None:
        if isinstance(ctx, commands.Context):
            color = await ctx.embed_color()
        else:
            color = discord.Color.blurple()

        pages = self._create_embed_pages(title, lines, color, per_page=per_page, empty_msg=empty_msg)

        if len(pages) == 1:
            if isinstance(ctx, commands.Context):
                return await ctx.send(embed=pages[0])
            if not ctx.response.is_done():
                return await ctx.response.send_message(embed=pages[0])
            return await ctx.followup.send(embed=pages[0])

        simple_menu = SimpleMenu(
            pages,
            disable_after_timeout=True,
            use_select_menu=(len(pages) > 2),
        )

        if isinstance(ctx, commands.Context):
            await simple_menu.start(ctx)
        else:
            simple_menu.author = ctx.user
            kwargs = await simple_menu.get_page(0)
            if not ctx.response.is_done():
                await ctx.response.send_message(**kwargs)
                simple_menu.message = await ctx.original_response()
            else:
                msg = await ctx.followup.send(**kwargs)
                simple_menu.message = msg

    # -------------------------------------------------------------------------
    # User / Statistics Text Commands
    # -------------------------------------------------------------------------

    @commands.guild_only()
    @commands.group(name="emojitrack", aliases=["emojistats", "emojitracker"], invoke_without_command=True)
    async def emojitrack(self, ctx: commands.Context) -> None:
        """
        View emoji and sticker usage statistics for this server.
        """
        await ctx.send_help()

    @commands.guild_only()
    @emojitrack.command(name="server", aliases=["guild", "stats", "overview"])
    async def emojitrack_server(self, ctx: commands.Context) -> None:
        """
        Show an overview of emoji and sticker usage for this server.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        emojis = guild_data.get("emojis", {})
        stickers = guild_data.get("stickers", {})

        total_emoji_uses = sum(e.get("total", 0) for e in emojis.values())
        total_msg_emojis = sum(e.get("messages", 0) for e in emojis.values())
        total_rxn_emojis = sum(e.get("reactions", 0) for e in emojis.values())
        total_sticker_uses = sum(s.get("total", 0) for s in stickers.values())

        # Guild custom emojis and stickers
        guild_emoji_count = len(ctx.guild.emojis)
        guild_sticker_count = len(ctx.guild.stickers)

        # Most used emoji
        top_emoji_str = "None"
        if emojis:
            top_emoji_tuple = max(emojis.items(), key=lambda item: item[1].get("total", 0))
            disp = self._format_emoji_display(ctx.guild, top_emoji_tuple[0], top_emoji_tuple[1])
            top_emoji_str = f"{disp} ({humanize_number(top_emoji_tuple[1].get('total', 0))} uses)"

        # Most used sticker
        top_sticker_str = "None"
        if stickers:
            top_sticker_tuple = max(stickers.items(), key=lambda item: item[1].get("total", 0))
            top_sticker_str = f"{bold(top_sticker_tuple[1].get('name', 'Sticker'))} ({humanize_number(top_sticker_tuple[1].get('total', 0))} uses)"

        # Unused server emojis
        recorded_ids = set(emojis.keys())
        unused_guild_emojis = [e for e in ctx.guild.emojis if str(e.id) not in recorded_ids or emojis[str(e.id)].get("total", 0) == 0]
        unused_guild_stickers = [s for s in ctx.guild.stickers if str(s.id) not in stickers or stickers[str(s.id)].get("total", 0) == 0]

        embed = discord.Embed(
            title=f"📊 Emoji & Sticker Stats • {ctx.guild.name}",
            color=await ctx.embed_color(),
            timestamp=datetime.now(timezone.utc),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        embed.add_field(
            name="😀 Emoji Usage",
            value=(
                f"• {bold('Total Uses:')} {humanize_number(total_emoji_uses)}\n"
                f"• {bold('In Messages:')} {humanize_number(total_msg_emojis)}\n"
                f"• {bold('In Reactions:')} {humanize_number(total_rxn_emojis)}\n"
                f"• {bold('Unique Tracked:')} {humanize_number(len(emojis))}\n"
                f"• {bold('Top Emoji:')} {top_emoji_str}"
            ),
            inline=True,
        )

        embed.add_field(
            name="🏷️ Sticker Usage",
            value=(
                f"• {bold('Total Uses:')} {humanize_number(total_sticker_uses)}\n"
                f"• {bold('Unique Tracked:')} {humanize_number(len(stickers))}\n"
                f"• {bold('Top Sticker:')} {top_sticker_str}"
            ),
            inline=True,
        )

        embed.add_field(
            name="📦 Server Slots & Cleanup",
            value=(
                f"• {bold('Server Emojis:')} {humanize_number(guild_emoji_count)} (Unused: {humanize_number(len(unused_guild_emojis))})\n"
                f"• {bold('Server Stickers:')} {humanize_number(guild_sticker_count)} (Unused: {humanize_number(len(unused_guild_stickers))})\n"
                f"• {bold('Tracking Status:')} {'🟢 Enabled' if guild_data.get('enabled', True) else '🔴 Disabled'}"
            ),
            inline=False,
        )

        await ctx.send(embed=embed)

    @commands.guild_only()
    @emojitrack.command(name="emojis", aliases=["topemojis", "topemoji", "emojitop"])
    async def emojitrack_emojis(self, ctx: commands.Context, server_only: bool = True) -> None:
        """
        Show the most used emojis in this server.

        Pass `server_only: False` to include external/global emojis used by Nitro members.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        emojis = guild_data.get("emojis", {})

        guild_emoji_ids = {str(e.id) for e in ctx.guild.emojis}
        items = []
        for eid, data in emojis.items():
            if server_only and eid not in guild_emoji_ids:
                continue
            items.append((eid, data))

        items.sort(key=lambda x: x[1].get("total", 0), reverse=True)

        lines = []
        for idx, (eid, data) in enumerate(items, 1):
            disp = self._format_emoji_display(ctx.guild, eid, data)
            tot = data.get("total", 0)
            msg_cnt = data.get("messages", 0)
            rxn_cnt = data.get("reactions", 0)
            lines.append(f"{inline(f'#{idx:02d}')} {disp} {bold(data.get('name', 'emoji'))} — {bold(humanize_number(tot))} uses ({humanize_number(msg_cnt)} msgs, {humanize_number(rxn_cnt)} rxns)")

        filter_text = "Server Custom Emojis" if server_only else "All Tracked Emojis"
        title = f"🏆 Top Emojis ({filter_text}) • {ctx.guild.name}"
        await self._send_paginated_embed(ctx, title, lines, per_page=10, empty_msg="No emoji usage recorded yet.")

    @commands.guild_only()
    @emojitrack.command(name="leastemojis", aliases=["bottomemojis", "leastused"])
    async def emojitrack_leastemojis(self, ctx: commands.Context, server_only: bool = True) -> None:
        """
        Show the least used emojis in this server.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        emojis = guild_data.get("emojis", {})

        guild_emoji_ids = {str(e.id) for e in ctx.guild.emojis}
        items = []
        for eid, data in emojis.items():
            if server_only and eid not in guild_emoji_ids:
                continue
            items.append((eid, data))

        items.sort(key=lambda x: x[1].get("total", 0))

        lines = []
        for idx, (eid, data) in enumerate(items, 1):
            disp = self._format_emoji_display(ctx.guild, eid, data)
            tot = data.get("total", 0)
            lines.append(f"{inline(f'#{idx:02d}')} {disp} {bold(data.get('name', 'emoji'))} — {bold(humanize_number(tot))} uses")

        filter_text = "Server Custom Emojis" if server_only else "All Tracked Emojis"
        title = f"📉 Least Used Emojis ({filter_text}) • {ctx.guild.name}"
        await self._send_paginated_embed(ctx, title, lines, per_page=10, empty_msg="No emoji usage recorded yet.")

    @commands.guild_only()
    @emojitrack.command(name="unusedemojis", aliases=["unused", "unusedemoji"])
    async def emojitrack_unusedemojis(self, ctx: commands.Context) -> None:
        """
        List all custom emojis belonging to this server with 0 recorded uses.

        Useful for freeing up emoji slots!
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        emojis = guild_data.get("emojis", {})

        unused = [e for e in ctx.guild.emojis if str(e.id) not in emojis or emojis[str(e.id)].get("total", 0) == 0]

        lines = [f"{e} {inline(e.name)} (ID: {inline(str(e.id))})" for e in unused]
        title = f"🗑️ Unused Server Emojis ({len(unused)}/{len(ctx.guild.emojis)}) • {ctx.guild.name}"
        await self._send_paginated_embed(
            ctx, title, lines, per_page=15, empty_msg="🎉 Great news! All server emojis have been used at least once."
        )

    async def _list_emojis_impl(
        self,
        ctx: commands.Context | discord.Interaction,
        sort_by: str = "name",
    ) -> None:
        guild = ctx.guild
        emojis_list = list(guild.emojis)
        if not emojis_list:
            msg = "This server does not have any custom emojis."
            if isinstance(ctx, discord.Interaction):
                return await ctx.response.send_message(msg, ephemeral=True)
            return await ctx.send(msg)

        guild_data = self._get_guild_data(guild.id)
        tracked_emojis = guild_data.get("emojis", {})

        sort_lower = (sort_by or "name").strip().lower()
        if sort_lower in ("uses", "use", "usage", "top", "most"):
            emojis_list.sort(key=lambda e: tracked_emojis.get(str(e.id), {}).get("total", 0), reverse=True)
            sort_label = "Most Used"
        elif sort_lower in ("least", "leastused", "bottom"):
            emojis_list.sort(key=lambda e: tracked_emojis.get(str(e.id), {}).get("total", 0))
            sort_label = "Least Used"
        elif sort_lower in ("recent", "newest", "created", "date"):
            emojis_list.sort(key=lambda e: e.created_at or discord.utils.snowflake_time(e.id), reverse=True)
            sort_label = "Recently Added"
        elif sort_lower in ("oldest", "first"):
            emojis_list.sort(key=lambda e: e.created_at or discord.utils.snowflake_time(e.id))
            sort_label = "Oldest Added"
        elif sort_lower in ("id", "snowflake"):
            emojis_list.sort(key=lambda e: e.id)
            sort_label = "By ID"
        elif sort_lower in ("name", "alpha", "alphabetical"):
            emojis_list.sort(key=lambda e: e.name.lower())
            sort_label = "Alphabetical"
        else:
            emojis_list.sort(key=lambda e: e.name.lower())
            sort_label = "Alphabetical"

        lines = []
        for idx, e in enumerate(emojis_list, 1):
            data = tracked_emojis.get(str(e.id), {})
            tot = data.get("total", 0)
            msg_cnt = data.get("messages", 0)
            rxn_cnt = data.get("reactions", 0)

            anim_tag = " `[Anim]`" if e.animated else ""
            if tot > 0:
                usage_str = f"{bold(humanize_number(tot))} uses ({humanize_number(msg_cnt)} msgs, {humanize_number(rxn_cnt)} rxns)"
            else:
                usage_str = "0 uses (unused)"

            lines.append(
                f"{inline(f'#{idx:02d}')} {e} {bold(e.name)} ({inline(f':{e.name}:')}){anim_tag} • ID: {inline(str(e.id))} — {usage_str}"
            )

        static_count = sum(1 for e in emojis_list if not e.animated)
        anim_count = len(emojis_list) - static_count
        title = f"📋 Server Emojis ({len(emojis_list)} Total: {static_count} Static, {anim_count} Animated) [{sort_label}] • {guild.name}"
        await self._send_paginated_embed(ctx, title, lines, per_page=15, empty_msg="This server does not have any custom emojis.")

    @commands.guild_only()
    @emojitrack.command(name="list", aliases=["listemojis", "emojislist", "all", "allemojis"])
    async def emojitrack_list(
        self,
        ctx: commands.Context,
        sort_by: str = "name",
    ) -> None:
        """
        List all custom emojis in this server with their names, IDs, and usage stats.

        Optionally sort by:
        - `name` (default, alphabetical)
        - `uses` (highest usage first)
        - `least` (lowest usage first)
        - `recent` (most recently added first)
        - `id` (by Discord snowflake ID)
        """
        await self._list_emojis_impl(ctx, sort_by)

    @commands.guild_only()
    @commands.command(name="emojilist", aliases=["listemojis", "serveremojis"])
    async def emojilist(
        self,
        ctx: commands.Context,
        sort_by: str = "name",
    ) -> None:
        """
        List all custom emojis in this server with their names, IDs, and usage stats.

        Optionally sort by:
        - `name` (default, alphabetical)
        - `uses` (highest usage first)
        - `least` (lowest usage first)
        - `recent` (most recently added first)
        - `id` (by Discord snowflake ID)
        """
        await self._list_emojis_impl(ctx, sort_by)

    @commands.guild_only()
    @emojitrack.command(name="stickers", aliases=["topstickers", "stickertop"])
    async def emojitrack_stickers(self, ctx: commands.Context, server_only: bool = True) -> None:
        """
        Show the most used stickers in this server.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        stickers = guild_data.get("stickers", {})

        guild_sticker_ids = {str(s.id) for s in ctx.guild.stickers}
        items = []
        for sid, data in stickers.items():
            if server_only and sid not in guild_sticker_ids:
                continue
            items.append((sid, data))

        items.sort(key=lambda x: x[1].get("total", 0), reverse=True)

        lines = []
        for idx, (sid, data) in enumerate(items, 1):
            tot = data.get("total", 0)
            lines.append(f"{inline(f'#{idx:02d}')} 🏷️ {bold(data.get('name', 'Sticker'))} (ID: {inline(sid)}) — {bold(humanize_number(tot))} uses")

        filter_text = "Server Stickers" if server_only else "All Tracked Stickers"
        title = f"🏆 Top Stickers ({filter_text}) • {ctx.guild.name}"
        await self._send_paginated_embed(ctx, title, lines, per_page=10, empty_msg="No sticker usage recorded yet.")

    @commands.guild_only()
    @emojitrack.command(name="leaststickers", aliases=["bottomstickers", "leaststick"])
    async def emojitrack_leaststickers(self, ctx: commands.Context, server_only: bool = True) -> None:
        """
        Show the least used stickers in this server.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        stickers = guild_data.get("stickers", {})

        guild_sticker_ids = {str(s.id) for s in ctx.guild.stickers}
        items = []
        for sid, data in stickers.items():
            if server_only and sid not in guild_sticker_ids:
                continue
            items.append((sid, data))

        items.sort(key=lambda x: x[1].get("total", 0))

        lines = []
        for idx, (sid, data) in enumerate(items, 1):
            tot = data.get("total", 0)
            lines.append(f"{inline(f'#{idx:02d}')} 🏷️ {bold(data.get('name', 'Sticker'))} (ID: {inline(sid)}) — {bold(humanize_number(tot))} uses")

        filter_text = "Server Stickers" if server_only else "All Tracked Stickers"
        title = f"📉 Least Used Stickers ({filter_text}) • {ctx.guild.name}"
        await self._send_paginated_embed(ctx, title, lines, per_page=10, empty_msg="No sticker usage recorded yet.")

    @commands.guild_only()
    @emojitrack.command(name="unusedstickers", aliases=["unusedsticker"])
    async def emojitrack_unusedstickers(self, ctx: commands.Context) -> None:
        """
        List all stickers belonging to this server with 0 recorded uses.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        stickers = guild_data.get("stickers", {})

        unused = [s for s in ctx.guild.stickers if str(s.id) not in stickers or stickers[str(s.id)].get("total", 0) == 0]

        lines = [f"🏷️ {bold(s.name)} (ID: {inline(str(s.id))})" for s in unused]
        title = f"🗑️ Unused Server Stickers ({len(unused)}/{len(ctx.guild.stickers)}) • {ctx.guild.name}"
        await self._send_paginated_embed(
            ctx, title, lines, per_page=15, empty_msg="🎉 Great news! All server stickers have been used at least once."
        )

    @commands.guild_only()
    @emojitrack.command(name="emoji")
    async def emojitrack_emoji(self, ctx: commands.Context, *, emoji: str) -> None:
        """
        View in-depth stats for a specific emoji.

        Accepts an emoji mention, name, or custom emoji ID.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        emojis = guild_data.get("emojis", {})

        target_id: str | None = None
        target_entry: dict | None = None

        # Check custom emoji regex: <:name:id> or <a:name:id>
        match = _CUSTOM_EMOJI_RE.search(emoji)
        if match:
            target_id = match.group(3)
        elif emoji.isdigit():
            target_id = emoji
        elif emoji in emojis:
            target_id = emoji

        # Search by ID or name
        if target_id and target_id in emojis:
            target_entry = emojis[target_id]
        else:
            clean_name = emoji.strip(":").lower()
            for eid, data in emojis.items():
                if data.get("name", "").lower() == clean_name:
                    target_id = eid
                    target_entry = data
                    break

        if not target_entry or not target_id:
            # Check if it exists in guild but with 0 uses
            guild_emoji = discord.utils.find(
                lambda e: str(e.id) == emoji or e.name.lower() == emoji.strip(":").lower() or str(e) == emoji,
                ctx.guild.emojis,
            )
            if guild_emoji:
                embed = discord.Embed(
                    title=f"Emoji Stats • {guild_emoji.name}",
                    description=f"{guild_emoji} has **0** recorded uses in this server.",
                    color=await ctx.embed_color(),
                )
                embed.set_thumbnail(url=guild_emoji.url)
                return await ctx.send(embed=embed)

            return await ctx.send("❌ No tracking data found for that emoji.")

        # Prepare embed
        disp = self._format_emoji_display(ctx.guild, target_id, target_entry)
        embed = discord.Embed(
            title=f"Emoji Stats • {target_entry.get('name', 'emoji')}",
            color=await ctx.embed_color(),
            timestamp=datetime.now(timezone.utc),
        )

        emoji_obj = ctx.guild.get_emoji(int(target_id)) if target_id.isdigit() else None
        if emoji_obj:
            embed.set_thumbnail(url=emoji_obj.url)
        elif target_id.isdigit():
            ext = "gif" if target_entry.get("animated", False) else "png"
            embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{target_id}.{ext}")

        tot = target_entry.get("total", 0)
        msg_cnt = target_entry.get("messages", 0)
        rxn_cnt = target_entry.get("reactions", 0)
        last_used = target_entry.get("last_used")
        last_used_str = f"<t:{int(datetime.fromisoformat(last_used).timestamp())}:R>" if last_used else "Never"

        embed.add_field(
            name="📊 Usage Breakdown",
            value=(
                f"• {bold('Display:')} {disp}\n"
                f"• {bold('Total Uses:')} {humanize_number(tot)}\n"
                f"• {bold('Messages:')} {humanize_number(msg_cnt)}\n"
                f"• {bold('Reactions:')} {humanize_number(rxn_cnt)}\n"
                f"• {bold('Last Used:')} {last_used_str}"
            ),
            inline=False,
        )

        users_dict = target_entry.get("users", {})
        if users_dict:
            top_users = sorted(users_dict.items(), key=lambda x: x[1], reverse=True)[:5]
            user_lines = []
            for rank, (uid, cnt) in enumerate(top_users, 1):
                user = ctx.guild.get_member(int(uid)) or self.bot.get_user(int(uid))
                uname = user.mention if user else f"User {inline(uid)}"
                user_lines.append(f"{inline(f'#{rank}')} {uname}: {bold(humanize_number(cnt))} uses")
            embed.add_field(name="👑 Top Users", value="\n".join(user_lines), inline=False)

        await ctx.send(embed=embed)

    @commands.guild_only()
    @emojitrack.command(name="sticker")
    async def emojitrack_sticker(self, ctx: commands.Context, *, sticker: str) -> None:
        """
        View in-depth stats for a specific sticker.

        Accepts a sticker name or ID.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        stickers = guild_data.get("stickers", {})

        target_id: str | None = None
        target_entry: dict | None = None

        if sticker.isdigit() and sticker in stickers:
            target_id = sticker
            target_entry = stickers[sticker]
        else:
            clean_name = sticker.lower()
            for sid, data in stickers.items():
                if data.get("name", "").lower() == clean_name:
                    target_id = sid
                    target_entry = data
                    break

        if not target_entry or not target_id:
            guild_sticker = discord.utils.find(
                lambda s: str(s.id) == sticker or s.name.lower() == sticker.lower(), ctx.guild.stickers
            )
            if guild_sticker:
                embed = discord.Embed(
                    title=f"Sticker Stats • {guild_sticker.name}",
                    description=f"🏷️ {bold(guild_sticker.name)} has {bold('0')} recorded uses in this server.",
                    color=await ctx.embed_color(),
                )
                embed.set_thumbnail(url=guild_sticker.url)
                return await ctx.send(embed=embed)

            return await ctx.send("❌ No tracking data found for that sticker.")

        embed = discord.Embed(
            title=f"Sticker Stats • {target_entry.get('name', 'Sticker')}",
            color=await ctx.embed_color(),
            timestamp=datetime.now(timezone.utc),
        )

        sticker_obj = discord.utils.get(ctx.guild.stickers, id=int(target_id)) if target_id.isdigit() else None
        if sticker_obj:
            embed.set_thumbnail(url=sticker_obj.url)
        elif target_id.isdigit():
            embed.set_thumbnail(url=f"https://media.discordapp.net/stickers/{target_id}.png")

        tot = target_entry.get("total", 0)
        last_used = target_entry.get("last_used")
        last_used_str = f"<t:{int(datetime.fromisoformat(last_used).timestamp())}:R>" if last_used else "Never"

        embed.add_field(
            name="📊 Usage Breakdown",
            value=(
                f"• {bold('Sticker ID:')} {inline(target_id)}\n"
                f"• {bold('Total Uses:')} {humanize_number(tot)}\n"
                f"• {bold('Format:')} {inline(target_entry.get('format', 'UNKNOWN'))}\n"
                f"• {bold('Last Used:')} {last_used_str}"
            ),
            inline=False,
        )

        users_dict = target_entry.get("users", {})
        if users_dict:
            top_users = sorted(users_dict.items(), key=lambda x: x[1], reverse=True)[:5]
            user_lines = []
            for rank, (uid, cnt) in enumerate(top_users, 1):
                user = ctx.guild.get_member(int(uid)) or self.bot.get_user(int(uid))
                uname = user.mention if user else f"User {inline(uid)}"
                user_lines.append(f"{inline(f'#{rank}')} {uname}: {bold(humanize_number(cnt))} uses")
            embed.add_field(name="👑 Top Users", value="\n".join(user_lines), inline=False)

        await ctx.send(embed=embed)

    @commands.guild_only()
    @emojitrack.command(name="user", aliases=["member"])
    async def emojitrack_user(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        """
        Show emoji and sticker stats for a specific user.
        """
        target = member or ctx.author
        str_user_id = str(target.id)
        guild_data = self._get_guild_data(ctx.guild.id)
        emojis = guild_data.get("emojis", {})
        stickers = guild_data.get("stickers", {})

        # Collect user's emoji usage
        user_emojis = []
        total_user_emojis = 0
        for eid, edata in emojis.items():
            cnt = edata.get("users", {}).get(str_user_id, 0)
            if cnt > 0:
                total_user_emojis += cnt
                user_emojis.append((eid, edata, cnt))

        user_emojis.sort(key=lambda x: x[2], reverse=True)

        # Collect user's sticker usage
        user_stickers = []
        total_user_stickers = 0
        for sid, sdata in stickers.items():
            cnt = sdata.get("users", {}).get(str_user_id, 0)
            if cnt > 0:
                total_user_stickers += cnt
                user_stickers.append((sid, sdata, cnt))

        user_stickers.sort(key=lambda x: x[2], reverse=True)

        embed = discord.Embed(
            title=f"User Stats • {target.display_name}",
            color=await ctx.embed_color(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name="📈 Summary",
            value=f"• {bold('Total Emojis Used:')} {humanize_number(total_user_emojis)}\n• {bold('Total Stickers Used:')} {humanize_number(total_user_stickers)}",
            inline=False,
        )

        if user_emojis:
            top_e_lines = []
            for rank, (eid, edata, cnt) in enumerate(user_emojis[:5], 1):
                disp = self._format_emoji_display(ctx.guild, eid, edata)
                top_e_lines.append(f"{inline(f'#{rank}')} {disp} {bold(edata.get('name', 'emoji'))}: {bold(humanize_number(cnt))}")
            embed.add_field(name="😀 Favorite Emojis", value="\n".join(top_e_lines), inline=True)
        else:
            embed.add_field(name="😀 Favorite Emojis", value="None recorded", inline=True)

        if user_stickers:
            top_s_lines = []
            for rank, (sid, sdata, cnt) in enumerate(user_stickers[:5], 1):
                top_s_lines.append(f"{inline(f'#{rank}')} 🏷️ {bold(sdata.get('name', 'Sticker'))}: {bold(humanize_number(cnt))}")
            embed.add_field(name="🏷️ Favorite Stickers", value="\n".join(top_s_lines), inline=True)
        else:
            embed.add_field(name="🏷️ Favorite Stickers", value="None recorded", inline=True)

        await ctx.send(embed=embed)

    # -------------------------------------------------------------------------
    # Slash Commands Group (/emojistats)
    # -------------------------------------------------------------------------

    emojistats = app_commands.Group(
        name="emojistats",
        description="View emoji and sticker usage statistics in this server.",
        guild_only=True,
    )

    @emojistats.command(name="server", description="View server-wide emoji and sticker statistics.")
    @app_commands.guild_only()
    async def slash_server(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        guild_data = self._get_guild_data(guild.id)
        emojis = guild_data.get("emojis", {})
        stickers = guild_data.get("stickers", {})

        total_emoji_uses = sum(e.get("total", 0) for e in emojis.values())
        total_msg_emojis = sum(e.get("messages", 0) for e in emojis.values())
        total_rxn_emojis = sum(e.get("reactions", 0) for e in emojis.values())
        total_sticker_uses = sum(s.get("total", 0) for s in stickers.values())

        top_emoji_str = "None"
        if emojis:
            top_emoji_tuple = max(emojis.items(), key=lambda item: item[1].get("total", 0))
            disp = self._format_emoji_display(guild, top_emoji_tuple[0], top_emoji_tuple[1])
            top_emoji_str = f"{disp} ({humanize_number(top_emoji_tuple[1].get('total', 0))} uses)"

        top_sticker_str = "None"
        if stickers:
            top_sticker_tuple = max(stickers.items(), key=lambda item: item[1].get("total", 0))
            top_sticker_str = f"{bold(top_sticker_tuple[1].get('name', 'Sticker'))} ({humanize_number(top_sticker_tuple[1].get('total', 0))} uses)"

        recorded_ids = set(emojis.keys())
        unused_guild_emojis = [e for e in guild.emojis if str(e.id) not in recorded_ids or emojis[str(e.id)].get("total", 0) == 0]
        unused_guild_stickers = [s for s in guild.stickers if str(s.id) not in stickers or stickers[str(s.id)].get("total", 0) == 0]

        embed = discord.Embed(
            title=f"📊 Emoji & Sticker Stats • {guild.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(
            name="😀 Emoji Usage",
            value=(
                f"• {bold('Total Uses:')} {humanize_number(total_emoji_uses)}\n"
                f"• {bold('In Messages:')} {humanize_number(total_msg_emojis)}\n"
                f"• {bold('In Reactions:')} {humanize_number(total_rxn_emojis)}\n"
                f"• {bold('Unique Tracked:')} {humanize_number(len(emojis))}\n"
                f"• {bold('Top Emoji:')} {top_emoji_str}"
            ),
            inline=True,
        )

        embed.add_field(
            name="🏷️ Sticker Usage",
            value=(
                f"• {bold('Total Uses:')} {humanize_number(total_sticker_uses)}\n"
                f"• {bold('Unique Tracked:')} {humanize_number(len(stickers))}\n"
                f"• {bold('Top Sticker:')} {top_sticker_str}"
            ),
            inline=True,
        )

        embed.add_field(
            name="📦 Server Slots & Cleanup",
            value=(
                f"• {bold('Server Emojis:')} {humanize_number(len(guild.emojis))} (Unused: {humanize_number(len(unused_guild_emojis))})\n"
                f"• {bold('Server Stickers:')} {humanize_number(len(guild.stickers))} (Unused: {humanize_number(len(unused_guild_stickers))})\n"
                f"• {bold('Tracking Status:')} {'🟢 Enabled' if guild_data.get('enabled', True) else '🔴 Disabled'}"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @emojistats.command(name="emojis", description="View top emojis in this server.")
    @app_commands.describe(server_only="Whether to show only emojis uploaded to this server (default True)")
    @app_commands.guild_only()
    async def slash_emojis(self, interaction: discord.Interaction, server_only: bool = True) -> None:
        guild = interaction.guild
        guild_data = self._get_guild_data(guild.id)
        emojis = guild_data.get("emojis", {})

        guild_emoji_ids = {str(e.id) for e in guild.emojis}
        items = []
        for eid, data in emojis.items():
            if server_only and eid not in guild_emoji_ids:
                continue
            items.append((eid, data))

        items.sort(key=lambda x: x[1].get("total", 0), reverse=True)

        lines = []
        for idx, (eid, data) in enumerate(items, 1):
            disp = self._format_emoji_display(guild, eid, data)
            tot = data.get("total", 0)
            msg_cnt = data.get("messages", 0)
            rxn_cnt = data.get("reactions", 0)
            lines.append(f"{inline(f'#{idx:02d}')} {disp} {bold(data.get('name', 'emoji'))} — {bold(humanize_number(tot))} uses ({humanize_number(msg_cnt)} msgs, {humanize_number(rxn_cnt)} rxns)")

        filter_text = "Server Custom Emojis" if server_only else "All Tracked Emojis"
        title = f"🏆 Top Emojis ({filter_text}) • {guild.name}"
        await self._send_paginated_embed(interaction, title, lines, per_page=10, empty_msg="No emoji usage recorded yet.")

    @emojistats.command(name="list", description="List all emojis in this server with their names and stats.")
    @app_commands.describe(sort_by="Sort emojis by name, uses, recently added, or ID (default: name)")
    @app_commands.choices(
        sort_by=[
            app_commands.Choice(name="Alphabetical (Name)", value="name"),
            app_commands.Choice(name="Most Used", value="uses"),
            app_commands.Choice(name="Least Used", value="least"),
            app_commands.Choice(name="Recently Added", value="recent"),
            app_commands.Choice(name="Emoji ID", value="id"),
        ]
    )
    @app_commands.guild_only()
    async def slash_list(
        self,
        interaction: discord.Interaction,
        sort_by: app_commands.Choice[str] | None = None,
    ) -> None:
        sort_val = sort_by.value if sort_by else "name"
        await self._list_emojis_impl(interaction, sort_val)

    @emojistats.command(name="stickers", description="View top stickers in this server.")
    @app_commands.describe(server_only="Whether to show only stickers uploaded to this server (default True)")
    @app_commands.guild_only()
    async def slash_stickers(self, interaction: discord.Interaction, server_only: bool = True) -> None:
        guild = interaction.guild
        guild_data = self._get_guild_data(guild.id)
        stickers = guild_data.get("stickers", {})

        guild_sticker_ids = {str(s.id) for s in guild.stickers}
        items = []
        for sid, data in stickers.items():
            if server_only and sid not in guild_sticker_ids:
                continue
            items.append((sid, data))

        items.sort(key=lambda x: x[1].get("total", 0), reverse=True)

        lines = []
        for idx, (sid, data) in enumerate(items, 1):
            tot = data.get("total", 0)
            lines.append(f"{inline(f'#{idx:02d}')} 🏷️ {bold(data.get('name', 'Sticker'))} (ID: {inline(sid)}) — {bold(humanize_number(tot))} uses")

        filter_text = "Server Stickers" if server_only else "All Tracked Stickers"
        title = f"🏆 Top Stickers ({filter_text}) • {guild.name}"
        await self._send_paginated_embed(interaction, title, lines, per_page=10, empty_msg="No sticker usage recorded yet.")

    @emojistats.command(name="unused", description="View unused emojis or stickers in this server.")
    @app_commands.describe(asset_type="Choose whether to view unused emojis or stickers")
    @app_commands.choices(
        asset_type=[
            app_commands.Choice(name="Emojis", value="emojis"),
            app_commands.Choice(name="Stickers", value="stickers"),
        ]
    )
    @app_commands.guild_only()
    async def slash_unused(self, interaction: discord.Interaction, asset_type: app_commands.Choice[str]) -> None:
        guild = interaction.guild
        guild_data = self._get_guild_data(guild.id)

        if asset_type.value == "emojis":
            emojis = guild_data.get("emojis", {})
            unused = [e for e in guild.emojis if str(e.id) not in emojis or emojis[str(e.id)].get("total", 0) == 0]
            lines = [f"{e} {inline(e.name)} (ID: {inline(str(e.id))})" for e in unused]
            title = f"🗑️ Unused Server Emojis ({len(unused)}/{len(guild.emojis)}) • {guild.name}"
            empty_msg = "🎉 Great news! All server emojis have been used at least once."
        else:
            stickers = guild_data.get("stickers", {})
            unused = [s for s in guild.stickers if str(s.id) not in stickers or stickers[str(s.id)].get("total", 0) == 0]
            lines = [f"🏷️ {bold(s.name)} (ID: {inline(str(s.id))})" for s in unused]
            title = f"🗑️ Unused Server Stickers ({len(unused)}/{len(guild.stickers)}) • {guild.name}"
            empty_msg = "🎉 Great news! All server stickers have been used at least once."

        await self._send_paginated_embed(interaction, title, lines, per_page=15, empty_msg=empty_msg)

    @emojistats.command(name="user", description="View emoji and sticker usage for a specific member.")
    @app_commands.describe(member="Member to inspect (defaults to yourself)")
    @app_commands.guild_only()
    async def slash_user(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        guild = interaction.guild
        target = member or interaction.user
        str_user_id = str(target.id)
        guild_data = self._get_guild_data(guild.id)
        emojis = guild_data.get("emojis", {})
        stickers = guild_data.get("stickers", {})

        user_emojis = []
        total_user_emojis = 0
        for eid, edata in emojis.items():
            cnt = edata.get("users", {}).get(str_user_id, 0)
            if cnt > 0:
                total_user_emojis += cnt
                user_emojis.append((eid, edata, cnt))

        user_emojis.sort(key=lambda x: x[2], reverse=True)

        user_stickers = []
        total_user_stickers = 0
        for sid, sdata in stickers.items():
            cnt = sdata.get("users", {}).get(str_user_id, 0)
            if cnt > 0:
                total_user_stickers += cnt
                user_stickers.append((sid, sdata, cnt))

        user_stickers.sort(key=lambda x: x[2], reverse=True)

        embed = discord.Embed(
            title=f"User Stats • {target.display_name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name="📈 Summary",
            value=f"• {bold('Total Emojis Used:')} {humanize_number(total_user_emojis)}\n• {bold('Total Stickers Used:')} {humanize_number(total_user_stickers)}",
            inline=False,
        )

        if user_emojis:
            top_e_lines = []
            for rank, (eid, edata, cnt) in enumerate(user_emojis[:5], 1):
                disp = self._format_emoji_display(guild, eid, edata)
                top_e_lines.append(f"{inline(f'#{rank}')} {disp} {bold(edata.get('name', 'emoji'))}: {bold(humanize_number(cnt))}")
            embed.add_field(name="😀 Favorite Emojis", value="\n".join(top_e_lines), inline=True)
        else:
            embed.add_field(name="😀 Favorite Emojis", value="None recorded", inline=True)

        if user_stickers:
            top_s_lines = []
            for rank, (sid, sdata, cnt) in enumerate(user_stickers[:5], 1):
                top_s_lines.append(f"{inline(f'#{rank}')} 🏷️ {bold(sdata.get('name', 'Sticker'))}: {bold(humanize_number(cnt))}")
            embed.add_field(name="🏷️ Favorite Stickers", value="\n".join(top_s_lines), inline=True)
        else:
            embed.add_field(name="🏷️ Favorite Stickers", value="None recorded", inline=True)

        await interaction.response.send_message(embed=embed)

    # -------------------------------------------------------------------------
    # Admin / Settings Commands
    # -------------------------------------------------------------------------

    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.group(name="emojitrackset", aliases=["emojiset", "trackset"])
    async def emojitrackset(self, ctx: commands.Context) -> None:
        """
        Configure Emoji and Sticker tracking settings for this server.
        """
        pass

    @emojitrackset.command(name="toggle")
    async def emojitrackset_toggle(self, ctx: commands.Context, status: bool | None = None) -> None:
        """
        Enable or disable emoji and sticker tracking.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        current = guild_data.get("enabled", True)
        new_status = not current if status is None else status
        guild_data["enabled"] = new_status
        await self.config.guild(ctx.guild).enabled.set(new_status)
        state_str = "enabled" if new_status else "disabled"
        await ctx.send(f"Emoji and sticker tracking is now **{state_str}**.")

    @emojitrackset.command(name="trackunicode", aliases=["unicode"])
    async def emojitrackset_trackunicode(self, ctx: commands.Context, status: bool | None = None) -> None:
        """
        Toggle tracking of standard Unicode emojis.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        current = guild_data.get("track_unicode", False)
        new_status = not current if status is None else status
        guild_data["track_unicode"] = new_status
        await self.config.guild(ctx.guild).track_unicode.set(new_status)
        state_str = "enabled" if new_status else "disabled"
        await ctx.send(f"Tracking of standard Unicode emojis is now **{state_str}**.")

    @emojitrackset.command(name="ignorebots", aliases=["bots"])
    async def emojitrackset_ignorebots(self, ctx: commands.Context, status: bool | None = None) -> None:
        """
        Toggle ignoring bot messages and reactions.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        current = guild_data.get("ignore_bots", True)
        new_status = not current if status is None else status
        guild_data["ignore_bots"] = new_status
        await self.config.guild(ctx.guild).ignore_bots.set(new_status)
        state_str = "ignoring" if new_status else "tracking"
        await ctx.send(f"The tracker is now **{state_str}** bot usage.")

    @emojitrackset.group(name="ignorechannel", aliases=["channel"])
    async def emojitrackset_ignorechannel(self, ctx: commands.Context) -> None:
        """
        Manage ignored channels for emoji tracking.
        """
        pass

    @emojitrackset_ignorechannel.command(name="add")
    async def emojitrackset_ignorechannel_add(
        self, ctx: commands.Context, *, channel: discord.TextChannel | discord.VoiceChannel | discord.Thread
    ) -> None:
        """
        Add a channel to the ignored channels list.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        ignored = set(guild_data.get("ignored_channels", []))
        if channel.id in ignored:
            return await ctx.send(f"{channel.mention} is already being ignored.")
        ignored.add(channel.id)
        guild_data["ignored_channels"] = list(ignored)
        await self.config.guild(ctx.guild).ignored_channels.set(list(ignored))
        await ctx.send(f"Now ignoring emoji and sticker usage in {channel.mention}.")

    @emojitrackset_ignorechannel.command(name="remove")
    async def emojitrackset_ignorechannel_remove(
        self, ctx: commands.Context, *, channel: discord.TextChannel | discord.VoiceChannel | discord.Thread | int
    ) -> None:
        """
        Remove a channel from the ignored channels list.
        """
        channel_id = channel.id if hasattr(channel, "id") else channel
        guild_data = self._get_guild_data(ctx.guild.id)
        ignored = set(guild_data.get("ignored_channels", []))
        if channel_id not in ignored:
            return await ctx.send(f"Channel ID `{channel_id}` is not in the ignored channels list.")
        ignored.remove(channel_id)
        guild_data["ignored_channels"] = list(ignored)
        await self.config.guild(ctx.guild).ignored_channels.set(list(ignored))
        await ctx.send(f"Channel ID `{channel_id}` is no longer ignored.")

    @emojitrackset_ignorechannel.command(name="list")
    async def emojitrackset_ignorechannel_list(self, ctx: commands.Context) -> None:
        """
        List all ignored channels.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        ignored = guild_data.get("ignored_channels", [])
        if not ignored:
            return await ctx.send("No channels are currently being ignored.")

        lines = []
        for cid in ignored:
            ch = ctx.guild.get_channel(cid) or ctx.guild.get_thread(cid)
            lines.append(f"• {ch.mention if ch else f'Deleted Channel (`{cid}`)'}")
        await ctx.send(bold("Ignored Channels:\n") + "\n".join(lines))

    @emojitrackset.group(name="ignorerole", aliases=["role"])
    async def emojitrackset_ignorerole(self, ctx: commands.Context) -> None:
        """
        Manage ignored roles for emoji tracking.
        """
        pass

    @emojitrackset_ignorerole.command(name="add")
    async def emojitrackset_ignorerole_add(self, ctx: commands.Context, *, role: discord.Role) -> None:
        """
        Add a role to the ignored roles list.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        ignored = set(guild_data.get("ignored_roles", []))
        if role.id in ignored:
            return await ctx.send(f"{role.mention} is already being ignored.")
        ignored.add(role.id)
        guild_data["ignored_roles"] = list(ignored)
        await self.config.guild(ctx.guild).ignored_roles.set(list(ignored))
        await ctx.send(f"Now ignoring emoji and sticker usage from members with the {role.mention} role.")

    @emojitrackset_ignorerole.command(name="remove")
    async def emojitrackset_ignorerole_remove(
        self, ctx: commands.Context, *, role: typing.Union[discord.Role, int]
    ) -> None:
        """
        Remove a role from the ignored roles list.
        """
        role_id = role.id if isinstance(role, discord.Role) else role
        guild_data = self._get_guild_data(ctx.guild.id)
        ignored = set(guild_data.get("ignored_roles", []))
        if role_id not in ignored:
            return await ctx.send(f"Role ID `{role_id}` is not in the ignored roles list.")
        ignored.remove(role_id)
        guild_data["ignored_roles"] = list(ignored)
        await self.config.guild(ctx.guild).ignored_roles.set(list(ignored))
        await ctx.send(f"Role ID `{role_id}` is no longer ignored.")

    @emojitrackset_ignorerole.command(name="list")
    async def emojitrackset_ignorerole_list(self, ctx: commands.Context) -> None:
        """
        List all ignored roles.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        ignored = guild_data.get("ignored_roles", [])
        if not ignored:
            return await ctx.send("No roles are currently being ignored.")

        lines = []
        for rid in ignored:
            r = ctx.guild.get_role(rid)
            lines.append(f"• {r.mention if r else f'Deleted Role (`{rid}`)'}")
        await ctx.send(bold("Ignored Roles:\n") + "\n".join(lines))

    @checks.guildowner_or_permissions(administrator=True)
    @emojitrackset.command(name="reset")
    async def emojitrackset_reset(
        self, ctx: commands.Context, scope: typing.Literal["all", "emojis", "stickers"]
    ) -> None:
        """
        Reset recorded emoji/sticker tracking data for this server.

        Scopes: `all`, `emojis`, `stickers`.
        """
        view = ConfirmView(ctx.author, disable_buttons=True)
        view.message = await ctx.send(
            f"⚠️ **Warning**: Are you sure you want to completely reset **{scope}** usage data for this server?\n"
            "This action is permanent and cannot be undone.",
            view=view,
        )
        await view.wait()

        if view.result is True:
            guild_data = self._get_guild_data(ctx.guild.id)
            if scope in ("all", "emojis"):
                guild_data["emojis"] = {}
                await self.config.guild(ctx.guild).emojis.set({})
            if scope in ("all", "stickers"):
                guild_data["stickers"] = {}
                await self.config.guild(ctx.guild).stickers.set({})
            self._dirty_guilds.discard(ctx.guild.id)
            await ctx.send(f"✅ Successfully reset **{scope}** tracking data for this server.")
        else:
            await ctx.send("Reset action cancelled.")

    @emojitrackset.command(name="showsettings", aliases=["settings", "view"])
    async def emojitrackset_showsettings(self, ctx: commands.Context) -> None:
        """
        Show the current EmojiTracker configuration for this server.
        """
        guild_data = self._get_guild_data(ctx.guild.id)

        enabled = guild_data.get("enabled", True)
        track_unicode = guild_data.get("track_unicode", False)
        ignore_bots = guild_data.get("ignore_bots", True)
        ignored_channels = guild_data.get("ignored_channels", [])
        ignored_roles = guild_data.get("ignored_roles", [])
        emoji_count = len(guild_data.get("emojis", {}))
        sticker_count = len(guild_data.get("stickers", {}))

        embed = discord.Embed(
            title=f"EmojiTracker Settings • {ctx.guild.name}",
            color=await ctx.embed_color(),
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="⚙️ General Settings",
            value=(
                f"• {bold('Tracking Enabled:')} {'Yes' if enabled else 'No'}\n"
                f"• {bold('Track Unicode Emojis:')} {'Yes' if track_unicode else 'No'}\n"
                f"• {bold('Ignore Bots:')} {'Yes' if ignore_bots else 'No'}\n"
                f"• {bold('Tracked Unique Emojis:')} {humanize_number(emoji_count)}\n"
                f"• {bold('Tracked Unique Stickers:')} {humanize_number(sticker_count)}"
            ),
            inline=False,
        )

        ch_lines = [
            (ctx.guild.get_channel(cid) or ctx.guild.get_thread(cid) or f"ID {cid}").name
            for cid in ignored_channels
        ]
        ch_str = humanize_list(ch_lines) if ch_lines else "None"
        embed.add_field(name=f"🚫 Ignored Channels ({humanize_number(len(ignored_channels))})", value=ch_str, inline=False)

        role_lines = [
            (ctx.guild.get_role(rid).name if ctx.guild.get_role(rid) else f"ID {rid}")
            for rid in ignored_roles
        ]
        role_str = humanize_list(role_lines) if role_lines else "None"
        embed.add_field(name=f"🚫 Ignored Roles ({humanize_number(len(ignored_roles))})", value=role_str, inline=False)

        await ctx.send(embed=embed)
