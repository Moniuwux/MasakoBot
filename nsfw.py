"""Cog de interacciones NSFW mediante comandos con prefijo."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.http import HttpError
from utils.nsfw_sources import NsfwSourceError, client as nsfw_client

log = logging.getLogger(__name__)
COLOR = discord.Color.dark_purple()


@dataclass(slots=True, frozen=True)
class InteractionConfig:
    emoji: str
    verb_self: str
    verb_other: str | None = None
    requires_target: bool = False


COMMANDS_CONFIG: dict[str, InteractionConfig] = {
    "boobs": InteractionConfig("🍈", "admira sus pechos", "toca los pechos de"),
    "cum": InteractionConfig("💦", "se corre fuerte", "se corre en"),
    "fap": InteractionConfig("🦾", "se masturba", "se masturba para"),
    "footjob": InteractionConfig("👣", "disfruta una mamada con pies", "hace una mamada con pies a"),
    "gelbooru": InteractionConfig("🎨", "navega en gelbooru", "comparte gelbooru con"),
    "grabboobs": InteractionConfig("👋", "se agarra los pechos", "agarra los pechos de"),
    "grabbutts": InteractionConfig("👋", "se agarra las nalgas", "agarra las nalgas de"),
    "handjob": InteractionConfig("👉", "se hace una manola", "le hace una manola a"),
    "hentai": InteractionConfig("🎭", "ve hentai", "comparte hentai con"),
    "hentaigif": InteractionConfig("🎭", "ve un GIF de hentai", "comparte un GIF de hentai con"),
    "konachan": InteractionConfig("🎨", "navega en konachan", "comparte konachan con"),
    "lewdere": InteractionConfig("😈", "tiene una erección sucio", "hace una erección sucio con"),
    "lewdkitsune": InteractionConfig("🦊", "actúa como un kitsune sucio", "hace cosas de kitsune sucio con"),
    "lewdneko": InteractionConfig("🐱", "actúa como un neko sucio", "hace cosas de neko sucio con"),
    "pussy": InteractionConfig("🐱", "juega con su vagina", "toca la vagina de"),
    "suck": InteractionConfig("👅", "se chupa", "chupa a"),
    "yuri": InteractionConfig("💜", "disfruta de yuri", "hace yuri con"),
    "anal": InteractionConfig("🍑", "", "hace anal a", True),
    "bfuck": InteractionConfig("💦", "", "folla fuerte a", True),
    "boobjob": InteractionConfig("🍈", "", "hace una mamada con pechos a", True),
    "fuck": InteractionConfig("💦", "", "folla a", True),
    "futafuck": InteractionConfig("💦", "", "folla a una futa a", True),
    "happyend": InteractionConfig("🎆", "", "le da un final feliz a", True),
    "kuni": InteractionConfig("👅", "", "hace kuni a", True),
    "oralfuck": InteractionConfig("👅", "", "folla la boca de", True),
    "pussyfuck": InteractionConfig("💦", "", "folla la vagina de", True),
    "randomfuck": InteractionConfig("🎲", "", "folla aleatoriamente a", True),
    "rape": InteractionConfig("⚠️", "", "viola a", True),
    "riding": InteractionConfig("🐴", "", "monta a", True),
    "suckboobs": InteractionConfig("👅", "", "chupa los pechos de", True),
    "suckpussy": InteractionConfig("👅", "", "chupa la vagina de", True),
    "tentacle": InteractionConfig("🐙", "", "es penetrado por tentáculos de", True),
    "titten": InteractionConfig("🍈", "", "toca los pechos de", True),
    "throatfuck": InteractionConfig("🤐", "", "folla la garganta de", True),
}


def _create_command(command_name: str):
    async def command(self: "NSFWInteractions", ctx: commands.Context[commands.Bot], target: Optional[discord.Member] = None) -> None:
        await self.execute(ctx, command_name, target)
    return commands.command(name=command_name)(command)


class NSFWInteractions(commands.Cog):
    """Cog NSFW con un único punto de registro y comandos prefix."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def execute(self, ctx: commands.Context[commands.Bot], command_name: str, target: Optional[discord.Member] = None) -> None:
        if not getattr(ctx.channel, "is_nsfw", lambda: False)():
            await ctx.send("🔞 Este comando solo se puede usar en canales marcados como NSFW (+18).", delete_after=10)
            return

        config = COMMANDS_CONFIG[command_name]
        if config.requires_target and target is None:
            await ctx.send(f"❌ `{command_name}` requiere mencionar a un usuario.", delete_after=5)
            return
        if target is not None and target.bot:
            embed = discord.Embed(description=f"❌ {ctx.author.mention} no puede hacer eso con un bot. 🚫", color=COLOR)
            await ctx.send(embed=embed)
            return
        if target is None or target == ctx.author:
            description = f"{config.emoji} {ctx.author.mention} {config.verb_self}"
        else:
            description = f"{config.emoji} {ctx.author.mention} {config.verb_other or config.verb_self} {target.mention}"
        embed = discord.Embed(description=description, color=COLOR)
        try:
            asset = await nsfw_client.fetch(command_name)
            if asset.url.startswith(("http://", "https://")):
                embed.set_image(url=asset.url)
        except (NsfwSourceError, HttpError, asyncio.TimeoutError) as exc:
            log.warning("Sin imagen para '%s': %s", command_name, exc)
            embed.set_footer(text="⚠️ Sin imagen disponible ahora mismo 😿")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="nsfw", description="Ejecuta una interacción o imagen NSFW en un canal +18.")
    @app_commands.describe(
        accion="La acción o categoría NSFW a ejecutar",
        target="Usuario objetivo (opcional o requerido según la acción)"
    )
    async def nsfw_slash(
        self,
        interaction: discord.Interaction,
        accion: str,
        target: Optional[discord.Member] = None,
    ) -> None:
        """Comando slash único e intuitivo con autocompletado para NSFW."""
        if not getattr(interaction.channel, "is_nsfw", lambda: False)():
            await interaction.response.send_message(
                "🔞 Este comando solo se puede usar en canales marcados como NSFW (+18).",
                ephemeral=True,
            )
            return

        clean_action = accion.strip().lower()
        if clean_action not in COMMANDS_CONFIG:
            await interaction.response.send_message(
                f"❌ Acción NSFW no válida. Escribe `/nsfw` y elige una de las opciones sugeridas.",
                ephemeral=True,
            )
            return

        config = COMMANDS_CONFIG[clean_action]
        if config.requires_target and target is None:
            await interaction.response.send_message(
                f"❌ La acción `{clean_action}` requiere especificar un usuario objetivo.",
                ephemeral=True,
            )
            return

        if target is not None and target.bot:
            await interaction.response.send_message(
                "❌ No se pueden realizar acciones NSFW sobre bots.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        if target is None or target.id == interaction.user.id:
            desc = f"{config.emoji} {interaction.user.mention} {config.verb_self}"
        else:
            desc = f"{config.emoji} {interaction.user.mention} {config.verb_other or config.verb_self} {target.mention}"

        embed = discord.Embed(description=desc, color=COLOR)
        try:
            asset = await nsfw_client.fetch(clean_action)
            if asset.url.startswith(("http://", "https://")):
                embed.set_image(url=asset.url)
        except (NsfwSourceError, HttpError, asyncio.TimeoutError) as exc:
            log.warning("Sin imagen para '%s': %s", clean_action, exc)
            embed.set_footer(text="⚠️ Sin imagen disponible ahora mismo 😿")

        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @nsfw_slash.autocomplete("accion")
    async def nsfw_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.strip().lower()
        choices = [
            app_commands.Choice(name=f"{COMMANDS_CONFIG[name].emoji} {name}", value=name)
            for name in COMMANDS_CONFIG
            if current_lower in name.lower()
        ]
        return choices[:25]

    for _command_name in COMMANDS_CONFIG:
        locals()[_command_name] = _create_command(_command_name)

async def setup(bot: commands.Bot) -> None:
    """Registra el cog NSFW exactamente una vez."""
    if bot.get_cog("NSFWInteractions") is None:
        await bot.add_cog(NSFWInteractions(bot))

