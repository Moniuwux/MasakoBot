"""Reacciones anime adicionales con comandos prefix y slash."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, cast

import discord
from discord.ext import commands

from utils.nekos_api import InvalidCategoryError, NekosBestError, client as nekos_client

log = logging.getLogger(__name__)
COLOR = discord.Color.fuchsia()


@dataclass(frozen=True, slots=True)
class ReactionConfig:
    """Texto y categoría visual de una reacción."""

    emoji: str
    verb_self: str
    verb_other: str
    source: str


REACTIONS: dict[str, ReactionConfig] = {
    "boom": ReactionConfig("💥", "provoca una explosión de anime", "provoca una explosión de anime sobre", "shoot"),
    "heal": ReactionConfig("💚", "se cura mágicamente", "cura mágicamente a", "hug"),
    "sape": ReactionConfig("👋", "se da un correctivo", "le da un sape a", "pat"),
    "splash": ReactionConfig("💦", "se empapa", "empapa a", "water"),
    "spray": ReactionConfig("🚿", "saca un rociador", "rocía a", "water"),
    "confused": ReactionConfig("❓", "se queda completamente confundido", "deja confundido a", "think"),
    "deredere": ReactionConfig("💖", "se muestra completamente enamorado", "se enamora perdidamente de", "love"),
    "drunk": ReactionConfig("🍻", "actúa como si estuviera totalmente ebrio", "emborracha de forma cómica a", "sigh"),
    "fail": ReactionConfig("💫", "protagoniza un fracaso monumental", "hace que todo salga mal con", "facepalm"),
    "peek": ReactionConfig("👀", "se asoma discretamente", "espía discretamente a", "stare"),
    "psycho": ReactionConfig("🌀", "saca a relucir su locura interna", "muestra su lado psicótico a", "smug"),
    "sing": ReactionConfig("🎤", "se pone a cantar a todo pulmón", "le canta a", "cheer"),
    "teehee": ReactionConfig("🤭", "hace una risita traviesa", "le hace una risita traviesa a", "giggle"),
    "wag": ReactionConfig("🐾", "menea alegremente la colita", "menea alegremente la colita para", "happy"),
    "yandere": ReactionConfig("🔪", "saca su lado obsesivo y peligroso", "muestra su lado yandere ante", "stare"),
    "lewd": ReactionConfig("😈", "piensa en cosas subidas de tono", "acusa de pensamientos subidos de tono a", "smug"),
}

# Ya están registrados por otros cogs y no deben duplicarse.
EXTERNAL_COMMANDS = frozenset({"kill"})


def _create_command(command_name: str):
    async def command(
        self: "ExtraReactions",
        ctx: Any,
        member: discord.Member | None = None,
    ) -> None:
        await self.execute(ctx, command_name, member)

    command.__annotations__.pop("ctx", None)
    hybrid = commands.hybrid_command(
        name=command_name,
        description=f"Ejecuta la reacción anime {command_name}.",
    )(command)
    if hybrid.app_command is not None:
        cast(Any, hybrid.app_command)._params.pop("ctx", None)
    return hybrid


class ExtraReactions(commands.Cog):
    """Reacciones adicionales disponibles por prefix y slash."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def execute(self, ctx: commands.Context[commands.Bot], command_name: str, member: discord.Member | None) -> None:
        config = REACTIONS[command_name]
        if member is not None and member.bot:
            await ctx.send("❌ No se pueden ejecutar estas reacciones sobre bots.", allowed_mentions=discord.AllowedMentions.none())
            return

        if member is None or member.id == ctx.author.id:
            description = f"{ctx.author.mention} {config.verb_self} {config.emoji}"
        else:
            description = f"{ctx.author.mention} {config.verb_other} {member.mention} {config.emoji}"

        embed = discord.Embed(description=description, color=COLOR)
        try:
            asset = await nekos_client.fetch(config.source)
            if asset.url.startswith(("http://", "https://")):
                embed.set_image(url=asset.url)
        except (InvalidCategoryError, NekosBestError, asyncio.TimeoutError) as exc:
            log.warning("No se pudo obtener GIF para '%s': %s", command_name, exc)
            embed.set_footer(text="⚠️ Reacción sin imagen disponible ahora mismo")

        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    for _command_name in REACTIONS:
        if _command_name not in EXTERNAL_COMMANDS:
            locals()[_command_name] = _create_command(_command_name)


async def setup(bot: commands.Bot) -> None:
    """Carga las reacciones adicionales sin duplicar comandos existentes."""
    if bot.get_cog("ExtraReactions") is None:
        cog = ExtraReactions(bot)
        for command in cog.get_commands():
            app_command = getattr(cast(Any, command), "app_command", None)
            if app_command is not None:
                app_command._params.pop("ctx", None)
        await bot.add_cog(cog)
