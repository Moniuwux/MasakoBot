from __future__ import annotations
# ----------------------------------------------------------------------------
# Ejecución directa (p. ej. `python cogs/general.py`): este archivo es
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
    _sys.path[:] = [p for p in _sys.path if _Path(p).resolve() != _here]
    print("[AVISO] Este archivo es un cog del bot, no un script ejecutable.")
    print("        Arranca el bot con:  python main.py  (desde la raiz del proyecto)")

from discord import app_commands
from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from bot import Masako


class General(commands.Cog):
    """Cog placeholder con comandos básicos de utilidad."""

    def __init__(self, bot: Masako) -> None:
        self.bot = bot

    @commands.hybrid_command(name="ping", description="Comprueba la latencia del bot.")
    async def ping(self, ctx: commands.Context[commands.Bot]) -> None:
        await ctx.send(f"Pong! Latencia: {round(self.bot.latency * 1000)}ms")

    @commands.hybrid_command(name="prefix", description="Cambia el prefijo de este servidor.")
    @app_commands.describe(nuevo="Nuevo prefijo o 'default' para restaurar m!")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def prefix(self, ctx: commands.Context[commands.Bot], nuevo: str) -> None:
        """Configura el prefijo de forma independiente por servidor."""
        if ctx.guild is None:
            await ctx.send("Este comando solo funciona dentro de un servidor.")
            return

        nuevo = nuevo.strip()
        if nuevo.lower() == "default":
            self.bot.set_guild_prefix(ctx.guild.id, None)
            await ctx.send("Prefijo restaurado a `m!`.")
            return

        if not 1 <= len(nuevo) <= 10 or any(char.isspace() for char in nuevo):
            await ctx.send("El prefijo debe tener entre 1 y 10 caracteres y no contener espacios.")
            return

        self.bot.set_guild_prefix(ctx.guild.id, nuevo)
        await ctx.send(f"Prefijo configurado: `{nuevo}`")

    @prefix.error
    async def prefix_error(self, ctx: commands.Context[commands.Bot], error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Necesitas permiso de gestionar el servidor para cambiar el prefijo.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("Este comando solo funciona dentro de un servidor.")
        else:
            raise error


async def setup(bot: Masako) -> None:
    await bot.add_cog(General(bot))
