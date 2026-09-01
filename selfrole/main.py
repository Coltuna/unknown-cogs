import asyncio
import logging
import typing

import discord
from redbot.core import Config, app_commands, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import bold, box, inline
from redbot.core.utils.mod import get_audit_reason

log = logging.getLogger("red.unknown.selfrole")

_DANGEROUS_PERMISSIONS_VALUE: int = discord.Permissions(
    administrator=True,
    ban_members=True,
    kick_members=True,
    manage_channels=True,
    manage_emojis=True,
    manage_events=True,
    manage_guild=True,
    manage_messages=True,
    manage_nicknames=True,
    manage_roles=True,
    manage_threads=True,
    manage_webhooks=True,
    mention_everyone=True,
    moderate_members=True,
).value


class SelfRole(commands.Cog):
    """
    Self-assignable roles with slash commands for users and management text commands for admins.
    """

    __author__ = "unknown.in"
    __version__ = "0.1.0"

    def __init__(self, bot: Red):
        super().__init__()
        self.bot: Red = bot
        self.config: Config = Config.get_conf(self, identifier=800721211893481515, force_registration=True)
        default_guild = {"roles": [], "allow_dangerous_role": False}
        self.config.register_guild(**default_guild)

        # In-memory cache
        self.guild_cache: dict[int, dict] = {}

    def format_help_for_context(self, ctx: commands.Context):
        helpcmd = super().format_help_for_context(ctx)
        txt = f"Version: {self.__version__}\nAuthor: {self.__author__}"
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
        self.guild_cache = await self.config.all_guilds()

    def _get_guild_data(self, guild_id: int) -> dict:
        if guild_id not in self.guild_cache:
            self.guild_cache[guild_id] = {"roles": [], "allow_dangerous_role": False}
        return self.guild_cache[guild_id]

    def _prune_and_get_roles(self, guild: discord.Guild) -> tuple[list[discord.Role], bool]:
        guild_data = self._get_guild_data(guild.id)
        role_ids: list[int] = list(guild_data.get("roles", []))
        allow_dangerous = guild_data.get("allow_dangerous_role", False)

        valid_roles: list[discord.Role] = []
        invalid_role_ids: list[int] = []
        for r_id in role_ids:
            role = guild.get_role(r_id)
            if role is not None:
                valid_roles.append(role)
            else:
                invalid_role_ids.append(r_id)

        if invalid_role_ids:
            cleaned_roles = [r_id for r_id in role_ids if r_id not in invalid_role_ids]
            guild_data["roles"] = cleaned_roles
            asyncio.create_task(self.config.guild(guild).roles.set(cleaned_roles))

        return valid_roles, allow_dangerous

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        guild_data = self.guild_cache.get(role.guild.id)
        if guild_data and role.id in guild_data.get("roles", []):
            roles = [r_id for r_id in guild_data["roles"] if r_id != role.id]
            guild_data["roles"] = roles
            await self.config.guild(role.guild).roles.set(roles)

    selfrole = app_commands.Group(
        name="selfrole",
        description="Add, remove, or list self-assignable roles",
        guild_only=True,
    )

    @selfrole.command(name="add", description="Add a self-assignable role to yourself.")
    @app_commands.guild_only()
    async def selfrole_add(self, interaction: discord.Interaction, role: discord.Role):
        guild_data = self._get_guild_data(interaction.guild.id)
        if role.id not in guild_data.get("roles", []):
            return await interaction.response.send_message(
                f"{role.mention} is not configured as a self-assignable role.", ephemeral=True
            )
        if role in interaction.user.roles:
            return await interaction.response.send_message("You already have that role.", ephemeral=True)
        if not interaction.guild.me.guild_permissions.manage_roles or interaction.guild.me.top_role <= role:
            return await interaction.response.send_message(
                "I do not have sufficient permissions or role hierarchy to assign that role.", ephemeral=True
            )
        try:
            audit_reason = get_audit_reason(
                interaction.guild, reason="SelfRole slash command", author=interaction.user
            )
            await interaction.user.add_roles(role, reason=audit_reason)
            await interaction.response.send_message(f"Added the {bold(role.name)} role.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to add that role.", ephemeral=True)
        except discord.HTTPException as ex:
            await interaction.response.send_message("Something went wrong while adding the role.", ephemeral=True)
            log.error(ex)

    @selfrole.command(name="remove", description="Remove a self-assignable role from yourself.")
    @app_commands.guild_only()
    async def selfrole_remove(self, interaction: discord.Interaction, role: discord.Role):
        guild_data = self._get_guild_data(interaction.guild.id)
        if role.id not in guild_data.get("roles", []):
            return await interaction.response.send_message(
                f"{role.mention} is not configured as a self-assignable role.", ephemeral=True
            )
        if role not in interaction.user.roles:
            return await interaction.response.send_message("You do not have that role.", ephemeral=True)
        if not interaction.guild.me.guild_permissions.manage_roles or interaction.guild.me.top_role <= role:
            return await interaction.response.send_message(
                "I do not have sufficient permissions or role hierarchy to remove that role.", ephemeral=True
            )
        try:
            audit_reason = get_audit_reason(
                interaction.guild, reason="SelfRole slash command", author=interaction.user
            )
            await interaction.user.remove_roles(role, reason=audit_reason)
            await interaction.response.send_message(f"Removed the {bold(role.name)} role.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to remove that role.", ephemeral=True)
        except discord.HTTPException as ex:
            await interaction.response.send_message("Something went wrong while removing the role.", ephemeral=True)
            log.error(ex)

    @selfrole.command(name="list", description="List all self-assignable roles.")
    @app_commands.guild_only()
    async def selfrole_list(self, interaction: discord.Interaction):
        valid_roles, allow_dangerous = self._prune_and_get_roles(interaction.guild)
        if not valid_roles:
            return await interaction.response.send_message("There are currently no selfroles available.", ephemeral=True)

        formatted_selfroles = "\n".join(["+ " + r.name for r in valid_roles])
        msg = f"Allow Dangerous Roles:\n{allow_dangerous}\n\nAvailable Selfroles:\n{formatted_selfroles}"
        await interaction.response.send_message(box(msg, "diff"))

    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    @commands.group(name="selfroleset")
    async def selfroleset(self, ctx: commands.Context) -> None:
        """
        Manage self-assignable roles for this server.
        """
        pass

    @selfroleset.command(name="add")
    async def selfroleset_add(self, ctx: commands.Context, *, role: discord.Role) -> None:
        """
        Add a role to the list of self-assignable roles.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        if role.id in guild_data.get("roles", []):
            return await ctx.send(f"{role.mention} is already a self-assignable role.")

        if not self.pass_member_hierarchy_check(ctx.author, ctx.guild, role):
            return await ctx.send(
                f"I cannot let you add {bold(role.name)} as a selfrole because that role is higher than or equal to your highest role in the Discord hierarchy."
            )

        if not guild_data.get("allow_dangerous_role", False) and not self.pass_dangerous_role_check(role):
            return await ctx.send(
                f"{bold(role.name)} has dangerous permissions. If you really wish to make this role self-assignable, please enable the setting via {inline(f'{ctx.prefix}selfroleset allow_dangerous_role true')}."
            )

        roles = list(guild_data.get("roles", []))
        roles.append(role.id)
        guild_data["roles"] = roles
        await self.config.guild(ctx.guild).roles.set(roles)
        await ctx.send(f"{bold(role.name)} is now added to the self-assignable roles list.")

    @selfroleset.command(name="remove")
    async def selfroleset_remove(self, ctx: commands.Context, *, role: typing.Union[discord.Role, int]) -> None:
        """
        Remove a role from the list of self-assignable roles.

        Accepts a role mention, name, or role ID (useful if the role was deleted).
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        roles = list(guild_data.get("roles", []))

        role_id = role.id if isinstance(role, discord.Role) else role
        role_name = role.name if isinstance(role, discord.Role) else f"ID {role}"

        if role_id not in roles:
            return await ctx.send(f"{bold(role_name)} is not in the self-assignable roles list.")

        roles.remove(role_id)
        guild_data["roles"] = roles
        await self.config.guild(ctx.guild).roles.set(roles)
        await ctx.send(f"{bold(role_name)} has been removed from the self-assignable roles list.")

    @checks.guildowner_or_permissions(administrator=True)
    @selfroleset.command(name="allow_dangerous_role", aliases=["allowdangerous"])
    async def selfroleset_allow_dangerous_role(self, ctx: commands.Context, status: bool) -> None:
        """
        Allow or disallow roles with elevated permissions to be configured as selfroles.
        """
        guild_data = self._get_guild_data(ctx.guild.id)
        guild_data["allow_dangerous_role"] = status
        await self.config.guild(ctx.guild).allow_dangerous_role.set(status)
        if status:
            await ctx.send(f"Addition of dangerous roles is now {bold('enabled')}.")
        else:
            await ctx.send(f"Addition of dangerous roles is now {bold('disabled')}.")

    @selfroleset.command(name="list")
    async def selfroleset_admin_list(self, ctx: commands.Context) -> None:
        """
        List all configured self-assignable roles.
        """
        valid_roles, allow_dangerous = self._prune_and_get_roles(ctx.guild)
        if not valid_roles:
            return await ctx.send("There are currently no selfroles configured.")

        formatted_selfroles = "\n".join(["+ " + r.name for r in valid_roles])
        msg = f"Allow Dangerous Roles:\n{allow_dangerous}\n\nConfigured Selfroles:\n{formatted_selfroles}"
        await ctx.send(box(msg, "diff"))

    @staticmethod
    def pass_member_hierarchy_check(member: discord.Member, guild: discord.Guild, role: discord.Role) -> bool:
        """
        Determines if a member is allowed to add/remove/edit the given role.
        """
        return member.top_role > role or member == guild.owner

    @staticmethod
    def pass_dangerous_role_check(role: discord.Role) -> bool:
        """
        Determines if a role has dangerous permissions using bitwise masking.
        """
        return (role.permissions.value & _DANGEROUS_PERMISSIONS_VALUE) == 0
