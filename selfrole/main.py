import asyncio
import logging
from typing import List
import typing

import discord
from redbot.core import commands, Config, app_commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box

log = logging.getLogger("red.unknown.selfrole")


class SelfRole(commands.Cog):
    """Description"""

    __author__ = "unknown.in"
    __version__ = "0.0.1"

    def __init__(self, bot: Red):
        super().__init__()
        self.bot: Red = bot
        self.config: Config = Config.get_conf(self, identifier=800721211893481515, force_registration=True)
        default_guild = {"roles": [], "allow_dangerous_role": False}
        self.config.register_guild(**default_guild)

        # Cache
        self.guild_cache = {}

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
        self.guild_cache = await self.config.all_guilds()

    selfrole = app_commands.Group(
        name="selfrole",
        description="Base command to add/remove selfrole",
        guild_only=True,
    )

    selfroleset = app_commands.Group(
        name="selfroleset",
        description="Base command to set selfrole list",
        guild_only=True,
    )

    @selfrole.command(name="add", description="Add a role to yourself.")
    @app_commands.guild_only()
    async def selfrole_add(self, interaction: discord.Interaction, role: discord.Role):
        guild_data = self.guild_cache.get(interaction.guild.id)
        if guild_data is None or role.id not in guild_data.get("roles"):
            return await interaction.response.send_message(
                f"{role.mention} is not assigned to be a selfrole.", ephemeral=True
            )
        try:
            if role in interaction.user.roles:
                return await interaction.response.send_message("You already have that role.", ephemeral=True)
            await interaction.user.add_roles(role, reason="Selfrole command triggered.")
            await interaction.response.send_message("Role added.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have enough permission to add that role.")
        except discord.HTTPException as ex:
            await interaction.response.send_message("Something went wrong...")
            log.error(ex)
        except Exception as e:
            log.error(e)

    @selfrole.command(name="remove", description="Remove a role from yourself")
    @app_commands.guild_only()
    async def selfrole_remove(self, interaction: discord.Interaction, role: discord.Role):
        guild_data = self.guild_cache.get(interaction.guild.id)
        if guild_data is None or role.id not in guild_data.get("roles"):
            return await interaction.response.send_message(
                f"{role.mention} is not assigned to be a selfrole.", ephemeral=True
            )
        try:
            if role not in interaction.user.roles:
                return await interaction.response.send_message(
                    "You don't have that role already.", ephemeral=True
                )
            await interaction.user.remove_roles(role, reason="Selfrole command triggered.")
            await interaction.response.send_message("Role removed.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have enough permission to remove that role.")
        except discord.HTTPException as ex:
            await interaction.response.send_message("Something went wrong...")
            log.error(ex)
        except Exception as e:
            log.error(e)

    @selfrole.command(name="list", description="List all self assignable role list.")
    @app_commands.guild_only()
    async def selfroleset_list(self, interaction: discord.Interaction):
        default_guild = {"roles": [], "allow_dangerous_role": False}
        self.guild_cache.setdefault(interaction.guild.id, default_guild)
        guild_data = self.guild_cache.get(interaction.guild.id)
        role_ids = guild_data["roles"]
        allow_dangerous_role = guild_data["allow_dangerous_role"]
        if len(role_ids) == 0:
            return await interaction.response.send_message("There are currently no selfroles.")
        roles = [interaction.guild.get_role(role_id) for role_id in role_ids]
        formatted_selfroles = "\n".join(["+ " + r.name for r in roles])
        msg = f"Allow Dangerous Roles:\n{allow_dangerous_role}\nAvailable Selfroles:\n{formatted_selfroles}"
        await interaction.response.send_message(box(msg, "diff"))

    @selfroleset.command(name="add", description="Add a role to selfrole set")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def selfroleset_add(self, interaction: discord.Interaction, role: discord.Role):
        default_guild = {"roles": [], "allow_dangerous_role": False}
        self.guild_cache.setdefault(interaction.guild.id, default_guild)
        guild_data = self.guild_cache.get(interaction.guild.id)
        if role.id in guild_data.get("roles"):
            return await interaction.response.send_message(
                f"{role.mention} is already a self assignable role."
            )
        if not self.pass_member_hierarchy_check(interaction, role):
            return await interaction.response.send_message(
                f"I cannot let you add {role.name} as a selfrole because that role is higher than or equal to your highest role in the Discord hierarchy."
            )
        if (
            guild_data["allow_dangerous_role"] == False
            and self.pass_dangerous_role_check(interaction, role) == False
        ):
            return await interaction.response.send_message(
                rf"{role.name} is a dangerous role. If you really wish to make this role as selfrole please change the setting via `\selfroleset allow_dangerous_role`"
            )
        roles = self.guild_cache[interaction.guild.id]["roles"]
        roles.append(role.id)
        self.guild_cache[interaction.guild.id]["roles"] = roles
        await self.config.guild(interaction.guild).roles.set(roles)
        await interaction.response.send_message(f"{role.name} is now added into self assignable role list.")

    @selfroleset.command(name="remove", description="Remove a role from selfrole set")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def selfroleset_remove(self, interaction: discord.Interaction, role: discord.Role):
        default_guild = {"roles": [], "allow_dangerous_role": False}
        self.guild_cache.setdefault(interaction.guild.id, default_guild)
        guild_data = self.guild_cache.get(interaction.guild.id)
        if role.id not in guild_data["roles"]:
            return await interaction.response.send_message(
                f"{role.name} is not in self assignable role list."
            )

        roles = self.guild_cache[interaction.guild.id]["roles"]
        roles.remove(role.id)
        self.guild_cache[interaction.guild.id]["roles"] = roles
        await self.config.guild(interaction.guild).roles.set(roles)
        await interaction.response.send_message(f"{role.name} is removed from self assignable role list.")

    @selfroleset.command(
        name="allow_dangerous_role",
        description="Allows roles with enhanced permissions to be added in selfrole list",
    )
    @app_commands.guild_only()
    async def selfroleset_allow_dangerous_role(self, interaction: discord.Interaction, status: bool):
        default_guild = {"roles": [], "allow_dangerous_role": False}
        self.guild_cache.setdefault(interaction.guild.id, default_guild)
        self.guild_cache[interaction.guild.id]["allow_dangerous_role"] = status
        await self.config.guild(interaction.guild).allow_dangerous_role.set(status)
        if status == False:
            await interaction.response.send_message("Addition of dangerous role is now disabled.")
        else:
            await interaction.response.send_message("Addition of dangerous role is now enabled.")

    @staticmethod
    def pass_member_hierarchy_check(interaction: discord.Interaction, role: discord.Role) -> bool:
        """
        Determines if a member is allowed to add/remove/edit the given role.
        """
        return interaction.user.top_role > role or interaction.user == interaction.guild.owner

    @staticmethod
    def pass_dangerous_role_check(interaction: discord.Interaction, role: discord.Role) -> bool:
        """
        Determines if a role is having dangerous permission or not.
        Returns False in case role has any of the below permissions.
        """
        return (
            role.permissions
            & discord.Permissions(
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
            )
        ).value == 0
