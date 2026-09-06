"""Cog de meteorología automática con Open-Meteo y configuración por servidor.

Sistema reescrito desde cero conservando las mismas características, comandos
y propósitos de la versión anterior (pero con el encoding correcto):

    • /weather        — consulta manual por latitud/longitud.
    • /weather-config — panel interactivo: ubicación, información mostrada,
                        pronóstico horario/diario, canal destino, rol de
                        notificación y vista previa.
    • Publicación automática cada 30 minutos con caché de 30 minutos.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Set, cast
from urllib.parse import quote_plus

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import API_CONFIG
from logger_config import setup_logger
from utils.http import HttpError, http
from utils.turso_database import turso_db

logger = setup_logger("Weather", level=logging.INFO)

DEFAULT_EMBED_COLOR = 3447003
DEFAULT_EMBED_TITLE = "🌤️ Clima"
WeatherData = dict[str, Any]
WeatherLocationData = Mapping[str, Any]


# ============================================================================
# MODELOS DE DATOS
# ============================================================================

@dataclass
class WeatherLocation:
    """Ubicación geocodificada desde Open-Meteo."""

    name: str
    latitude: float
    longitude: float
    country: str
    timezone: str
    admin1: Optional[str] = None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "WeatherLocation":
        """Construye la ubicación desde una respuesta de la API."""
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        return cls(
            name=str(data.get("name", "Unknown")),
            latitude=float(latitude) if latitude is not None else 0.0,
            longitude=float(longitude) if longitude is not None else 0.0,
            country=str(data.get("country", "Unknown")),
            timezone=str(data.get("timezone", "UTC")),
            admin1=data.get("admin1") if isinstance(data.get("admin1"), str) else None,
        )


@dataclass
class WeatherConfig:
    """Configuración de meteorología por servidor."""

    guild_id: int
    channel_id: Optional[int] = None
    role_id: Optional[int] = None
    location_name: str = "Not Set"
    latitude: float = 0.0
    longitude: float = 0.0
    timezone: str = "UTC"
    country: str = ""
    selected_info: Set[str] = field(
        default_factory=lambda: {"temperatura", "humedad", "viento", "precipitacion"}
    )
    forecast_types: Set[str] = field(default_factory=lambda: {"actual"})
    embed_color: int = DEFAULT_EMBED_COLOR
    embed_title: str = DEFAULT_EMBED_TITLE
    last_published_data: Optional[str] = None
    updated_at: Optional[str] = None


# ============================================================================
# CLIENTE OPEN-METEO
# ============================================================================

class OpenMeteoClient:
    """Cliente especializado para Open-Meteo."""

    WEATHER_CODES: Dict[int, tuple[str, str]] = {
        0: ("☀️", "Despejado"),
        1: ("🌤️", "Mayormente despejado"),
        2: ("🌤️", "Parcialmente nublado"),
        3: ("☁️", "Nublado"),
        45: ("🌫️", "Brumoso"),
        48: ("🌫️", "Bruma helada"),
        51: ("🌧️", "Llovizna ligera"),
        53: ("🌧️", "Llovizna moderada"),
        55: ("🌧️", "Llovizna densa"),
        61: ("🌧️", "Lluvia ligera"),
        63: ("🌧️", "Lluvia moderada"),
        65: ("🌧️", "Lluvia fuerte"),
        71: ("❄️", "Nieve ligera"),
        73: ("❄️", "Nieve moderada"),
        75: ("❄️", "Nieve fuerte"),
        77: ("❄️", "Nieve granulada"),
        80: ("🌧️", "Chubascos ligeros"),
        81: ("🌧️", "Chubascos moderados"),
        82: ("🌧️", "Chubascos violentos"),
        85: ("❄️", "Chubascos de nieve ligeros"),
        86: ("❄️", "Chubascos de nieve fuertes"),
        95: ("⛈️", "Tormenta ligera"),
        96: ("⛈️", "Tormenta con granizo ligero"),
        99: ("⛈️", "Tormenta con granizo fuerte"),
    }

    WIND_DIRECTIONS = (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO",
    )

    @staticmethod
    async def geocode(location_query: str) -> Optional[WeatherLocation]:
        """Obtiene coordenadas desde el nombre de una ubicación."""
        try:
            url = (
                "https://geocoding-api.open-meteo.com/v1/search?"
                f"name={quote_plus(location_query)}&count=1&language=es&format=json"
            )
            response_raw = await http.get_json(url)
            if not isinstance(response_raw, dict):
                return None

            response: dict[str, Any] = cast(dict[str, Any], response_raw)
            results: list[Any] = cast(list[Any], response.get("results", []))
            if not results:
                return None

            first_result_raw: Any = results[0]
            if not isinstance(first_result_raw, dict):
                return None

            first_result: Mapping[str, Any] = cast(Mapping[str, Any], first_result_raw)
            return WeatherLocation.from_api(first_result)
        except (HttpError, asyncio.TimeoutError, KeyError, AttributeError):
            return None

    @staticmethod
    async def fetch_weather(
        latitude: float,
        longitude: float,
        timezone: str = "auto",
    ) -> Optional[WeatherData]:
        """Obtiene datos meteorológicos completos de Open-Meteo."""
        # Variables actuales más completas
        current_vars = [
            "temperature_2m",
            "apparent_temperature",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
            "relative_humidity_2m",
            "dew_point_2m",
            "precipitation",
            "rain",
            "showers",
            "snowfall",
            "cloud_cover",
            "pressure_msl",
            "visibility",
            "uv_index",
            "is_day",
        ]

        # Variables diarias
        daily_vars = [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "wind_direction_10m_dominant",
            "sunrise",
            "sunset",
            "uv_index_max",
        ]

        # Variables horarias (próximas 24 horas)
        hourly_vars = [
            "temperature_2m",
            "relative_humidity_2m",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
            "precipitation_probability",
        ]

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(current_vars),
            "daily": ",".join(daily_vars),
            "hourly": ",".join(hourly_vars),
            "timezone": timezone,
            "forecast_days": 7,
        }
        query_str = "&".join(
            f"{key}={quote_plus(str(value))}" for key, value in params.items()
        )
        url = f"{API_CONFIG.open_meteo_url}/forecast?{query_str}"

        try:
            response_raw = await http.get_json(url)
            if not isinstance(response_raw, dict):
                return None

            response: dict[str, Any] = cast(dict[str, Any], response_raw)
            if not response.get("current"):
                return None
            return response
        except (HttpError, asyncio.TimeoutError, KeyError):
            return None

    @staticmethod
    def wind_direction_cardinal(degrees: Optional[float]) -> str:
        """Convierte grados a dirección cardinal."""
        if degrees is None:
            return "?"
        index = int((degrees + 11.25) / 22.5) % 16
        return OpenMeteoClient.WIND_DIRECTIONS[index]

    @staticmethod
    def get_weather_emoji_and_desc(code: int) -> tuple[str, str]:
        """Obtiene emoji y descripción para un código meteorológico."""
        return OpenMeteoClient.WEATHER_CODES.get(code, ("🌡️", "Desconocido"))


# ============================================================================
# CONSTRUCTOR DE EMBEDS
# ============================================================================

class WeatherEmbedBuilder:
    """Constructor de embeds meteorológicos personalizados."""

    @staticmethod
    def build_current_weather(
        location: WeatherLocation,
        weather_data: WeatherData,
        config: WeatherConfig,
        selected_info: Set[str],
    ) -> discord.Embed:
        """Construye el embed de clima actual."""
        current_raw = weather_data.get("current")
        daily_raw = weather_data.get("daily")
        current: dict[str, Any] = cast(dict[str, Any], current_raw) if isinstance(current_raw, dict) else {}
        daily: dict[str, Any] = cast(dict[str, Any], daily_raw) if isinstance(daily_raw, dict) else {}

        # Código y descripción meteorológica
        code = int(current.get("weather_code", 0) or 0)
        emoji, description = OpenMeteoClient.get_weather_emoji_and_desc(code)

        display_name = location.name
        if location.admin1 and location.admin1 not in display_name:
            display_name += f", {location.admin1}"
        if location.country and location.country not in display_name:
            display_name += f" ({location.country})"

        embed = discord.Embed(
            title=f"{config.embed_title} • {display_name}",
            description=f"{emoji} {description}",
            color=config.embed_color,
            timestamp=datetime.now(),
        )

        # Temperatura
        if "temperatura" in selected_info:
            temp = current.get("temperature_2m")
            feels_like = current.get("apparent_temperature")
            temp_max = daily.get("temperature_2m_max", [None])[0]
            temp_min = daily.get("temperature_2m_min", [None])[0]
            dew = current.get("dew_point_2m")

            temp_str = f"**Actual:** {temp}°C"
            if feels_like is not None:
                temp_str += f"\n**Sensación:** {feels_like}°C"
            if temp_max is not None:
                temp_str += f"\n**Máxima:** {temp_max}°C"
            if temp_min is not None:
                temp_str += f"\n**Mínima:** {temp_min}°C"
            if dew is not None:
                temp_str += f"\n**Punto de rocío:** {dew}°C"

            embed.add_field(name="🌡️ Temperatura", value=temp_str, inline=False)

        # Humedad
        if "humedad" in selected_info:
            humidity = current.get("relative_humidity_2m")
            dew = current.get("dew_point_2m")
            humidity_str = ""
            if humidity is not None:
                humidity_str += f"**Relativa:** {humidity}%"
            if dew is not None:
                humidity_str += f"\n**Punto de rocío:** {dew}°C"
            if humidity_str:
                embed.add_field(name="💧 Humedad", value=humidity_str, inline=True)

        # Precipitación
        if "precipitacion" in selected_info:
            precip = current.get("precipitation")
            rain = current.get("rain")
            showers = current.get("showers")
            snowfall = current.get("snowfall")
            prob = daily.get("precipitation_probability_max", [0])[0]

            precip_str = f"**Probabilidad:** {prob}%"
            if precip is not None:
                precip_str += f"\n**Total:** {precip} mm"
            if rain is not None and rain > 0:
                precip_str += f"\n**Lluvia:** {rain} mm"
            if showers is not None and showers > 0:
                precip_str += f"\n**Chubascos:** {showers} mm"
            if snowfall is not None and snowfall > 0:
                precip_str += f"\n**Nieve:** {snowfall} cm"

            embed.add_field(name="🌧️ Precipitación", value=precip_str, inline=True)

        # Viento
        if "viento" in selected_info:
            speed = current.get("wind_speed_10m")
            direction = current.get("wind_direction_10m")
            gusts = current.get("wind_gusts_10m")

            wind_str = f"**Velocidad:** {speed} km/h"
            if direction is not None:
                cardinal = OpenMeteoClient.wind_direction_cardinal(direction)
                wind_str += f" {cardinal}"
            if gusts is not None and gusts > 0:
                wind_str += f"\n**Ráfagas:** {gusts} km/h"

            embed.add_field(name="💨 Viento", value=wind_str, inline=True)

        # Atmósfera
        if "atmosfera" in selected_info:
            cloud = current.get("cloud_cover")
            pressure = current.get("pressure_msl")
            visibility = current.get("visibility")

            atm_str = ""
            if cloud is not None:
                atm_str += f"**Nubosidad:** {cloud}%\n"
            if pressure is not None:
                atm_str += f"**Presión:** {pressure} hPa\n"
            if visibility is not None:
                atm_str += f"**Visibilidad:** {visibility / 1000:.1f} km\n"

            if atm_str:
                embed.add_field(name="🌫️ Atmósfera", value=atm_str.strip(), inline=True)

        # UV y Radiación
        if "uv" in selected_info:
            uv = current.get("uv_index")
            uv_max = daily.get("uv_index_max", [None])[0]

            uv_str = f"**Actual:** {uv}"
            if uv_max is not None:
                uv_str += f"\n**Máximo hoy:** {uv_max}"

            embed.add_field(name="☀️ Índice UV", value=uv_str, inline=True)

        # Amanecer/Atardecer
        if "sol" in selected_info:
            sunrise = daily.get("sunrise", [None])[0]
            sunset = daily.get("sunset", [None])[0]

            sol_str = ""
            if sunrise:
                sunrise_time = sunrise.split("T")[1] if "T" in sunrise else sunrise
                sol_str += f"🌅 **Amanecer:** {sunrise_time}\n"
            if sunset:
                sunset_time = sunset.split("T")[1] if "T" in sunset else sunset
                sol_str += f"🌇 **Atardecer:** {sunset_time}"

            if sol_str:
                embed.add_field(name="☀️ Sol", value=sol_str, inline=True)

        embed.set_footer(text="📡 Datos de Open-Meteo")
        return embed

    @staticmethod
    def build_hourly_forecast(
        weather_data: WeatherData,
        location: WeatherLocation,
        config: WeatherConfig,
        hours: int = 6,
    ) -> Optional[discord.Embed]:
        """Construye embed con pronóstico horario."""
        hourly_raw = weather_data.get("hourly")
        hourly: dict[str, Any] = cast(dict[str, Any], hourly_raw) if isinstance(hourly_raw, dict) else {}
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        humidity = hourly.get("relative_humidity_2m", [])
        codes = hourly.get("weather_code", [])
        precip_prob = hourly.get("precipitation_probability", [])

        if not times:
            return None

        embed = discord.Embed(
            title=f"🕐 Pronóstico horario - {location.name}",
            color=config.embed_color,
            timestamp=datetime.now(),
        )

        forecast_text = ""
        for i in range(min(hours, len(times))):
            time_str = times[i].split("T")[1] if "T" in times[i] else times[i]
            temp = temps[i] if i < len(temps) else "?"
            code = int(codes[i]) if i < len(codes) else 0
            emoji, _ = OpenMeteoClient.get_weather_emoji_and_desc(code)
            prob = precip_prob[i] if i < len(precip_prob) else 0
            humid = humidity[i] if i < len(humidity) else 0

            forecast_text += f"**{time_str}** {emoji} {temp}°C | 💧 {humid}% | 🌧️ {prob}%\n"

        embed.description = forecast_text
        embed.set_footer(text="📡 Datos de Open-Meteo")
        return embed

    @staticmethod
    def build_daily_forecast(
        weather_data: WeatherData,
        location: WeatherLocation,
        config: WeatherConfig,
        days: int = 3,
    ) -> Optional[discord.Embed]:
        """Construye embed con pronóstico diario."""
        daily_raw = weather_data.get("daily")
        daily: dict[str, Any] = cast(dict[str, Any], daily_raw) if isinstance(daily_raw, dict) else {}
        times = daily.get("time", [])
        codes = daily.get("weather_code", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        precip_prob = daily.get("precipitation_probability_max", [])

        if not times:
            return None

        embed = discord.Embed(
            title=f"📅 Pronóstico diario - {location.name}",
            color=config.embed_color,
            timestamp=datetime.now(),
        )

        forecast_text = ""
        for i in range(min(days, len(times))):
            date = times[i]
            code = int(codes[i]) if i < len(codes) else 0
            emoji, _ = OpenMeteoClient.get_weather_emoji_and_desc(code)
            max_t = temp_max[i] if i < len(temp_max) else "?"
            min_t = temp_min[i] if i < len(temp_min) else "?"
            prob = precip_prob[i] if i < len(precip_prob) else 0

            forecast_text += f"**{date}** {emoji} {min_t}°C — {max_t}°C | 🌧️ {prob}%\n"

        embed.description = forecast_text
        embed.set_footer(text="📡 Datos de Open-Meteo")
        return embed


# ============================================================================
# VISTAS DE CONFIGURACIÓN
# ============================================================================

class LocationModal(discord.ui.Modal):
    """Modal para buscar ubicación por nombre."""

    location_input: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Nombre de la ubicación",
        placeholder="ej: Apizaco, Tlaxcala, México",
        min_length=2,
        max_length=100,
    )

    def __init__(self) -> None:
        super().__init__(title="📍 Buscar Ubicación")
        self.location: Optional[WeatherLocation] = None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        location = await OpenMeteoClient.geocode(self.location_input.value)

        if not location:
            await interaction.followup.send(
                "❌ No se encontró la ubicación. Intenta con otro nombre.",
                ephemeral=True,
            )
            return

        self.location = location


class InformationSelectView(discord.ui.View):
    """Select menu para elegir la información meteorológica."""

    def __init__(self, config: WeatherConfig):
        super().__init__()
        self.selected: Set[str] = set(config.selected_info)

    @discord.ui.select(
        placeholder="Selecciona la información que deseas",
        min_values=1,
        max_values=8,
        options=[
            discord.SelectOption(label="🌡️ Temperatura", value="temperatura"),
            discord.SelectOption(label="💧 Humedad", value="humedad"),
            discord.SelectOption(label="🌧️ Precipitación", value="precipitacion"),
            discord.SelectOption(label="💨 Viento", value="viento"),
            discord.SelectOption(label="🌫️ Atmósfera", value="atmosfera"),
            discord.SelectOption(label="☀️ UV", value="uv"),
            discord.SelectOption(label="☀️ Sol", value="sol"),
            discord.SelectOption(label="✨ Información completa", value="completa"),
        ],
    )
    async def select_info(
        self, interaction: discord.Interaction, select: discord.ui.Select[Any]
    ) -> None:
        if "completa" in select.values:
            self.selected = {
                "temperatura", "humedad", "precipitacion",
                "viento", "atmosfera", "uv", "sol",
            }
        else:
            self.selected = set(select.values)

        await interaction.response.defer()
        self.stop()


class ForecastSelectView(discord.ui.View):
    """Select menu para elegir los tipos de pronóstico a publicar."""

    def __init__(self, config: WeatherConfig):
        super().__init__()
        self.selected: Set[str] = set(config.forecast_types) or {"actual"}

    @discord.ui.select(
        placeholder="Selecciona los pronósticos a publicar",
        min_values=1,
        max_values=3,
        options=[
            discord.SelectOption(label="🌤️ Clima actual", value="actual"),
            discord.SelectOption(label="🕐 Pronóstico horario (6 h)", value="horario"),
            discord.SelectOption(label="📅 Pronóstico diario (3 días)", value="diario"),
        ],
    )
    async def select_forecast(
        self, interaction: discord.Interaction, select: discord.ui.Select[Any]
    ) -> None:
        self.selected = set(select.values)
        await interaction.response.defer()
        self.stop()


class WeatherConfigView(discord.ui.View):
    """Vista interactiva principal de configuración meteorológica."""

    INFO_LABELS: Dict[str, str] = {
        "temperatura": "🌡️ Temperatura",
        "humedad": "💧 Humedad",
        "precipitacion": "🌧️ Precipitación",
        "viento": "💨 Viento",
        "atmosfera": "🌫️ Atmósfera",
        "uv": "☀️ UV",
        "sol": "☀️ Sol",
    }

    FORECAST_LABELS: Dict[str, str] = {
        "actual": "🌤️ Clima actual",
        "horario": "🕐 Horario",
        "diario": "📅 Diario",
    }

    def __init__(self, bot: commands.Bot, guild_id: int, config: WeatherConfig):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id
        self.config = config
        self.working_config = WeatherConfig(**asdict(config))

    async def update_embed(self, interaction: discord.Interaction) -> None:
        """Actualiza el embed principal con la configuración actual."""
        embed = discord.Embed(
            title="🌤️ Configuración del Clima",
            description="Personaliza tu servicio meteorológico automático.",
            color=discord.Color.blue(),
        )

        embed.add_field(name="📡 API", value="Open-Meteo", inline=False)

        location_display = self.working_config.location_name
        if location_display == "Not Set":
            location_display = "No configurada"
        embed.add_field(name="📍 Ubicación", value=location_display, inline=False)

        channel_display = (
            f"<#{self.working_config.channel_id}>"
            if self.working_config.channel_id
            else "No configurado"
        )
        embed.add_field(name="📺 Canal", value=channel_display, inline=False)

        info_display = (
            ", ".join(self.INFO_LABELS.get(i, i) for i in sorted(self.working_config.selected_info))
            if self.working_config.selected_info
            else "Ninguna"
        )
        embed.add_field(
            name="📊 Información", value=info_display[:1024] or "Ninguna", inline=False
        )

        forecast_display = ", ".join(
            self.FORECAST_LABELS.get(f, f) for f in sorted(self.working_config.forecast_types)
        )
        embed.add_field(name="📅 Pronóstico", value=forecast_display, inline=False)

        role_display = (
            f"<@&{self.working_config.role_id}>"
            if self.working_config.role_id
            else "Ninguno"
        )
        embed.add_field(name="🔔 Rol de notificación", value=role_display, inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📍 Ubicación", style=discord.ButtonStyle.primary, emoji="📍")
    async def button_location(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        modal = LocationModal()
        await interaction.response.send_modal(modal)

        # Esperar a que el modal se complete (timeout del modal: Discord 15 min)
        timed_out = False
        try:
            await asyncio.wait_for(modal.wait(), timeout=180)
        except asyncio.TimeoutError:
            timed_out = True

        if not timed_out and modal.location is not None:
            loc = modal.location
            self.working_config.location_name = loc.name
            self.working_config.latitude = loc.latitude
            self.working_config.longitude = loc.longitude
            self.working_config.timezone = loc.timezone
            self.working_config.country = loc.country
            try:
                await self.update_embed(interaction)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="📊 Información", style=discord.ButtonStyle.primary, emoji="📊")
    async def button_information(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        view = InformationSelectView(self.working_config)
        embed = discord.Embed(
            title="📊 Selecciona la información",
            description="Elige qué datos meteorológicos deseas recibir.",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        try:
            await asyncio.wait_for(view.wait(), timeout=120)
            if view.selected:
                self.working_config.selected_info = view.selected
            await self.update_embed(interaction)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="📅 Pronóstico", style=discord.ButtonStyle.primary, emoji="📅")
    async def button_forecast(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        view = ForecastSelectView(self.working_config)
        embed = discord.Embed(
            title="📅 Pronósticos automáticos",
            description=(
                "Elige qué secciones publicaremos: clima actual, "
                "pronóstico horario y/o pronóstico diario."
            ),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        try:
            await asyncio.wait_for(view.wait(), timeout=120)
            if view.selected:
                self.working_config.forecast_types = view.selected
            await self.update_embed(interaction)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="📺 Canal", style=discord.ButtonStyle.primary, emoji="📺")
    async def button_channel(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        menu: discord.ui.ChannelSelect[discord.ui.View] = discord.ui.ChannelSelect(
            placeholder="Selecciona el canal de actualizaciones…",
            channel_types=[discord.ChannelType.text],
        )

        async def _pick(interaction: discord.Interaction) -> None:
            if menu.values:
                self.working_config.channel_id = int(menu.values[0].id)
            await interaction.response.defer()
            view.stop()

        view = discord.ui.View()
        menu.callback = _pick
        view.add_item(menu)
        await interaction.response.send_message(
            "¿Qué canal quieres usar para recibir las actualizaciones meteorológicas?",
            view=view,
            ephemeral=True,
        )

        try:
            await asyncio.wait_for(view.wait(), timeout=120)
            await self.update_embed(interaction)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="🔔 Rol", style=discord.ButtonStyle.primary, emoji="🔔")
    async def button_role(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        menu: discord.ui.RoleSelect[discord.ui.View] = discord.ui.RoleSelect(
            placeholder="Selecciona el rol de notificación…"
        )

        async def _pick(interaction: discord.Interaction) -> None:
            if menu.values:
                self.working_config.role_id = int(menu.values[0].id)
            else:
                self.working_config.role_id = None
            await interaction.response.defer()
            view.stop()

        view = discord.ui.View()
        menu.callback = _pick
        view.add_item(menu)
        await interaction.response.send_message(
            "Selecciona un rol para las notificaciones (o elige Ninguno).",
            view=view,
            ephemeral=True,
        )

        try:
            await asyncio.wait_for(view.wait(), timeout=120)
            await self.update_embed(interaction)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="👁️ Vista previa", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def button_preview(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if self.working_config.latitude == 0 and self.working_config.longitude == 0:
            await interaction.followup.send(
                "❌ Configura primero una ubicación.", ephemeral=True
            )
            return

        weather_data = await OpenMeteoClient.fetch_weather(
            self.working_config.latitude,
            self.working_config.longitude,
            self.working_config.timezone,
        )
        if not weather_data:
            await interaction.followup.send(
                "❌ No se pudo obtener datos de vista previa.", ephemeral=True
            )
            return

        location = WeatherLocation(
            name=self.working_config.location_name,
            latitude=self.working_config.latitude,
            longitude=self.working_config.longitude,
            country=self.working_config.country,
            timezone=self.working_config.timezone,
        )

        embed = WeatherEmbedBuilder.build_current_weather(
            location,
            weather_data,
            self.working_config,
            self.working_config.selected_info,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="💾 Guardar", style=discord.ButtonStyle.success, emoji="💾")
    async def button_save(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        if self.working_config.latitude == 0 and self.working_config.longitude == 0:
            await interaction.response.send_message(
                "❌ Debe configurar una ubicación primero.",
                ephemeral=True,
            )
            return

        if not self.working_config.channel_id:
            await interaction.response.send_message(
                "❌ Debe configurar un canal primero.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await self._save(interaction)

    async def _save(self, interaction: discord.Interaction) -> None:
        """Guarda la configuración en la base de datos."""
        await turso_db.setup()
        selected_info_json = json.dumps(sorted(self.working_config.selected_info))
        forecast_types_json = json.dumps(sorted(self.working_config.forecast_types))

        await turso_db.execute(
            """
            INSERT INTO weather_config
            (guild_id, channel_id, role_id, location_name, latitude, longitude, timezone, country,
             selected_info, forecast_types, embed_color, embed_title, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                role_id = excluded.role_id,
                location_name = excluded.location_name,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                timezone = excluded.timezone,
                country = excluded.country,
                selected_info = excluded.selected_info,
                forecast_types = excluded.forecast_types,
                embed_color = excluded.embed_color,
                embed_title = excluded.embed_title,
                updated_at = excluded.updated_at
            """,
            (
                self.guild_id,
                self.working_config.channel_id,
                self.working_config.role_id,
                self.working_config.location_name,
                self.working_config.latitude,
                self.working_config.longitude,
                self.working_config.timezone,
                self.working_config.country,
                selected_info_json,
                forecast_types_json,
                self.working_config.embed_color,
                self.working_config.embed_title,
                datetime.now().isoformat(),
            ),
        )

        await interaction.followup.send(
            "✅ Configuración guardada. El sistema enviará actualizaciones "
            "meteorológicas automáticamente cada 30 minutos.",
            ephemeral=True,
        )
        self.stop()


# ============================================================================
# COG PRINCIPAL
# ============================================================================

class Weather(commands.Cog):
    """Meteorología: consulta manual y publicación automática con Open-Meteo."""

    CACHE_TTL_SECONDS = 30 * 60  # 30 minutos

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.weather_cache: dict[tuple[float, float], WeatherData] = {}
        self.cache_expiry: dict[tuple[float, float], float] = {}
        self.weather_publish_loop.start()

    # ------------------------------------------------------------------
    # PUBLICACIÓN AUTOMÁTICA
    # ------------------------------------------------------------------
    @tasks.loop(minutes=30)
    async def weather_publish_loop(self) -> None:
        """Tarea automática que publica actualizaciones meteorológicas."""
        try:
            await turso_db.setup()
            rows = await turso_db.fetch_all("SELECT * FROM weather_config")

            for row in rows:
                config = self._config_from_row(row)
                if not config.channel_id or config.latitude == 0 and config.longitude == 0:
                    continue

                guild = self.bot.get_guild(config.guild_id)
                if not guild:
                    continue

                channel = guild.get_channel(config.channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue
                if not channel.permissions_for(guild.me).send_messages:
                    continue

                weather_data = await self._get_weather_data(
                    config.latitude, config.longitude, config.timezone
                )
                if not weather_data:
                    continue

                location = WeatherLocation(
                    name=config.location_name,
                    latitude=config.latitude,
                    longitude=config.longitude,
                    country=config.country,
                    timezone=config.timezone,
                )

                embeds: list[discord.Embed] = []
                if "actual" in config.forecast_types or not config.forecast_types:
                    embeds.append(
                        WeatherEmbedBuilder.build_current_weather(
                            location, weather_data, config, config.selected_info
                        )
                    )

                if "horario" in config.forecast_types:
                    hourly_embed = WeatherEmbedBuilder.build_hourly_forecast(
                        weather_data, location, config, hours=6
                    )
                    if hourly_embed:
                        embeds.append(hourly_embed)

                if "diario" in config.forecast_types:
                    daily_embed = WeatherEmbedBuilder.build_daily_forecast(
                        weather_data, location, config, days=3
                    )
                    if daily_embed:
                        embeds.append(daily_embed)

                if not embeds:
                    continue

                # Mención opcional de rol
                content = self._role_mention(guild, channel, config.role_id)

                try:
                    await channel.send(content=content or None, embeds=embeds[:10])
                except discord.Forbidden:
                    continue

        except Exception as exc:
            logger.error("Error en weather_publish_loop: %s", exc)

    @weather_publish_loop.before_loop
    async def before_weather_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # AYUDANTES
    # ------------------------------------------------------------------
    @staticmethod
    def _role_mention(
        guild: discord.Guild,
        channel: discord.TextChannel,
        role_id: Optional[int],
    ) -> str:
        """Devuelve la mención del rol si el bot puede usarla."""
        if not role_id:
            return ""
        role = guild.get_role(role_id)
        if not role:
            return ""
        my_perms = channel.permissions_for(guild.me)
        if my_perms.mention_everyone or role.mentionable:
            return f"<@&{role_id}>"
        return ""

    async def _get_weather_data(
        self, latitude: float, longitude: float, timezone: str
    ) -> Optional[WeatherData]:
        """Obtiene datos meteorológicos con caché de 30 minutos."""
        cache_key = (latitude, longitude)
        now = datetime.now().timestamp()

        if cache_key in self.weather_cache:
            if self.cache_expiry.get(cache_key, 0) > now:
                return self.weather_cache[cache_key]

        data = await OpenMeteoClient.fetch_weather(latitude, longitude, timezone)

        if data:
            self.weather_cache[cache_key] = data
            self.cache_expiry[cache_key] = now + self.CACHE_TTL_SECONDS
            return data

        return None

    async def _load_config(self, guild_id: int) -> Optional[WeatherConfig]:
        """Carga la configuración del servidor desde la base de datos."""
        await turso_db.setup()
        rows = await turso_db.fetch_all(
            "SELECT * FROM weather_config WHERE guild_id = ?",
            (guild_id,),
        )
        if not rows:
            return None
        return self._config_from_row(rows[0])

    @staticmethod
    def _config_from_row(row: Any) -> WeatherConfig:
        """Convierte una fila de la tabla en ``WeatherConfig``."""
        return WeatherConfig(
            guild_id=row[0],
            channel_id=row[1],
            role_id=row[2],
            location_name=row[3] or "Not Set",
            latitude=row[4] or 0.0,
            longitude=row[5] or 0.0,
            timezone=row[6] or "UTC",
            country=row[7] or "",
            selected_info=(
                set(json.loads(row[8]))
                if row[8]
                else {"temperatura", "humedad", "viento", "precipitacion"}
            ),
            forecast_types=set(json.loads(row[9])) if row[9] else {"actual"},
            embed_color=row[10] if row[10] else DEFAULT_EMBED_COLOR,
            embed_title=row[11] if row[11] else DEFAULT_EMBED_TITLE,
            updated_at=row[13] if len(row) > 13 and row[13] else None,
        )

    # ------------------------------------------------------------------
    # COMANDOS
    # ------------------------------------------------------------------
    @app_commands.command(
        name="weather", description="Obtén información del clima de una ubicación."
    )
    @app_commands.describe(
        latitude="Latitud de la ubicación",
        longitude="Longitud de la ubicación",
    )
    async def weather_manual(
        self,
        interaction: discord.Interaction,
        latitude: float,
        longitude: float,
    ) -> None:
        """Comando manual de consulta meteorológica."""
        await interaction.response.defer()

        weather_data = await self._get_weather_data(latitude, longitude, "auto")
        if not weather_data:
            await interaction.followup.send(
                "❌ No se pudo obtener información meteorológica.", ephemeral=True
            )
            return

        location = WeatherLocation(
            name=f"{latitude}, {longitude}",
            latitude=latitude,
            longitude=longitude,
            country="",
            timezone="UTC",
        )

        config = WeatherConfig(
            guild_id=interaction.guild_id or 0,
            selected_info={
                "temperatura", "humedad", "viento", "precipitacion", "atmosfera",
            },
        )

        embed = WeatherEmbedBuilder.build_current_weather(
            location,
            weather_data,
            config,
            config.selected_info,
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="weather-config",
        description="Configura el servicio meteorológico automático.",
    )
    @app_commands.default_permissions(administrator=True)
    async def weather_configure(self, interaction: discord.Interaction) -> None:
        """Abre el panel de configuración meteorológica."""
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Este comando requiere un servidor.", ephemeral=True
            )
            return

        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                "❌ No se pudo determinar el servidor de esta interacción.", ephemeral=True
            )
            return

        await interaction.response.defer()

        config = await self._load_config(guild_id)
        if not config:
            config = WeatherConfig(guild_id=guild_id)

        view = WeatherConfigView(self.bot, guild_id, config)

        embed = discord.Embed(
            title="🌤️ Configuración del Clima",
            description="Personaliza tu servicio meteorológico automático.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="📡 API", value="Open-Meteo", inline=False)
        embed.add_field(
            name="📍 Ubicación",
            value=config.location_name if config.location_name != "Not Set" else "No configurada",
            inline=False,
        )
        embed.add_field(name="📺 Canal", value="No configurado", inline=False)

        await interaction.followup.send(embed=embed, view=view)

    async def cog_unload(self) -> None:
        """Limpia recursos al descargar el cog."""
        self.weather_publish_loop.cancel()


# ============================================================================
# INSTALACIÓN
# ============================================================================

async def setup(bot: commands.Bot) -> None:
    """Instala el cog y crea su tabla si no existe."""
    await turso_db.setup()
    await turso_db.execute(
        """
        CREATE TABLE IF NOT EXISTS weather_config (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            role_id INTEGER,
            location_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timezone TEXT DEFAULT 'UTC',
            country TEXT,
            selected_info TEXT DEFAULT '["temperatura", "humedad", "viento", "precipitacion"]',
            forecast_types TEXT DEFAULT '["actual"]',
            embed_color INTEGER DEFAULT 3447003,
            embed_title TEXT DEFAULT '🌤️ Clima',
            last_published_data TEXT,
            updated_at TEXT
        )
        """
    )
    await bot.add_cog(Weather(bot))












