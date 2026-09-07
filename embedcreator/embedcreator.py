from __future__ import annotations

import contextlib
from copy import deepcopy
from typing import Optional

import discord
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list

from .constants import DEFAULT_CONTAINER_TEXT, DEFAULT_CONTAINER_TITLE
from .converters import (
    ContainerArgsConverter,
    EmbedArgsConverter,
    clone_container,
    container_to_embed,
    embed_to_container,
)
from .views import ContainerEditorView, EmbedEditorView


def has_container_support() -> bool:
    """Checks if the running discord.py version supports Components V2 (Container and LayoutView)."""
    return hasattr(discord.ui, "Container") and hasattr(discord.ui, "LayoutView")


class EmbedCreator(commands.Cog):
    """Create rich embeds and modern Components V2 containers using interactive buttons and modals!"""

    __author__ = ["unknown.in", "Kreusada"]
    __version__ = "2.0.0"

    def __init__(self, bot: Red):
        self.bot = bot

    def format_help_for_context(self, ctx: commands.Context) -> str:
        context = super().format_help_for_context(ctx)
        authors = humanize_list(self.__author__) if isinstance(self.__author__, list) else self.__author__
        return f"{context}\n\nAuthor: {authors}\nVersion: {self.__version__}"

    async def red_delete_data_for_user(self, **kwargs):
        return

    # ==========================================================================
    # Embed Creator Command
    # ==========================================================================

    @commands.command(aliases=["ecreate"])
    @commands.mod()
    async def embedcreate(self, ctx: commands.Context, *, options: Optional[EmbedArgsConverter] = None):
        """Create a Discord embed using an interactive builder or flags."""
        if options is None:
            options = await EmbedArgsConverter._construct_default(ctx)

        view = EmbedEditorView(ctx)
        embed: Optional[discord.Embed] = None

        if options.source:
            # Check if source has embeds
            if options.source.embeds:
                embed = deepcopy(options.source.embeds[0])
            elif has_container_support() and options.source.components:
                # Check if source message has a Container component
                with contextlib.suppress(Exception):
                    src_view = discord.ui.LayoutView.from_message(options.source)
                    for item in src_view.children:
                        if isinstance(item, discord.ui.Container):
                            embed = container_to_embed(item)
                            break

        if embed is None:
            if options.builder:
                embed = view.embed
            else:
                embed = discord.Embed()

        flags = options.get_flags()
        for name, flag in flags.items():
            if (
                gattr := getattr(options, name)
            ) != flag.default and name in options.embed_settable_attributes:
                setattr(embed, name, gattr)

        if options.image != flags["image"].default:
            embed.set_image(url=options.image)
        if options.thumbnail != flags["thumbnail"].default:
            embed.set_thumbnail(url=options.thumbnail)
        if kwargs := options.author_kwargs():
            embed.set_author(**kwargs)
        if kwargs := options.footer_kwargs():
            embed.set_footer(**kwargs)

        try:
            if options.builder:
                view.embed = embed
                view.content = options.content
                view.message = await ctx.send(view=view, embed=embed, content=options.content)
            else:
                await ctx.send(embed=embed, content=options.content)
        except discord.HTTPException as exc:
            await ctx.send(
                f"An error occurred whilst creating your embed: {box(exc.text, lang='py')}"
            )
        except Exception as exc:
            await ctx.send(
                f"An unexpected error occurred whilst creating your embed: {box(str(exc), lang='py')}"
            )

    # ==========================================================================
    # Container Creator Command (Components V2)
    # ==========================================================================

    @commands.command(aliases=["ccreate", "boxcreate"])
    @commands.mod()
    async def containercreate(self, ctx: commands.Context, *, options: Optional[ContainerArgsConverter] = None):
        """Create a Discord UI container (Components V2).

        Sends an interactive live container builder to construct modern Discord container layouts.

        The following options are supported:
        - **accent_colour/colour/color** - Accent colour for the container (e.g. #5865F2, blurple).
        - **spoiler** - Whether to flag the container as a spoiler. Defaults to false.
        - **text** - Initial markdown text block to add inside the container.
        - **image/media** - Image or media URL to add to the media gallery.
        - **thumbnail** - Thumbnail image URL to add as a section accessory.
        - **builder** - Whether the interactive builder appears. Defaults to true.
        - **source** - An existing message to extract its container or convert its embed.
        - **content** - The text sent outside of the message.
        """
        if not has_container_support():
            return await ctx.send(
                "Discord UI Containers require **discord.py >= 2.6.0** with Components V2 support. "
                f"Your bot is currently running discord.py version `{discord.__version__}`."
            )

        if options is None:
            options = await ContainerArgsConverter._construct_default(ctx)

        container: Optional[discord.ui.Container] = None

        if options.source:
            # 1. Try extracting existing container from source message
            if options.source.components:
                with contextlib.suppress(Exception):
                    src_view = discord.ui.LayoutView.from_message(options.source)
                    for item in src_view.children:
                        if isinstance(item, discord.ui.Container):
                            container = clone_container(item)
                            break

            # 2. Try converting embed from source message
            if container is None and options.source.embeds:
                container = embed_to_container(options.source.embeds[0])

        if container is None:
            container = discord.ui.Container(
                accent_colour=options.accent_colour or discord.Colour.blurple(),
                spoiler=options.spoiler or False,
            )
            if options.builder and not options.text and not options.image and not options.thumbnail:
                container.add_item(discord.ui.TextDisplay(f"# {DEFAULT_CONTAINER_TITLE}"))
                container.add_item(
                    discord.ui.TextDisplay(DEFAULT_CONTAINER_TEXT.replace("[p]", ctx.clean_prefix))
                )

        if options.accent_colour is not None:
            container.accent_colour = options.accent_colour
        if options.spoiler:
            container.spoiler = True

        if options.text:
            container.add_item(discord.ui.TextDisplay(options.text))
        if options.thumbnail:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay("*Section*"),
                    accessory=discord.ui.Thumbnail(options.thumbnail),
                )
            )
        if options.image:
            container.add_item(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(options.image)
                )
            )

        if not container.children:
            container.add_item(discord.ui.TextDisplay("[Empty Container]"))

        try:
            if options.builder:
                view = ContainerEditorView(ctx, container=container, content=options.content)
                view.message = await ctx.send(view=view, content=options.content)
            else:
                clean_view = discord.ui.LayoutView(timeout=None)
                clean_view.add_item(container)
                await ctx.send(view=clean_view, content=options.content)
        except discord.HTTPException as exc:
            await ctx.send(
                f"An error occurred whilst creating your container: {box(exc.text, lang='py')}"
            )
        except Exception as exc:
            await ctx.send(
                f"An unexpected error occurred whilst creating your container: {box(str(exc), lang='py')}"
            )
