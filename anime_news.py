"""Cog mejorado para noticias de anime con configuración interactiva y publicación automática."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Mapping, Optional, cast
from dataclasses import dataclass, asdict

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import API_CONFIG
from utils.http import HttpError, http
from utils.turso_database import turso_db


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class AnimeNewsConfig:
    """Configuración de noticias de anime por servidor."""
    guild_id: int
    channel_id: Optional[int] = None
    role_id: Optional[int] = None
    content_types: Optional[set[str]] = None
    adult_filter: str = "blocked"  # "blocked" o "allowed"
    embed_color: int = 9698099  # Color púrpura por defecto
    updated_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.content_types is None:
            self.content_types = {"trending"}


# ============================================================================
# ANILIST CLIENT
# ============================================================================

class AniListClient:
    """Cliente especializado para AniList GraphQL."""

    CONTENT_TYPE_QUERIES = {
        "nuevos": {
            "sort": "START_DATE_DESC",
            "status": "RELEASING",
            "emoji": "🆕",
            "label": "Nuevos animes",
        },
        "episodios": {
            "sort": "START_DATE_DESC",
            "status": "RELEASING",
            "emoji": "📺",
            "label": "Nuevos episodios",
        },
        "trending": {
            "sort": "TRENDING_DESC",
            "status": None,
            "emoji": "🔥",
            "label": "Animes en tendencia",
        },
        "popular": {
            "sort": "POPULARITY_DESC",
            "status": None,
            "emoji": "⭐",
            "label": "Animes populares",
        },
        "proximos": {
            "sort": "START_DATE_DESC",
            "status": "NOT_YET_RELEASED",
            "emoji": "📅",
            "label": "Próximos estrenos",
        },
        "valorados": {
            "sort": "SCORE_DESC",
            "status": None,
            "emoji": "🏆",
            "label": "Mejor valorados",
        },
        "peliculas": {
            "sort": "SCORE_DESC",
            "format": "MOVIE",
            "emoji": "🎬",
            "label": "Películas",
        },
    }

    @staticmethod
    async def fetch_news(
        content_type: str,
        limit: int = 5,
        exclude_adult: bool = True,
    ) -> Optional[list[dict[str, Any]]]:
        """Obtiene noticias de anime desde AniList."""
        try:
            query_config = AniListClient.CONTENT_TYPE_QUERIES.get(content_type)
            if not query_config:
                return None

            sort = query_config.get("sort", "TRENDING_DESC")
            type_filter = query_config.get("type", "ANIME")
            format_filter = query_config.get("format")
            status = query_config.get("status")

            # Construir filtros
            status_filter = f", status: {status}" if status else ""
            format_filter_clause = f", format: {format_filter}" if format_filter else ""
            adult_filter = ", isAdult: false" if exclude_adult else ""

            query = f"""
            query {{
                Page(page: 1, perPage: {limit}) {{
                    media(
                        type: {type_filter},
                        sort: {sort}{status_filter}{format_filter_clause}{adult_filter}
                    ) {{
                        id
                        title {{
                            english
                            romaji
                        }}
                        type
                        episodes
                        status
                        averageScore
                        genres
                        description
                        siteUrl
                        coverImage {{
                            large
                        }}
                        startDate {{
                            year
                            month
                            day
                        }}
                        isAdult
                    }}
                }}
            }}
            """

            response = await http.post_json(
                API_CONFIG.anilist_graphql_url,
                json={"query": query}
            )

            media = response.get("data", {}).get("Page", {}).get("media", [])
            return media if media else None

        except (HttpError, asyncio.TimeoutError, KeyError):
            return None

    @staticmethod
    def clean_description(html_text: Optional[str]) -> str:
        """Limpia HTML de la descripción."""
        if not html_text:
            return "Sin descripción disponible."
        
        # Remover etiquetas HTML
        clean = re.sub(r"<[^>]+>", "", html_text)
        # Limitar longitud
        if len(clean) > 200:
            clean = clean[:200] + "..."
        return clean.strip()

    @staticmethod
    def format_date(date_obj: Optional[Mapping[str, Any]]) -> str:
        """Formatea fecha de AniList."""
        if not date_obj:
            return "Desconocida"

        year = date_obj.get("year")
        month = date_obj.get("month")
        day = date_obj.get("day")

        if year is None:
            return "Desconocida"

        if month is not None and day is not None:
            return f"{day}/{month}/{year}"
        if month is not None:
            return f"{month}/{year}"
        return str(year)


# ============================================================================
# ANIME EMBED BUILDER
# ============================================================================

class AnimeEmbedBuilder:
    """Constructor de embeds para noticias de anime."""

    @staticmethod
    def build_anime_embed(
        anime: dict[str, Any],
        content_type: str,
        config: AnimeNewsConfig,
    ) -> discord.Embed:
        """Construye un embed para un anime."""
        title_map = cast(dict[str, Any], anime.get("title", {}))
        cover_map = cast(dict[str, Any], anime.get("coverImage", {}))
        type_config = cast(dict[str, Any], AniListClient.CONTENT_TYPE_QUERIES.get(content_type, {}))
        emoji = type_config.get("emoji", "📰")

        title = title_map.get("english") or title_map.get("romaji", "Anime")

        embed = discord.Embed(
            title=f"{emoji} {title}",
            url=anime.get("siteUrl"),
            color=config.embed_color,
            timestamp=datetime.now(),
        )

        description = AniListClient.clean_description(cast(Optional[str], anime.get("description")))
        embed.description = description

        if cover_map.get("large"):
            embed.set_thumbnail(url=str(cover_map["large"]))

        anime_type = str(anime.get("type", "?"))
        episodes = anime.get("episodes")
        status = str(anime.get("status", "?"))
        score = anime.get("averageScore")
        genres_raw = anime.get("genres", [])
        genre_items: list[str] = []
        if isinstance(genres_raw, list):
            genre_values = cast(list[Any], genres_raw)
            genre_items = [str(genre) for genre in genre_values if isinstance(genre, (str, int, float))]

        info_str = f"**Tipo:** {anime_type}"
        if episodes:
            info_str += f"\n**Episodios:** {episodes}"
        info_str += f"\n**Estado:** {status}"
        if score:
            info_str += f"\n**Puntuación:** {score}/100"
        if genre_items:
            info_str += f"\n**Géneros:** {', '.join(genre_items[:5])}"

        embed.add_field(name="📊 Información", value=info_str, inline=False)

        start_date = AniListClient.format_date(cast(Optional[Mapping[str, Any]], anime.get("startDate")))
        embed.add_field(name="📅 Inicio", value=start_date, inline=True)

        embed.set_footer(text="📡 Datos de AniList")

        return embed


# ============================================================================
# CONFIGURATION VIEWS
# ============================================================================

class ContentTypeSelectView(discord.ui.View):
    """Select menu para seleccionar tipos de contenido."""

    def __init__(self, current: set[str]):
        super().__init__()
        self.selected: set[str] = set(current)

    @discord.ui.select(
        placeholder="Selecciona qué noticias deseas recibir",
        min_values=1,
        max_values=7,
        options=[
            discord.SelectOption(label="🆕 Nuevos animes", value="nuevos"),
            discord.SelectOption(label="📺 Nuevos episodios", value="episodios"),
            discord.SelectOption(label="🔥 Animes en tendencia", value="trending"),
            discord.SelectOption(label="⭐ Animes populares", value="popular"),
            discord.SelectOption(label="📅 Próximos estrenos", value="proximos"),
            discord.SelectOption(label="🏆 Mejor valorados", value="valorados"),
            discord.SelectOption(label="🎬 Películas", value="peliculas"),
        ],
    )
    async def select_types(self, interaction: discord.Interaction, select: discord.ui.Select[Any]) -> None:
        self.selected = set(select.values)
        await interaction.response.defer()
        self.stop()


class AdultFilterView(discord.ui.View):
    """Botones para seleccionar filtro de contenido adulto."""
    
    def __init__(self):
        super().__init__()
        self.selected = "blocked"

    @discord.ui.button(label="🔒 Bloqueado", style=discord.ButtonStyle.danger)
    async def block_adult(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        self.selected = "blocked"
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="⚠️ Permitir", style=discord.ButtonStyle.secondary)
    async def allow_adult(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        self.selected = "allowed"
        await interaction.response.defer()
        self.stop()


class AnimeNewsConfigView(discord.ui.View):
    """Vista interactiva principal de configuración de noticias."""
    
    def __init__(self, bot: commands.Bot, guild_id: int, config: AnimeNewsConfig):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id
        self.config = config
        self.working_config = AnimeNewsConfig(**asdict(config))

    async def update_embed(self, interaction: discord.Interaction) -> None:
        """Actualiza el embed principal con la configuración actual."""
        embed = discord.Embed(
            title="📰 Configuración de Anime News",
            description=(
                "Personaliza a tu gusto las noticias que quieres recibir en este servidor. "
                "Selecciona los tipos de contenido que deseas recibir, configura el canal de destino "
                "y elige si quieres recibir una notificación mediante un rol."
            ),
            color=discord.Color.purple(),
        )

        # API
        embed.add_field(name="📡 API", value="AniList GraphQL", inline=False)

        # Noticias seleccionadas
        if self.working_config.content_types:
            content_labels: list[str] = []
            type_map: dict[str, str] = {
                "nuevos": "🆕 Nuevos animes",
                "episodios": "📺 Nuevos episodios",
                "trending": "🔥 Tendencias",
                "popular": "⭐ Populares",
                "proximos": "📅 Próximos estrenos",
                "valorados": "🏆 Mejor valorados",
                "peliculas": "🎬 Películas",
            }
            for content_type in sorted(self.working_config.content_types):
                content_labels.append(type_map.get(content_type, content_type))

            news_display = "\n".join(content_labels)
        else:
            news_display = "Ninguna"

        embed.add_field(name="📰 Noticias seleccionadas", value=news_display, inline=False)

        # Canal
        channel_display = f"<#{self.working_config.channel_id}>" if self.working_config.channel_id else "No configurado"
        embed.add_field(name="📺 Canal", value=channel_display, inline=False)

        # Filtro adulto
        adult_status = "🔒 Bloqueado" if self.working_config.adult_filter == "blocked" else "⚠️ Permitido"
        embed.add_field(name="🔞 Contenido adulto", value=adult_status, inline=False)

        # Rol de notificación
        role_display = f"<@&{self.working_config.role_id}>" if self.working_config.role_id else "Ninguno"
        embed.add_field(name="🔔 Rol de notificación", value=role_display, inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📰 Tipos de noticias", style=discord.ButtonStyle.primary, emoji="📰")
    async def button_content_types(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        view = ContentTypeSelectView(self.working_config.content_types or {"trending"})
        embed = discord.Embed(
            title="📰 Selecciona tipos de noticias",
            description="Elige qué tipos de contenido de anime deseas recibir.",
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        try:
            await asyncio.wait_for(view.wait(), timeout=60)
            self.working_config.content_types = view.selected
            await self.update_embed(interaction)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="📺 Canal", style=discord.ButtonStyle.primary, emoji="📺")
    async def button_channel(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        class ChannelSelect(discord.ui.View):
            def __init__(self):
                super().__init__()
                self.selected_channel = None

            @discord.ui.button(label="Usar canal actual", style=discord.ButtonStyle.secondary)
            async def use_current(self, i: discord.Interaction, b: discord.ui.Button[Any]) -> None:
                self.selected_channel = i.channel_id
                self.stop()
                await i.response.defer()

        view = ChannelSelect()
        await interaction.response.send_message(
            "¿Qué canal quieres usar para recibir las noticias de anime?",
            view=view,
            ephemeral=True,
        )
        
        try:
            await asyncio.wait_for(view.wait(), timeout=60)
            if view.selected_channel:
                self.working_config.channel_id = view.selected_channel
                await self.update_embed(interaction)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="🔞 Contenido adulto", style=discord.ButtonStyle.primary, emoji="🔞")
    async def button_adult_filter(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        view = AdultFilterView()
        embed = discord.Embed(
            title="🔞 Filtro de contenido adulto",
            description="¿Deseas permitir contenido clasificado como adulto (+18)?",
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        try:
            await asyncio.wait_for(view.wait(), timeout=60)
            self.working_config.adult_filter = view.selected
            await self.update_embed(interaction)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="🔔 Rol", style=discord.ButtonStyle.primary, emoji="🔔")
    async def button_role(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        class RoleSelect(discord.ui.View):
            def __init__(self):
                super().__init__()
                self.selected_role = None

            @discord.ui.button(label="Ninguno", style=discord.ButtonStyle.secondary)
            async def no_role(self, i: discord.Interaction, b: discord.ui.Button[Any]) -> None:
                self.selected_role = None
                self.stop()
                await i.response.defer()

        view = RoleSelect()
        await interaction.response.send_message(
            "Selecciona un rol para las notificaciones (o elige Ninguno).",
            view=view,
            ephemeral=True,
        )
        
        try:
            await asyncio.wait_for(view.wait(), timeout=60)
            self.working_config.role_id = view.selected_role
            await self.update_embed(interaction)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="👁️ Vista previa", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def button_preview(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await interaction.response.defer(ephemeral=True)
        
        if not self.working_config.content_types:
            await interaction.followup.send("❌ Selecciona primero tipos de noticias.", ephemeral=True)
            return

        content_type = list(self.working_config.content_types)[0]
        exclude_adult = self.working_config.adult_filter == "blocked"
        
        media = await AniListClient.fetch_news(content_type, limit=1, exclude_adult=exclude_adult)
        
        if not media:
            await interaction.followup.send("❌ No se pudo obtener vista previa.", ephemeral=True)
            return

        embed = AnimeEmbedBuilder.build_anime_embed(media[0], content_type, self.working_config)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="💾 Guardar", style=discord.ButtonStyle.success, emoji="💾")
    async def button_save(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        if not self.working_config.channel_id:
            await interaction.response.send_message(
                "❌ Debe configurar un canal primero.",
                ephemeral=True,
            )
            return

        if not self.working_config.content_types:
            await interaction.response.send_message(
                "❌ Debe seleccionar al menos un tipo de noticia.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        
        # Guardar en base de datos
        await turso_db.setup()
        content_types_json = json.dumps(list(self.working_config.content_types))
        
        await turso_db.execute(
            """
            INSERT INTO anime_news_config 
            (guild_id, channel_id, role_id, content_types, adult_filter, embed_color, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                role_id = excluded.role_id,
                content_types = excluded.content_types,
                adult_filter = excluded.adult_filter,
                embed_color = excluded.embed_color,
                updated_at = excluded.updated_at
            """,
            (
                self.guild_id,
                self.working_config.channel_id,
                self.working_config.role_id,
                content_types_json,
                self.working_config.adult_filter,
                self.working_config.embed_color,
                datetime.now().isoformat(),
            ),
        )

        await interaction.followup.send(
            "✅ Configuración guardada. El sistema comenzará a enviar noticias de anime automáticamente.",
            ephemeral=True,
        )
        self.stop()


# ============================================================================
# MAIN COG
# ============================================================================

class AnimeNews(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.published_anime: dict[int, set[int]] = {}  # guild_id -> set de anime_ids publicados
        self.anime_publish_loop.start()

    @tasks.loop(hours=4)
    async def anime_publish_loop(self) -> None:
        """Tarea automática que publica noticias de anime."""
        try:
            await turso_db.setup()
            rows = await turso_db.fetch_all("SELECT * FROM anime_news_config")

            for row in rows:
                guild_id = int(row[0])
                channel_id = row[1]
                role_id = row[2]

                if not channel_id:
                    continue

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                channel = guild.get_channel(int(channel_id))
                if not isinstance(channel, discord.abc.Messageable):
                    continue

                if not channel.permissions_for(guild.me).send_messages:
                    continue

                config = await self._load_config(guild_id)
                if not config or not config.content_types:
                    continue

                published_ids: set[int] = set(self.published_anime.get(guild_id, set()))
                exclude_adult = config.adult_filter == "blocked"

                for content_type in config.content_types:
                    media = await AniListClient.fetch_news(content_type, limit=5, exclude_adult=exclude_adult)

                    if not media:
                        continue

                    for anime in media:
                        anime_id = anime.get("id")
                        if anime_id is None:
                            continue
                        if int(anime_id) in published_ids:
                            continue

                        published_ids.add(int(anime_id))
                        embed = AnimeEmbedBuilder.build_anime_embed(anime, content_type, config)

                        content = ""
                        if role_id:
                            role = guild.get_role(int(role_id))
                            if role and (channel.permissions_for(guild.me).mention_everyone or role.mentionable):
                                content = f"<@&{role_id}>"

                        try:
                            await channel.send(content=content or None, embed=embed)
                            await asyncio.sleep(1)
                        except discord.Forbidden:
                            pass

                self.published_anime[guild_id] = published_ids

        except Exception as e:
            print(f"Error en anime_publish_loop: {e}")

    @anime_publish_loop.before_loop
    async def before_anime_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _load_config(self, guild_id: int) -> Optional[AnimeNewsConfig]:
        """Carga configuración de la base de datos."""
        await turso_db.setup()
        rows = await turso_db.fetch_all(
            "SELECT * FROM anime_news_config WHERE guild_id = ?",
            (guild_id,),
        )

        if not rows:
            return None

        row = rows[0]
        content_types_raw = row[3]
        parsed_types: set[str] = set()
        if content_types_raw:
            parsed_types = {str(item) for item in json.loads(content_types_raw)}

        return AnimeNewsConfig(
            guild_id=int(row[0]),
            channel_id=int(row[1]) if row[1] is not None else None,
            role_id=int(row[2]) if row[2] is not None else None,
            content_types=parsed_types or {"trending"},
            adult_filter=str(row[4]) if row[4] else "blocked",
            embed_color=int(row[5]) if row[5] is not None else 9698099,
            updated_at=row[6] if len(row) > 6 and row[6] is not None else None,
        )

    @app_commands.command(name="anime-news", description="Muestra noticias de anime en tendencia, popular o en emisión.")
    @app_commands.describe(tipo="trending, popular o news")
    @app_commands.choices(
        tipo=[
            app_commands.Choice(name="Tendencias", value="trending"),
            app_commands.Choice(name="Populares", value="popular"),
            app_commands.Choice(name="En emisión", value="nuevos"),
        ]
    )
    async def anime_news_manual(self, interaction: discord.Interaction, tipo: app_commands.Choice[str] | None = None) -> None:
        """Comando manual de noticias de anime (CONSERVADO)."""
        await interaction.response.defer()

        selected_type = tipo.value if tipo is not None else "trending"
        media = await AniListClient.fetch_news(selected_type, limit=5, exclude_adult=True)

        if not media:
            await interaction.followup.send("❌ No se pudo consultar AniList.", ephemeral=True)
            return

        guild_id = interaction.guild_id if interaction.guild_id is not None else 0
        config = AnimeNewsConfig(guild_id=guild_id)

        for anime in media:
            embed = AnimeEmbedBuilder.build_anime_embed(anime, selected_type, config)
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="anime-config", description="Configura el sistema automático de noticias de anime.")
    @app_commands.default_permissions(administrator=True)
    async def anime_configure(self, interaction: discord.Interaction) -> None:
        """Abre el panel de configuración de noticias."""
        if not interaction.guild:
            await interaction.response.send_message("❌ Este comando requiere un servidor.", ephemeral=True)
            return

        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("❌ No se pudo determinar el servidor.", ephemeral=True)
            return

        await interaction.response.defer()

        config = await self._load_config(guild_id)
        if not config:
            config = AnimeNewsConfig(guild_id=guild_id)

        view = AnimeNewsConfigView(self.bot, guild_id, config)

        embed = discord.Embed(
            title="📰 Configuración de Anime News",
            description=(
                "Personaliza a tu gusto las noticias que quieres recibir en este servidor. "
                "Selecciona los tipos de contenido que deseas recibir, configura el canal de destino "
                "y elige si quieres recibir una notificación mediante un rol."
            ),
            color=discord.Color.purple(),
        )

        embed.add_field(name="📡 API", value="AniList GraphQL", inline=False)
        embed.add_field(name="📰 Noticias", value="No configuradas", inline=False)
        embed.add_field(name="📺 Canal", value="No configurado", inline=False)

        await interaction.followup.send(embed=embed, view=view)

    async def cog_unload(self) -> None:
        """Limpia recursos al descargar el cog."""
        self.anime_publish_loop.cancel()


async def setup(bot: commands.Bot) -> None:
    """Instala el cog."""
    await turso_db.setup()
    await turso_db.execute(
        """
        CREATE TABLE IF NOT EXISTS anime_news_config (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            role_id INTEGER,
            content_types TEXT DEFAULT '["trending"]',
            adult_filter TEXT DEFAULT 'blocked',
            embed_color INTEGER DEFAULT 9698099,
            updated_at TEXT
        )
        """
    )
    await bot.add_cog(AnimeNews(bot))