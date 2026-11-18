"""Dashboard web del bot: vedi `dashboard.app`."""

from .app import ConfigError, DashboardConfig, DashboardServer, create_app

__all__ = ["ConfigError", "DashboardConfig", "DashboardServer", "create_app"]
