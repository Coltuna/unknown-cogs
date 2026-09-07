.. _embedcreator:

============
EmbedCreator
============

This is the cog guide for the 'EmbedCreator' cog. This guide
contains the collection of commands which you can use in the cog.

Through this guide, ``[p]`` will always represent your prefix. Replace
``[p]`` with your own prefix when you use these commands in Discord.

.. note::

    This guide was updated for version 2.0.0. Ensure
    that you are up to date by running ``[p]cog update embedcreator``.

--------------
About this cog
--------------

Create rich embeds and modern Discord Components V2 containers using interactive buttons, modals and dropdowns!

--------
Commands
--------

Here are all the commands included in this cog (2):

+------------------------+------------------------------------------------------------------------------------------------------------------------------------------------+
| Command                | Help                                                                                                                                           |
+========================+================================================================================================================================================+
| ``[p]embedcreate``     | Create an embed.                                                                                                                               |
| (alias: ``[p]ecreate``)|                                                                                                                                                |
|                        | The command will send an interactive menu to construct an embed, unless otherwise specified by the **builder** option described further below. |
|                        |                                                                                                                                                |
|                        | The following options are supported:                                                                                                           |
|                        |                                                                                                                                                |
|                        | - **title** - Embed title.                                                                                                                     |
|                        | - **description** - Embed description.                                                                                                         |
|                        | - **colour/color** - A valid colour or hex code.                                                                                               |
|                        | - **url** - A valid URL for the embed's title hyperlink.                                                                                       |
|                        | - **image** - A valid URL for the embed's image.                                                                                               |
|                        | - **thumbnail** - A valid URL for the embed's thumbnail.                                                                                       |
|                        | - **author_name** - The name of the embed's author.                                                                                            |
|                        | - **author_url** - A valid URL for the author's hyperlink.                                                                                     |
|                        | - **author_icon_url** - A valid URL for the author's icon image.                                                                               |
|                        | - **footer_name** - Text for the footer.                                                                                                       |
|                        | - **footer_icon_url** - A valid URL for the footer's icon image.                                                                               |
|                        | - **builder** - Whether this help menu appears along with the constructor buttons. Defaults to true.                                           |
|                        | - **source** - An existing message to use its embed or container. Can be a link or message ID.                                                 |
|                        | - **content** - The text sent outside of the message.                                                                                          |
+------------------------+------------------------------------------------------------------------------------------------------------------------------------------------+
| ``[p]containercreate`` | Create a Discord UI container (Components V2).                                                                                                 |
| (alias: ``[p]ccreate``,|                                                                                                                                                |
| ``[p]boxcreate``)      | Sends an interactive live builder to construct modern Discord container layouts.                                                             |
|                        |                                                                                                                                                |
|                        | The following options are supported:                                                                                                           |
|                        |                                                                                                                                                |
|                        | - **accent_colour/colour/color** - Accent colour for the container (e.g. #5865F2, blurple).                                                    |
|                        | - **spoiler** - Whether to flag the container as a spoiler. Defaults to false.                                                                 |
|                        | - **text** - Initial markdown text block to add inside the container.                                                                          |
|                        | - **image/media** - Image or media URL to add to the media gallery.                                                                           |
|                        | - **thumbnail** - Thumbnail image URL to add as a section accessory.                                                                           |
|                        | - **builder** - Whether the interactive builder appears. Defaults to true.                                                                     |
|                        | - **source** - An existing message to extract its container or convert its embed.                                                             |
|                        | - **content** - The text sent outside of the message.                                                                                          |
+------------------------+------------------------------------------------------------------------------------------------------------------------------------------------+

------------
Installation
------------

.. code-block::

    [p]cog install unknown-cogs embedcreator
    [p]load embedcreator
