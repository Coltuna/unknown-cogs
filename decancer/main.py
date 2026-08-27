import asyncio
import logging
import random
import re
import typing
import unicodedata
import unidecode

import discord
from datetime import datetime, timezone, timedelta
from redbot.core import Config, checks, commands, modlog
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_timedelta
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from .randomnick import properNouns

log = logging.getLogger("red.unknown.decancer")

_NON_ALPHANUM_RE = re.compile(r"[^a-zA-Z0-9 \n.]")


class Decancer(commands.Cog):
    """
    Decancer usernames by removing special and accented characters.
    """

    __author__ = ["unknown.in", "KableKompany", "PhenoM4n4n"]
    __version__ = "0.1.0"

    def __init__(self, bot: Red):
        super().__init__()
        self.bot: Red = bot
        self.config: Config = Config.get_conf(self, identifier=800721211893481515, force_registration=True)
        default_guild = {"new_custom_nick": "simp name", "auto": False}
        self.config.register_guild(**default_guild)
        self.enabled_guilds: set[int] = set()

    def format_help_for_context(self, ctx: commands.Context):
        helpcmd = super().format_help_for_context(ctx)
        txt = "Version: {}\nAuthor: {}".format(self.__version__, ", ".join(self.__author__))
        return f"{helpcmd}\n\n{txt}"

    async def red_delete_data_for_user(self, *args, **kwargs):
        return

    async def red_get_data_for_user(self, *args, **kwargs):
        return

    async def cog_load(self) -> None:
        await self.register_casetypes()
        asyncio.create_task(self.initialize())

    async def cog_unload(self) -> None:
        pass

    @staticmethod
    async def register_casetypes():
        casetypes = [
            {
                "name": "decancer",
                "default_setting": True,
                "image": "\N{NAME BADGE}",
                "case_str": "Decancer",
            },
            {
                "name": "auto-decancer",
                "default_setting": True,
                "image": "\N{NAME BADGE}",
                "case_str": "Auto-Decancer",
            },
        ]
        try:
            await modlog.register_casetypes(casetypes)
        except RuntimeError:
            pass

    async def initialize(self) -> None:
        await self.bot.wait_until_red_ready()
        for guild_id, guild_data in (await self.config.all_guilds()).items():
            if guild_data.get("auto", False):
                self.enabled_guilds.add(guild_id)

    @staticmethod
    def is_cancerous(text: str) -> bool:
        return any(not (c.isascii() and c.isalnum()) for c in text if not c.isspace())

    @staticmethod
    def strip_accs(text: str) -> str:
        try:
            text = unicodedata.normalize("NFKC", text)
            text = unidecode.unidecode(text)
            text = text.encode("ascii", "ignore").decode("utf-8")
        except Exception as e:
            log.debug(f"Error stripping accents: {e}")
        return str(text)

    async def nick_maker(self, guild: discord.Guild, old_nick: str, default_name: str | None = None) -> str:
        old_nick = self.strip_accs(old_nick)
        new_nick = _NON_ALPHANUM_RE.sub("", old_nick)
        new_nick = " ".join(new_nick.split()).title()
        if len(new_nick.replace(" ", "")) <= 1 or len(new_nick) > 32:
            if default_name is None:
                default_name = await self.config.guild(guild).new_custom_nick()
            if default_name == "random":
                new_nick = await self.get_random_nick()
            elif default_name:
                new_nick = default_name
            else:
                new_nick = "simp name"
        return new_nick

    async def get_random_nick(self) -> str:
        return random.choice(properNouns)

    async def decancer_log(
        self,
        guild: discord.Guild,
        member: discord.Member,
        moderator: discord.Member | None,
        old_nick: str,
        new_nick: str,
        dc_type: str,
    ) -> None:
        try:
            await modlog.create_case(
                bot=self.bot,
                guild=guild,
                created_at=datetime.now(timezone.utc),
                action_type=dc_type,
                user=member,
                moderator=moderator,
                reason=f"Old name ({old_nick}): contained special characters -> {new_nick}",
            )
        except Exception as e:
            log.debug(f"Failed to create modlog case: {e}")

    @commands.command(name="decancer", aliases=["dehoist"])
    @checks.mod_or_permissions(manage_nicknames=True)
    @checks.bot_has_permissions(manage_nicknames=True, add_reactions=True)
    @commands.guild_only()
    async def _decancer(
        self, ctx: commands.Context, *, target: typing.Union[discord.Member, discord.Role] = None
    ) -> None:
        """
        Remove special/cancerous characters from a member or all members of a role.

        - If target is a member, decancers that member's nickname.
        - If target is a role (or omitted), decancers all members with that role (or the whole server).
        """
        if isinstance(target, discord.Member):
            if target.top_role >= ctx.me.top_role:
                return await ctx.send("I can't decancer that user since they are higher than or equal to me in hierarchy.")
            if ctx.author != ctx.guild.owner and target.top_role >= ctx.author.top_role:
                return await ctx.send("You cannot decancer a member with an equal or higher role than yourself.")

            old_nick = target.display_name
            new_nick = await self.nick_maker(ctx.guild, old_nick)
            if old_nick == new_nick:
                return await ctx.send("The nickname is already decancered.")
            try:
                await target.edit(reason=f"Nickname decancered by {ctx.author.name}", nick=new_nick)
                await ctx.send(f"({old_nick}) was changed to {new_nick}")
                await self.decancer_log(ctx.guild, target, ctx.author, old_nick, new_nick, "decancer")
            except discord.Forbidden:
                await ctx.send("I do not have proper permissions to change that nickname.")
            except discord.HTTPException:
                await ctx.send("Something went wrong while changing the nickname.")
            return

        role = target or ctx.guild.default_role
        guild = ctx.guild
        cancerous_list = [
            member
            for member in role.members
            if not member.bot
            and self.is_cancerous(member.display_name)
            and ctx.me.top_role > member.top_role
            and (ctx.author == ctx.guild.owner or ctx.author.top_role > member.top_role)
        ]
        if not cancerous_list:
            return await ctx.send(f"There's no one I can decancer in **`{role.name}`**.")

        member_preview = "\n".join(
            f"{member} - {member.id}" for index, member in enumerate(cancerous_list, 1) if index <= 10
        ) + (f"\nand {len(cancerous_list) - 10} other members.." if len(cancerous_list) > 10 else "")

        case = "" if len(cancerous_list) == 1 else "s"
        msg = await ctx.send(
            f"Are you sure you want me to decancer the following {len(cancerous_list)} member{case} in **`{role.name}`**?\n"
            + box(member_preview, "py")
        )
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(msg, ctx.author)
        try:
            await self.bot.wait_for("reaction_add", check=pred, timeout=60)
        except asyncio.TimeoutError:
            return await ctx.send("Action cancelled.")
        if pred.result is True:
            await ctx.send(
                f"Ok. This will take around **{humanize_timedelta(timedelta=timedelta(seconds=len(cancerous_list) * 1.5))}**."
            )
            default_name = await self.config.guild(guild).new_custom_nick()
            async with ctx.typing():
                for member in cancerous_list:
                    await asyncio.sleep(1)
                    old_nick = member.display_name
                    new_nick = await self.nick_maker(guild, member.display_name, default_name=default_name)
                    if old_nick.lower() != new_nick.lower():
                        try:
                            await member.edit(
                                reason=f"Dehoist | Old name ({old_nick}): contained special characters",
                                nick=new_nick,
                            )
                            await self.decancer_log(
                                ctx.guild, member, ctx.author, old_nick, new_nick, "decancer"
                            )
                        except discord.Forbidden:
                            await ctx.send("Dehoist failed due to invalid permissions.")
                            return
                        except discord.NotFound:
                            continue
            try:
                await ctx.send("Dehoist completed.")
            except (discord.NotFound, discord.Forbidden):
                pass
        else:
            await ctx.send("Action cancelled.")

    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @commands.group(name="decancerset")
    async def _decancer_set(self, ctx: commands.Context) -> None:
        """
        Settings for Decancer.
        """
        pass

    @commands.guild_only()
    @_decancer_set.command(name="auto")
    async def _decancer_set_auto(self, ctx: commands.Context, status: bool | None = None) -> None:
        """
        Toggle automatically decancering new users on join.
        """
        current_status: bool = await self.config.guild(ctx.guild).auto()
        if status is None:
            new_status: bool = not current_status
        else:
            new_status: bool = status
        await self.config.guild(ctx.guild).auto.set(new_status)
        if new_status:
            self.enabled_guilds.add(ctx.guild.id)
            await ctx.send("New users will now be automatically decancered upon joining.")
        else:
            self.enabled_guilds.discard(ctx.guild.id)
            await ctx.send("New users will not be automatically decancered.")

    @commands.guild_only()
    @_decancer_set.command(name="defaultname")
    async def _decancer_set_defaultname(self, ctx: commands.Context, name: str) -> None:
        """
        Set the default nickname for users when their nickname cannot be decancered.

        Pass `random` to assign a random name from the built-in noun list.
        """
        await self.config.guild(ctx.guild).new_custom_nick.set(name)
        await ctx.send(f"Fallback nickname set to: `{name}`.")

    @commands.guild_only()
    @checks.bot_has_permissions(embed_links=True)
    @_decancer_set.command(name="showsettings", aliases=["settings", "ss"])
    async def _decancer_show_settings(self, ctx: commands.Context) -> discord.Message:
        """
        Show the current Decancer settings for this server.
        """
        embed = discord.Embed(title="Decancer Settings", color=await ctx.embed_color())
        embed.add_field(name="Auto Decancer", value=str(await self.config.guild(ctx.guild).auto()), inline=False)
        embed.add_field(
            name="Default Nickname", value=await self.config.guild(ctx.guild).new_custom_nick(), inline=False
        )
        return await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild: discord.Guild = member.guild
        if guild.id not in self.enabled_guilds or not guild.me.guild_permissions.manage_nicknames:
            return

        old_nick = member.display_name
        if not self.is_cancerous(old_nick):
            return

        await asyncio.sleep(5)  # wait for automod actions to finish
        member = guild.get_member(member.id)
        if not member or member.top_role >= guild.me.top_role:
            return

        new_cool_nick = await self.nick_maker(guild, old_nick)
        if old_nick.lower() != new_cool_nick.lower():
            try:
                await member.edit(
                    reason=f"Auto Decancer | Old name ({old_nick}): contained special characters",
                    nick=new_cool_nick,
                )
                await self.decancer_log(guild, member, guild.me, old_nick, new_cool_nick, "auto-decancer")
            except discord.Forbidden:
                await self.config.guild(guild).auto.set(False)
                self.enabled_guilds.discard(guild.id)
