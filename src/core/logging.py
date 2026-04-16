import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal, cast

import structlog
from structlog.typing import Processor

ServiceType = Literal["api", "worker", "telegram", "service"]


def configure_logging(
    service: ServiceType = "api",
    json_logs: bool = True,
    log_level: str = "INFO",
    enable_file_logging: bool = False,
) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Console handler: human-readable in dev, JSON in prod
    if json_logs:
        console_renderer: Processor = structlog.processors.JSONRenderer()
    else:
        console_renderer = structlog.dev.ConsoleRenderer(colors=True)

    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ],
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    if enable_file_logging:
        project_root = Path(__file__).resolve().parent.parent.parent
        log_dir = project_root / "logs"
        log_dir.mkdir(exist_ok=True)

        json_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )

        # Rotating file: 10MB max, keep 5 backups
        file_handler = RotatingFileHandler(
            log_dir / f"{service}.json",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Quiet noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("arq").setLevel(logging.INFO)
    logging.getLogger("watchfiles.main").setLevel(
        logging.WARNING
    )  # Silence "rust notify timeout"
    logging.getLogger("asyncio").setLevel(
        logging.WARNING
    )  # Silence selector debug messages
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(
        logging.WARNING
    )  # Silence SQL queries


def get_logger(
    service: ServiceType, **initial_context: object
) -> structlog.stdlib.BoundLogger:
    logger = structlog.get_logger(service=service, **initial_context)
    return cast(structlog.stdlib.BoundLogger, logger)
