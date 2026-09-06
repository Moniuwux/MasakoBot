"""Cog de entretenimiento mejorado: comandos divertidos e interactivos.

Incluye: 8ball, coin, roll, choose, joke, meme, cat, dog, weather, anime news/GIFs.
- Sistema mejorado de configuración de anime news con preferencias por usuario
- Botón para cambiar GIF sin duplicar mensajes
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# Ejecución directa (p. ej. `python cogs/entertainment.py`): este archivo es
# un "cog" que el bot carga automáticamente, no un script independiente. Este
# bloque añade la raíz del proyecto a sys.path para que las importaciones
# absolutas (`utils`, `config`, `logger_config`) resuelvan igual que cuando
# el bot arranca con `python main.py`.
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _here = _Path(__file__).resolve().parent
    _sys.path.insert(0, str(_here.parent))
    # Evita que la carpeta del script tape módulos de la stdlib
    # (p. ej. utils/http.py taparía al módulo estándar `http`).
    _sys.path[:] = [p for p in _sys.path if _Path(p).resolve() != _here]
    print("[AVISO] Este archivo es un cog del bot, no un script ejecutable.")
    print("        Arranca el bot con:  python main.py  (desde la raiz del proyecto)")

import asyncio
import hashlib
import logging
import os
import random
import re
from typing import Any, List, Mapping, Optional, cast
from urllib.parse import quote_plus

import discord
from discord.ext import commands
from discord import app_commands

from utils.http import HttpError, http
from config import API_CONFIG
from utils.nekos_api import NekosBestError, client as nekos_client
from utils.entertainment_security import (
    ApiGate,
    CommandGate,
    Guard,
    MAX_SAY_LEN,
    SecurityValidationError,
    rate_limited,
    rate_limited_ctx,
    guard_errors_ctx,
    respond_safely,
)

_APIVERVE_BASE_URL = "https://api.apiverve.com/v1"
_APIVERVE_RPS_API_KEY = os.getenv("APIVERVE_RPS_API_KEY", "")
_APIVERVE_LOVE_API_KEY = os.getenv("APIVERVE_LOVE_API_KEY", "")
RPS_CHOICES = ("rock", "paper", "scissors")
RPS_ALIASES = {
    "piedra": "rock", "r": "rock", "rock": "rock",
    "papel": "paper", "p": "paper", "paper": "paper",
    "tijera": "scissors", "tijeras": "scissors", "t": "scissors", "scissors": "scissors",
}
RPS_EMOJI = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
RPS_LABEL_ES = {"rock": "Piedra", "paper": "Papel", "scissors": "Tijeras"}

logger = logging.getLogger(__name__)


async def _send_local_rps(ctx: commands.Context[commands.Bot], choice: str) -> None:
    bot_choice = random.choice(RPS_CHOICES)
    if choice == bot_choice:
        headline = "🤝 Empate."
    elif (
        (choice == "rock" and bot_choice == "scissors")
        or (choice == "paper" and bot_choice == "rock")
        or (choice == "scissors" and bot_choice == "paper")
    ):
        headline = "🎉 ¡Ganaste!"
    else:
        headline = "😢 Perdiste."
    embed = Guard.safe_embed(title="🪨📄✂️ Piedra, Papel o Tijeras", color=discord.Color.green())
    Guard.safe_add_field(embed, "Tu elección", f"{RPS_EMOJI[choice]} {RPS_LABEL_ES[choice]}", inline=True)
    Guard.safe_add_field(embed, "Elección de Masako", f"{RPS_EMOJI[bot_choice]} {RPS_LABEL_ES[bot_choice]}", inline=True)
    Guard.safe_add_field(embed, "Resultado", headline)
    await ctx.send(embed=embed)


class AnimeGifView(discord.ui.View):
    """Vista interactiva para cambiar GIF de anime sin duplicar."""

    def __init__(self, interaction: discord.Interaction, bot: commands.Bot, current_url: str):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.bot = bot
        self.current_url = current_url
        self.message: Optional[discord.Message] = None
        self._gif_gate = ApiGate(name="nekos-best", max_calls=15, cache_ttl=0, timeout=6)

    async def _get_new_gif(self) -> Optional[str]:
        """Obtiene un nuevo GIF de anime."""
        try:
            asset = await self._gif_gate.call(
                cache_key=None,
                func=lambda: nekos_client.fetch("neko"),
            )
            return Guard.validate_url(asset.url)
        except (NekosBestError, HttpError, asyncio.TimeoutError):
            return None

    @discord.ui.button(label="🔄 Cambiar GIF", style=discord.ButtonStyle.primary)
    async def change_gif(self, interaction: discord.Interaction, _button: discord.ui.Button[Any]) -> None:
        """Cambia el GIF actual por uno nuevo."""
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "❌ Solo quien ejecutó el comando puede cambiar el GIF.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        new_url = await self._get_new_gif()
        if not new_url:
            await interaction.followup.send(
                "❌ No se pudo obtener un nuevo GIF.",
                ephemeral=True
            )
            return

        self.current_url = new_url
        embed = Guard.safe_embed(
            title="🎬 Anime GIF",
            color=discord.Color.pink()
        )
        Guard.safe_set_image(embed, new_url)

        # Editar el mensaje existente sin duplicar
        if self.message:
            await self.message.edit(embed=embed, view=self)


class Entertainment(commands.Cog):
    """Comandos de entretenimiento: 8ball, coin, roll, choose, joke, meme, cat, dog, weather, anime."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._eight_ball = [
            "Sí, definitivamente.",
            "No, de ninguna manera.",
            "Tal vez en otra vida.",
            "Sin duda alguna.",
            "No cuentes con ello.",
            "Pregunta de nuevo más tarde.",
            "Los signos apuntan a que sí.",
            "No lo creo mucho.",
            "Mejor no te lo digo.",
            "Concentra y pregunta de nuevo.",
        ]
        self._gate = CommandGate()
        self._joke_gate = ApiGate(name="jokeapi", cache_ttl=5)
        self._meme_gate = ApiGate(name="meme-api", cache_ttl=3)
        self._cat_gate = ApiGate(name="the-cat-api", cache_ttl=2)
        self._dog_gate = ApiGate(name="dog-ceo", cache_ttl=2)
        self._weather_gate = ApiGate(name="open-meteo", cache_ttl=120)
        self._anilist_gate = ApiGate(name="anilist", max_calls=10, cache_ttl=300)
        self._anilist_unavailable_until = 0.0
        self._gif_gate = ApiGate(name="nekos-best")

    async def cog_unload(self) -> None:
        """Libera el cog; los buckets son memoria efímera y se purgan solos."""
        return None

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Evita exponer errores internos y responde fallos del guard."""
        original = getattr(error, "original", error)
        if isinstance(original, SecurityValidationError):
            await respond_safely(interaction, f"❌ {original}", ephemeral=True)
            return
        if getattr(original, "code", None) in {10062, 10063}:
            logger.warning("La interacción de entretenimiento expiró antes de responder.")
            return
        logger.exception("Error no controlado en entretenimiento", exc_info=original)
        await respond_safely(interaction, "❌ Ocurrió un error inesperado.", ephemeral=True)

    # ========================================================================
    # COMANDOS BÁSICOS (Mejorados)
    # ========================================================================

    @app_commands.command(name="8ball", description="Pregunta a la bola 8 mágica.")
    @app_commands.describe(question="Tu pregunta para la bola mágica")
    @rate_limited("8ball")
    async def eight_ball(
        self, 
        interaction: discord.Interaction,
        question: str
    ) -> None:
        """Consulta la bola 8 mágica."""
        try:
            question = Guard.validate_question(question)
        except SecurityValidationError as exc:
            await respond_safely(interaction, f"❌ {exc}", ephemeral=True)
            return

        embed = Guard.safe_embed(
            title="🎱 Bola 8 Mágica",
            description=f"**Tu pregunta:** {question}",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="Respuesta",
            value=random.choice(self._eight_ball),
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="coin", description="Lanza una moneda.")
    @rate_limited("coin")
    async def coin(self, interaction: discord.Interaction) -> None:
        """Lanza una moneda."""
        result = random.choice(["Cara", "Cruz"])
        emoji = "🪙"
        
        embed = discord.Embed(
            title="Lanzar Moneda",
            description=f"{emoji} **{result}**",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roll", description="Tira dados con modificadores opcionales.")
    @app_commands.describe(dice="Formato: NdM[+/-K] (ej: 2d6, d20+3, 3d100-5)")
    @rate_limited("roll")
    async def roll(
        self, 
        interaction: discord.Interaction,
        dice: str = "1d20"
    ) -> None:
        """Tira dados y aplica un modificador opcional al total."""
        expression = Guard.sanitize_text(dice, max_len=30).lower().replace(" ", "")
        match = re.fullmatch(r"(?:(\d+))?d(\d+)(?:([+-])(\d+))?", expression)
        
        if not match:
            await interaction.response.send_message(
                "❌ Formato inválido. Usa `NdM[+/-K]`, por ejemplo `2d6`, `d20+3` o `3d100-5`.",
                ephemeral=True
            )
            return

        count = int(match.group(1) or 1)
        faces = int(match.group(2))
        modifier_sign = match.group(3)
        modifier = int(match.group(4) or 0)
        if modifier_sign == "-":
            modifier *= -1

        if count < 1 or count > 100 or faces < 2 or faces > 10000:
            await interaction.response.send_message(
                "❌ Límites inválidos: usa entre 1 y 100 dados de 2 a 10000 caras.",
                ephemeral=True
            )
            return
        if abs(modifier) > 100000:
            await interaction.response.send_message(
                "❌ El modificador máximo es de 100000 puntos.",
                ephemeral=True,
            )
            return

        rolls: List[int] = [random.randint(1, faces) for _ in range(count)]
        subtotal = sum(rolls)
        total = subtotal + modifier

        embed = discord.Embed(
            title="🎲 Resultado de Tirada",
            color=discord.Color.green()
        )
        rolls_str = ", ".join(map(str, rolls))
        modifier_text = f" {modifier:+d}" if modifier else ""
        embed.description = f"`{expression}` → **{total}**"
        embed.add_field(name="Resultados", value=f"`{rolls_str}`", inline=False)
        embed.add_field(name="Subtotal", value=f"`{subtotal}`", inline=True)
        embed.add_field(name="Total", value=f"**{total}**", inline=False)
        embed.set_footer(text=f"{count}d{faces}{modifier_text} • Tirado por {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="choose", description="Elige entre opciones separadas por comas.")
    @app_commands.describe(options="Opciones separadas por comas (ej: rojo, azul, verde)")
    @rate_limited("choose")
    async def choose(
        self, 
        interaction: discord.Interaction,
        options: str
    ) -> None:
        """Elige aleatoriamente entre opciones."""
        try:
            parts = Guard.validate_options(options)
        except SecurityValidationError as exc:
            await respond_safely(interaction, f"❌ {exc}", ephemeral=True)
            return
        
        if not parts:
            await interaction.response.send_message(
                "❌ Debes proporcionar al menos una opción.",
                ephemeral=True
            )
            return
        if len(parts) > 25:
            await interaction.response.send_message(
                "❌ Puedes proporcionar como máximo 25 opciones.",
                ephemeral=True,
            )
            return
        if any(len(part) > 100 for part in parts):
            await interaction.response.send_message(
                "❌ Cada opción puede tener como máximo 100 caracteres.",
                ephemeral=True,
            )
            return

        chosen = random.choice(parts)
        
        embed = discord.Embed(
            title="🤔 He Elegido...",
            description=f"**{chosen}**",
            color=discord.Color.purple()
        )
        embed.set_footer(text=f"Entre {len(parts)} opciones")
        
        await interaction.response.send_message(embed=embed)

    # ========================================================================
    # COMANDOS DE JOKES Y MEMES
    # ========================================================================

    @app_commands.command(name="joke", description="Obtén un chiste aleatorio.")
    @app_commands.describe(
        lang="Idioma del chiste: es (español) o en (inglés)"
    )
    @rate_limited("joke")
    async def joke(
        self,
        interaction: discord.Interaction,
        lang: str = "es"
    ) -> None:
        """Obtén un chiste."""
        await interaction.response.defer()
        lang = Guard.sanitize_text(lang, max_len=2).lower()

        if lang not in ["es", "en"]:
            await interaction.followup.send(
                "❌ Idioma no válido. Usa `es` o `en`.",
                ephemeral=True
            )
            return

        try:
            url = f"{API_CONFIG.joke_api_url}/joke/Any?lang={quote_plus(lang)}&format=json"
            raw_data = await self._joke_gate.call(
                cache_key=f"joke:{lang}",
                func=lambda: http.get_json(url),
            )
            if not isinstance(raw_data, Mapping):
                raise HttpError("La API devolvió una respuesta inválida.")
            data = cast(Mapping[str, Any], raw_data)

            if data.get("error"):
                await interaction.followup.send(
                    "❌ No se pudo obtener un chiste.",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="😂 Chiste",
                color=discord.Color.gold()
            )

            if data.get("type") == "single":
                joke_text = str(data.get("joke", "")).strip()
                if not joke_text:
                    raise HttpError("La API no devolvió el texto del chiste.")
                embed.description = joke_text
            else:
                setup = str(data.get("setup", "")).strip()
                delivery = str(data.get("delivery", "")).strip()
                if not setup or not delivery:
                    raise HttpError("La API no devolvió un chiste completo.")
                embed.add_field(
                    name="Setup",
                    value=setup,
                    inline=False
                )
                embed.add_field(
                    name="Punchline",
                    value=delivery,
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except (HttpError, asyncio.TimeoutError):
            await interaction.followup.send(
                "❌ Error conectando con la API de chistes.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error en comando joke: {e}")
            await interaction.followup.send(
                "❌ Error inesperado. Intenta de nuevo.",
                ephemeral=True
            )

    @app_commands.command(name="meme", description="Obtén un meme aleatorio.")
    @app_commands.describe(
        subreddit="Subreddit del que obtener el meme (opcional)"
    )
    @rate_limited("meme")
    async def meme(
        self,
        interaction: discord.Interaction,
        subreddit: str = "memes"
    ) -> None:
        """Obtén un meme desde Reddit vía meme-api."""
        await interaction.response.defer()

        try:
            subreddit = Guard.validate_subreddit(subreddit)
        except SecurityValidationError as exc:
            await respond_safely(interaction, f"❌ {exc}", ephemeral=True)
            return
        try:
            data_raw = await self._meme_gate.call(
                cache_key=f"meme:{subreddit}",
                func=lambda: http.get_json(
                    f"https://meme-api.com/gimme/{quote_plus(subreddit)}"
                ),
            )
            if not isinstance(data_raw, Mapping):
                raise HttpError("La API devolvió una respuesta inválida.")
            data = cast(Mapping[str, Any], data_raw)

            if data.get("nsfw") and not getattr(interaction.channel, "is_nsfw", lambda: False)():
                await interaction.followup.send(
                    "🔞 Ese meme es NSFW y este canal no lo es.",
                    ephemeral=True
                )
                return

            image_url = Guard.validate_url(data.get("url"))
            if not image_url:
                raise HttpError("La API no devolvió una imagen válida.")

            title = str(data.get("title", "Meme")).strip()[:256] or "Meme"
            embed = Guard.safe_embed(
                title=title,
                url=Guard.validate_url(data.get("postLink")),
                color=discord.Color.gold()
            )
            Guard.safe_set_image(embed, image_url)
            embed.set_footer(
                text=Guard.sanitize_external_text(
                    f"r/{data.get('subreddit', subreddit)} • 👍 {data.get('ups', 0)}",
                    max_len=2048,
                )
            )

            await interaction.followup.send(embed=embed)

        except (HttpError, asyncio.TimeoutError):
            await interaction.followup.send(
                "❌ Error al obtener el meme. Inténtalo más tarde.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error en comando meme: {e}")
            await interaction.followup.send(
                "❌ Error inesperado.",
                ephemeral=True
            )

    # ========================================================================
    # COMANDOS DE MASCOTAS
    # ========================================================================

    @app_commands.command(name="cat", description="Obtén una imagen de gato aleatorio.")
    @rate_limited("cat")
    async def cat(self, interaction: discord.Interaction) -> None:
        """Obtén una imagen de gato."""
        await interaction.response.defer()

        try:
            url = f"{API_CONFIG.cat_api_url}/images/search"
            headers: dict[str, str] = {}
            if API_CONFIG.cat_api_key:
                headers["x-api-key"] = API_CONFIG.cat_api_key

            data: Any = await self._cat_gate.call(
                cache_key=None,
                func=lambda: http.get_json(url, headers=headers),
            )
            cat_url = ""

            if isinstance(data, list):
                items = cast(list[Any], data)
                if items:
                    first_item = items[0]
                    if isinstance(first_item, dict):
                        cat_obj = cast(Mapping[str, Any], first_item)
                        cat_url = str(cat_obj.get("url", ""))
            elif isinstance(data, dict):
                cat_obj = cast(Mapping[str, Any], data)
                cat_url = str(cat_obj.get("url", ""))

            if not cat_url:
                await interaction.followup.send("❌ No se pudo obtener la imagen del gato.", ephemeral=True)
                return

            embed = Guard.safe_embed(
                title="🐱 Gato Aleatorio / Random Cat",
                color=discord.Color.orange()
            )
            Guard.safe_set_image(embed, cat_url)

            await interaction.followup.send(embed=embed)

        except (HttpError, asyncio.TimeoutError):
            await interaction.followup.send(
                "❌ Error conectando con la API de gatos.",
                ephemeral=True
            )

    @app_commands.command(name="dog", description="Obtén una imagen de perro aleatorio.")
    @rate_limited("dog")
    async def dog(self, interaction: discord.Interaction) -> None:
        """Obtén una imagen de perro."""
        await interaction.response.defer()

        try:
            url = f"{API_CONFIG.dog_ceo_url}/breeds/image/random"
            data = await self._dog_gate.call(
                cache_key=None,
                func=lambda: http.get_json(url),
            )

            if data.get("status") != "success":
                await interaction.followup.send(
                    "❌ No se pudo obtener imagen.",
                    ephemeral=True
                )
                return

            embed = Guard.safe_embed(
                title="🐕 Perro Aleatorio",
                color=discord.Color.from_rgb(139, 69, 19)
            )
            Guard.safe_set_image(embed, data.get("message"))

            await interaction.followup.send(embed=embed)

        except (HttpError, asyncio.TimeoutError):
            await interaction.followup.send(
                "❌ Error conectando.",
                ephemeral=True
            )

    # ========================================================================
    # COMANDOS DE ANIME GIF
    # ========================================================================

    @app_commands.command(name="anime-gif", description="Obtén un GIF de anime aleatorio con opción de cambiar.")
    @rate_limited("anime-gif")
    async def animegif(self, interaction: discord.Interaction) -> None:
        """Obtén un GIF seguro de anime con botón changeable."""
        await interaction.response.defer()

        try:
            asset = await self._gif_gate.call(
                cache_key=None,
                func=lambda: nekos_client.fetch("neko"),
            )

            gif_url = Guard.validate_url(asset.url)
            if not gif_url:
                await interaction.followup.send(
                    "❌ No se pudo obtener GIF.",
                    ephemeral=True
                )
                return

            embed = Guard.safe_embed(
                title="🎬 Anime GIF",
                color=discord.Color.pink()
            )
            Guard.safe_set_image(embed, gif_url)

            view = AnimeGifView(interaction, self.bot, gif_url)
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message

        except (HttpError, asyncio.TimeoutError):
            await interaction.followup.send(
                "❌ Error al conectar.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error en comando animegif: {e}")
            await interaction.followup.send(
                "❌ Error inesperado.",
                ephemeral=True
            )

    @commands.hybrid_command(name="say", description="Repite un mensaje de forma segura.")
    @app_commands.describe(message="Mensaje a repetir")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(send_messages=True)
    @rate_limited_ctx("say")
    @guard_errors_ctx
    async def say(self, ctx: commands.Context[commands.Bot], *, message: str) -> None:
        clean_message = Guard.sanitize_say_text(message, max_len=MAX_SAY_LEN)
        await ctx.send(
            clean_message,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )

    @commands.hybrid_command(name="rps", description="Juega Piedra, Papel o Tijeras.")
    @app_commands.describe(choice="Piedra, papel o tijeras")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="Piedra 🪨", value="piedra"),
            app_commands.Choice(name="Papel 📄", value="papel"),
            app_commands.Choice(name="Tijeras ✂️", value="tijeras"),
        ]
    )
    @commands.guild_only()
    @rate_limited_ctx("rps")
    @guard_errors_ctx
    async def rps(self, ctx: commands.Context[commands.Bot], *, choice: str = "") -> None:
        normalized = RPS_ALIASES.get(Guard.sanitize_text(choice, max_len=20).lower())
        if normalized not in RPS_CHOICES:
            await ctx.send("❌ Elige `piedra`, `papel` o `tijeras`.")
            return

        await _send_local_rps(ctx, normalized)

    @commands.hybrid_command(name="ship", description="Calcula la compatibilidad entre dos usuarios.")
    @app_commands.describe(member_a="Primer usuario", member_b="Segundo usuario (opcional, por defecto tú)")
    @commands.guild_only()
    @rate_limited_ctx("ship")
    @guard_errors_ctx
    async def ship(self, ctx: commands.Context[commands.Bot], member_a: discord.Member, member_b: Optional[discord.Member] = None) -> None:
        other_member = member_b or member_a
        first_member = cast(discord.Member, ctx.author) if member_b is None else member_a
        if first_member.id == other_member.id:
            await ctx.send("❌ Elige a dos usuarios diferentes.")
            return
        name_a = Guard.sanitize_text(first_member.display_name, max_len=32)
        name_b = Guard.sanitize_text(other_member.display_name, max_len=32)

        pair_hash = int(hashlib.md5(f"{min(first_member.id, other_member.id)}-{max(first_member.id, other_member.id)}".encode()).hexdigest(), 16)
        percentage = pair_hash % 101
        filled = percentage // 10
        bar = "❤️" * filled + "🖤" * (10 - filled)
        if percentage >= 85:
            level, color = "Almas gemelas", discord.Color.red()
        elif percentage >= 65:
            level, color = "Gran conexión", discord.Color.pink()
        elif percentage >= 40:
            level, color = "Química por descubrir", discord.Color.orange()
        else:
            level, color = "Amistad recomendable", discord.Color.blurple()
        embed = Guard.safe_embed(
            title="💘 Compatibilidad",
            description=f"**{name_a}**  💞  **{name_b}**",
            color=color,
        )
        embed.set_thumbnail(url=first_member.display_avatar.url)
        embed.set_image(url=other_member.display_avatar.url)
        Guard.safe_add_field(embed, "Puntuación", f"{bar}\n**{percentage}%**", inline=False)
        Guard.safe_add_field(embed, "Lectura", level, inline=True)
        Guard.safe_add_field(embed, "Método", "Cálculo recreativo", inline=True)
        embed.set_footer(text="El resultado es recreativo y determinista")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    """Carga el Cog en el bot."""
    await bot.add_cog(Entertainment(bot))
