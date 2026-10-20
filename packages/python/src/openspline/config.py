"""Validated, dependency-free client configuration."""

import math
import os
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

Quality = Literal["low", "high"]


@dataclass(frozen=True)
class OpensplineConfig:
    url: str | None = field(default_factory=lambda: os.getenv("OPENSPLINE_URL"))
    quality: Quality = "low"
    timeout: float = 180
    viewer_timeout: float = 60
    api_key: str | None = field(default_factory=lambda: os.getenv("OPENSPLINE_API_KEY"), repr=False)

    def __post_init__(self):
        if self.api_key is not None and (not isinstance(self.api_key, str) or not self.api_key or any(c.isspace() for c in self.api_key)):
            raise ValueError("api_key must be a nonempty API key without whitespace")
        object.__setattr__(self, "_url_defaulted", self.url is None)
        if self.url is None:
            object.__setattr__(self, "url", "https://dashboard.openspline.dev/api" if self.api_key else "http://localhost:7860")
        if not isinstance(self.url, str):
            raise ValueError("url must be an HTTP or HTTPS URL")
        try:
            parsed = urlsplit(self.url)
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
        except ValueError:
            valid = False
        if (
            not valid
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in self.url)
        ):
            raise ValueError(
                "url must be an HTTP or HTTPS URL without credentials, query, or fragment"
            )
        if self.quality not in ("low", "high"):
            raise ValueError("quality must be low or high")
        if self.api_key and parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Cloud API keys require HTTPS except on localhost")
        for name in ("timeout", "viewer_timeout"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number of seconds")
        object.__setattr__(self, "url", self.url.rstrip("/"))
