"""Extract privacy-safe analytics facts from an incoming request."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Request

from app.core.config import settings
from app.core.security import client_ip, hash_ip

#: Automated clients; matched before phones because bots often fake them.
BOT_PATTERN = re.compile(
    r"(bot|crawler|spider|slurp|curl/|wget/|python-requests|httpx|go-http-client|"
    r"java/|okhttp|headless|phantomjs|scrapy)",
    re.IGNORECASE,
)
TABLET_PATTERN = re.compile(r"(ipad|tablet|kindle|silk|playbook|nexus 7|nexus 9)", re.IGNORECASE)
MOBILE_PATTERN = re.compile(
    r"(mobile|iphone|ipod|android|blackberry|opera mini|iemobile|windows phone|webos)",
    re.IGNORECASE,
)

#: Field limits that mirror the database columns.
REFERER_LIMIT = 255
USER_AGENT_LIMIT = 400


@dataclass(frozen=True)
class ClickInfo:
    """Everything the analytics table needs about one visit."""

    device_type: str
    referer: str | None
    user_agent: str | None
    ip_hash: str


def detect_device(user_agent: str | None) -> str:
    """Classify a User-Agent string into a coarse device type."""
    if not user_agent:
        return "other"
    if BOT_PATTERN.search(user_agent):
        return "bot"
    if TABLET_PATTERN.search(user_agent):
        return "tablet"
    if MOBILE_PATTERN.search(user_agent):
        return "mobile"
    return "desktop"


def extract_source(referer: str | None) -> str | None:
    """Reduce a Referer header to a compact source host."""
    if not referer:
        return None
    parsed = urlparse(referer)
    host = (parsed.netloc or "").lower()
    if not host:
        return None
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    own_host = (urlparse(settings.base_url).hostname or "").lower()
    if host == own_host:
        return "internal"
    return host[:REFERER_LIMIT]


def describe_click(request: Request) -> ClickInfo:
    """Collect the analytics payload for a redirect request."""
    user_agent = request.headers.get("user-agent")
    if user_agent is not None:
        user_agent = user_agent[:USER_AGENT_LIMIT]
    return ClickInfo(
        device_type=detect_device(request.headers.get("user-agent")),
        referer=extract_source(request.headers.get("referer")),
        user_agent=user_agent,
        ip_hash=hash_ip(client_ip(request)),
    )
