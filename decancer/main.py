import asyncio
import logging
import random
import re
import unicodedata
import unidecode
import stringcase

import discord
from datetime import datetime, timedelta
from redbot.core import Config, checks, commands, modlog
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_timedelta
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from .randomnick import properNouns

log = logging.getLogger("red.unknown.decancer")


class Decancer(commands.Cog):
    """
    Decancer users names removing special and accented chars.

    `[p]decancerset` to get started if you're already using redbot core modlog
    """

    __author__ = ["unknown.in", "KableKompany", "PhenoM4n4n"]
    __version__ = "0.0.1"

    def __init__(self, bot: Red):
        super().__init__()
        self.bot: Red = bot
        self.config: Config = Config.get_conf(self, identifier=800721211893481515, force_registration=True)
        default_guild = {"modlogchannel": None, "new_custom_nick": "simp name", "auto": False}
        self.config.register_guild(**default_guild)
        self.enabled_guilds = set()

    def format_help_for_context(self, ctx: commands.Context):
        helpcmd = super().format_help_for_context(ctx)
        txt = "Version: {}\nAuthor: {}".format(self.__version__, self.__author__)
        return f"{helpcmd}\n\n{txt}"

    async def red_delete_data_for_user(self, *args, **kwargs):
        return

    async def red_get_data_for_user(self, *args, **kwargs):
        return

    async def cog_load(self) -> None:
        asyncio.create_task(self.initialize())

    async def cog_unload(self) -> None:
        pass

    async def initialize(self) -> None:
        await self.bot.wait_until_red_ready()
        for guild_id, guild_data in (await self.config.all_guilds()).items():
            if guild_data["auto"]:
                self.enabled_guilds.add(guild_id)

    @staticmethod
    def is_cancerous(text: str) -> bool:
        for segment in text.split():
            for char in segment:
                if not (char.isascii() and char.isalnum()):
                    return True
        return False

    @staticmethod
    def strip_accs(text):
        try:
            text = unicodedata.normalize("NFKC", text)
            text = unicodedata.normalize("NFD", text)
            text = unidecode.unidecode(text)
            text = text.encode("ascii", "ignore")
            text = text.decode("utf-8")
        except Exception as e:
            print(e)
        return str(text)

    async def nick_maker(self, guild: discord.Guild, old_nick: str) -> str:
        """
        Make a nickname from a given nickname.

        Args:
            guild (discord.Guild): The guild to get the configuration for.
            old_nick (str): The old nickname to modify.

        Returns:
            str: A new nickname that is strongly typed.
        """
        old_nick = self.strip_accs(old_nick)
        new_nick = re.sub("[^a-zA-Z0-9 \n.]", "", old_nick)
        new_nick = " ".join(new_nick.split())
        new_nick = stringcase.lowercase(new_nick)
        new_nick = stringcase.titlecase(new_nick)
        default_name = await self.config.guild(guild).new_custom_nick()
        if len(new_nick.replace(" ", "")) <= 1 or len(new_nick) > 32:
            if default_name == "random":
                new_nick = await self.get_random_nick()
            elif default_name:
                new_nick = default_name
            else:
                new_nick = "simp name"
        return new_nick

    async def get_random_nick(self) -> str:
        """
        Get a random nickname.

        Returns:
            str: A random nickname from the list of proper nouns.
        """
        new_nick: str = random.choice(properNouns)
        return new_nick

    async def decancer_log(
        self,
        guild: discord.Guild,
        member: discord.Member,
        moderator: discord.Member,
        old_nick: str,
        new_nick: str,
        dc_type: str,
    ) -> None:
        """
        Logs a moderation event.

        Args:
            guild (discord.Guild): The guild in which the moderation event occurred.
            member (discord.Member): The user who was moderated.
            moderator (discord.Member): The user who performed the moderation action.
            old_nick (str): The user's old nickname.
            new_nick (str): The user's new nickname.
            dc_type (str): The type of moderation event.

        Returns:
            None
        """
        channel_id: int = await self.config.guild(guild).modlogchannel()
        if not channel_id:
            return
        channel: discord.abc.GuildChannel = guild.get_channel(channel_id)
        if not channel or not (
            channel.permissions_for(guild.me).send_messages and channel.permissions_for(guild.me).embed_links
        ):
            await self.config.guild(guild).modlogchannel.clear()
            return
        data = {
            "offender": f"{member} {member.mention}",
            "reason": "Remove cancerous characters from previous name",
            "old_nick": old_nick,
            "new_nick": new_nick,
            "moderator": f"{moderator} {moderator.mention}",
        }
        embed: discord.Embed = discord.Embed(
            title=dc_type, timestamp=datetime.utcnow(), color=discord.Color(0x2FFFFF)
        ).set_footer(text=f"ID: {member.id}")
        embed.description = "\n".join(f"**{k}**: {v}" for k, v in data.items())
        await channel.send(embed=embed)

    @commands.command(name="decancer")
    @checks.mod_or_permissions(manage_nicknames=True)
    @checks.bot_has_permissions(manage_nicknames=True)
    @commands.guild_only()
    async def _decancer(self, ctx: commands.Context, member: discord.Member) -> None:
        """
        Remove special/cancerous characters from user nicknames

        Parameters:
            ctx (commands.Context): The command invocation context.
            member (discord.Member): The user who's nickname is being modified.

        Returns:
            None
        """
        if member.top_role >= ctx.me.top_role:
            return await ctx.send(f"I can't decancer that user since they are higher than me in heirarchy.")

        old_nick = member.display_name
        new_nick = await self.nick_maker(ctx.guild, old_nick)
        if old_nick == new_nick:
            return await ctx.send("The nickname is already decancered.")
        try:
            await member.edit(reason=f"Nickname decancered by {ctx.author.name}", nick=new_nick)
            await ctx.send(f"({old_nick}) was changed to {new_nick}")
            await self.decancer_log(ctx.guild, member, ctx.author, old_nick, new_nick, "decancer")
        except discord.Forbidden:
            await ctx.send("I do not have proper permission to change the nickname")
        except discord.HTTPException:
            await ctx.send("Something went wrong...")

    @commands.guild_only()
    @commands.admin()
    @commands.group(name="decancerset")
    async def _decancer_set(self, ctx: commands.Context) -> None:
        """
        Settings for Decancer
        """
        pass

    @commands.guild_only()
    @_decancer_set.command(name="auto")
    async def _decancer_set_auto(self, ctx: commands.Context, status: bool | None = None) -> None:
        """
        Toggle automatically decancering new users.

        Args:
            status (bool | None): If True, then new users will be decancered. If False, they will not.
                If None, then the current setting will be toggled.
        """
        current_status: bool = await self.config.guild(ctx.guild).auto()
        if status is None:
            new_status: bool = not current_status
        else:
            new_status: bool = status
        await self.config.guild(ctx.guild).auto.set(new_status)
        if new_status:
            await ctx.send("New users will be decancered from now.")
        else:
            await ctx.send("New users will not be decancered from now.")

    @commands.guild_only()
    @_decancer_set.command(name="modlog")
    async def _decancer_set_modlogchannel(
        self, ctx: commands.Context, channel: discord.TextChannel | None = None
    ) -> None:
        """
        Set the modlog channel for Decancer.

        Args:
            channel (discord.TextChannel | None): The channel to log to. If `None`, the current channel will be used.
        """
        channel = channel or ctx.channel
        await self.config.guild(ctx.guild).modlogchannel.set(channel.id)
        await ctx.send(f"Decancer will now log to {channel.mention} for mod actions.")

    @commands.guild_only()
    @_decancer_set.command(name="defaultname")
    async def _decancer_set_defaultname(self, ctx: commands.Context, name: str) -> None:
        """
        Set the default name for new users.

        Args:
            name (str): The name to use for new users.
        """
        await self.config.guild(ctx.guild).new_custom_nick.set(name)
        await ctx.send(f"New users will be named {name} from now.")

    @commands.guild_only()
    @_decancer_set.command(name="showsettings", aliases=["settings", "ss"])
    async def _decancer_show_settings(self, ctx: commands.Context) -> discord.Message:
        """
        Shows the current settings for Decancer.

        Args:
            ctx (commands.Context): The invocation context.

        Returns:
            discord.Message: The sent message with the settings.
        """
        modlog_channel = ctx.guild.get_channel(await self.config.guild(ctx.guild).modlogchannel())
        embed = discord.Embed(title="Decancer Settings")
        embed.add_field(name="Auto Decancer", value=await self.config.guild(ctx.guild).auto(), inline=False)
        embed.add_field(
            name="Modlog Channel", value=modlog_channel.mention if modlog_channel else "None", inline=False
        )
        embed.add_field(
            name="Default Nickname", value=await self.config.guild(ctx.guild).new_custom_nick(), inline=False
        )
        return await ctx.send(embed=embed)

    @commands.max_concurrency(1, commands.BucketType.guild)
    @commands.cooldown(1, 36000, commands.BucketType.guild)
    @checks.mod_or_permissions(manage_nicknames=True)
    @checks.bot_has_permissions(manage_nicknames=True)
    @commands.guild_only()
    @commands.command(cooldown_after_parsing=True, name="dehoist")
    async def _dehoist(self, ctx: commands.Context, *, role: discord.Role = None):
        """Decancer all members of the targeted role.

        Role defaults to all members of the server."""
        if not await self.config.guild(ctx.guild).modlogchannel():
            await ctx.send(f"Set up a modlog for this server using `{ctx.prefix}decancerset modlog #channel`")
            ctx.command.reset_cooldown(ctx)
            return
        role = role or ctx.guild.default_role
        guild = ctx.guild
        cancerous_list = [
            member
            for member in role.members
            if not member.bot and self.is_cancerous(member.display_name) and ctx.me.top_role > member.top_role
        ]
        if not cancerous_list:
            await ctx.send(f"There's no one I can decancer in **`{role}`**.")
            ctx.command.reset_cooldown(ctx)
            return
        member_preview = "\n".join(
            f"{member} - {member.id}" for index, member in enumerate(cancerous_list, 1) if index <= 10
        ) + (f"\nand {len(cancerous_list) - 10} other members.." if len(cancerous_list) > 10 else "")

        case = "" if len(cancerous_list) == 1 else "s"
        msg = await ctx.send(
            f"Are you sure you want me to decancer the following {len(cancerous_list)} member{case}?\n"
            + box(member_preview, "py")
        )
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(msg, ctx.author)
        try:
            await self.bot.wait_for("reaction_add", check=pred, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("Action cancelled.")
            ctx.command.reset_cooldown(ctx)
            return
        if pred.result is True:
            await ctx.send(
                f"Ok. This will take around **{humanize_timedelta(timedelta=timedelta(seconds=len(cancerous_list) * 1.5))}**."
            )
            async with ctx.typing():
                for member in cancerous_list:
                    await asyncio.sleep(1)
                    old_nick = member.display_name
                    new_nick = await self.nick_maker(guild, member.display_name)
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
            ctx.command.reset_cooldown(ctx)
            return

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild: discord.Guild = member.guild
        if guild.id not in self.enabled_guilds:
            return

        data = await self.config.guild(guild).all()

        if not data["auto"] or not guild.me.guild_permissions.manage_nicknames:
            return

        old_nick = member.display_name

        if not self.is_cancerous(old_nick):
            return

        await asyncio.sleep(5)  # wait for automod actions to finish
        member = guild.get_member(member.id)
        if not member:
            return
        if member.top_role >= guild.me.top_role:
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
