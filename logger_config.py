"""Configuración de logging profesional."""

import logging
import sys

# Asegura que la consola en Windows soporte UTF-8 sin errores de charmap
if sys.platform == "win32":
    try:
        stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
        if callable(stdout_reconfigure):
            stdout_reconfigure(encoding="utf-8", errors="replace")
        stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
        if callable(stderr_reconfigure):
            stderr_reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class ColoredFormatter(logging.Formatter):
    """Formateador con colores para consola."""

    COLORS = {
        "DEBUG": "\033[36m",      # Cyan
        "INFO": "\033[32m",       # Green
        "WARNING": "\033[33m",    # Yellow
        "ERROR": "\033[31m",      # Red
        "CRITICAL": "\033[35m",   # Magenta
        "RESET": "\033[0m",       # Reset
    }

    def format(self, record: logging.LogRecord) -> str:
        """Formatea el registro con colores."""
        log_color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        record.levelname = f"{log_color}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)


def setup_logger(
    name: str,
    level: int = logging.INFO,
    use_color: bool = True,
) -> logging.Logger:
    """Configura un logger profesional.

    Args:
        name: Nombre del logger.
        level: Nivel de logging.
        use_color: Si usar colores en la salida.

    Returns:
        logging.Logger: Logger configurado.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Elimina handlers anteriores para evitar duplicados
    logger.handlers.clear()

    # Handler para consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    format_string = (
        "%(asctime)s | "
        "%(levelname)-8s | "
        "%(name)-15s | "
        "%(message)s"
    )

    if use_color:
        formatter = ColoredFormatter(
            fmt=format_string,
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        formatter = logging.Formatter(
            fmt=format_string,
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
