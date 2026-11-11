"""Network route to dane.gov.pl.

Since November 2026 dane.gov.pl (api, admin and www) only accepts connections
from Polish IP addresses; everyone else gets a TCP timeout. GitHub runners are
not in Poland, so the portal traffic can go through a proxy with a Polish exit,
set in DANE_GOV_PROXY as a URL (http://user:password@host:port). The developer's
website and Resend are reached directly.

The URL carries credentials: only `describe()` may be logged.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel

from danegov.models import DaneGovError

PROXY_ENV = "DANE_GOV_PROXY"
SCHEMES = ("http", "https", "socks5")


class ProxyConfigError(DaneGovError):
    pass


class PortalProxy(BaseModel):
    url: str
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def server(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def describe(self) -> str:
        """Loggable form, without credentials."""
        return self.server

    def playwright(self) -> dict[str, str]:
        settings = {"server": self.server}
        if self.username is not None:
            settings["username"] = self.username
        if self.password is not None:
            settings["password"] = self.password
        return settings


def parse_proxy(url: str) -> PortalProxy:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ProxyConfigError(f"{PROXY_ENV} is not a valid URL") from None
    if parts.scheme not in SCHEMES:
        raise ProxyConfigError(f"{PROXY_ENV} must start with {', '.join(SCHEMES)} (://)")
    if not parts.hostname or port is None:
        raise ProxyConfigError(f"{PROXY_ENV} needs a host and a port")
    return PortalProxy(
        url=url,
        scheme=parts.scheme,
        host=parts.hostname,
        port=port,
        username=unquote(parts.username) if parts.username is not None else None,
        password=unquote(parts.password) if parts.password is not None else None,
    )


def portal_proxy() -> PortalProxy | None:
    """The proxy for dane.gov.pl, or None to connect directly."""
    value = os.environ.get(PROXY_ENV, "").strip()
    return parse_proxy(value) if value else None
