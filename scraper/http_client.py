from __future__ import annotations

import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter

from . import USER_AGENT


class ScraperAccessError(RuntimeError):
    """Base error for an access policy failure."""


class RecipeAuthorizationRequired(ScraperAccessError):
    """Raised when recipe pages were not explicitly authorized."""


class RobotsBlocked(ScraperAccessError):
    """Raised when robots.txt disallows a URL."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    text: str
    status_code: int


class AcademicHttpClient:
    """Small, deliberately conservative HTTP client for the collector."""

    def __init__(
        self,
        *,
        delay_seconds: float = 2.0,
        timeout_seconds: tuple[float, float] = (10.0, 30.0),
        max_retries: int = 3,
        allow_authorized_recipe_pages: bool = False,
        override_robots_with_permission: bool = False,
        user_agent: str = USER_AGENT,
        session: requests.Session | None = None,
    ) -> None:
        if override_robots_with_permission and not allow_authorized_recipe_pages:
            raise ValueError(
                "O override de robots.txt exige --allow-authorized-recipe-pages."
            )
        self.delay_seconds = max(0.0, delay_seconds)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.allow_authorized_recipe_pages = allow_authorized_recipe_pages
        self.override_robots_with_permission = override_robots_with_permission
        self.user_agent = user_agent
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
        )
        adapter = HTTPAdapter(max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request_at = 0.0

    def close(self) -> None:
        self.session.close()

    def _origin(self, url: str) -> str:
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            raise ValueError(f"URL inválida: {url}")
        return f"{parts.scheme}://{parts.netloc}"

    def _sleep_between_requests(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _request(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._sleep_between_requests()
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                self._last_request_at = time.monotonic()
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    retry_after = response.headers.get("Retry-After")
                    sleep_seconds = self._retry_after_seconds(retry_after, attempt)
                    time.sleep(sleep_seconds)
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                time.sleep(2**attempt)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _retry_after_seconds(value: str | None, attempt: int) -> float:
        if value:
            try:
                return max(0.0, float(value))
            except ValueError:
                try:
                    target = parsedate_to_datetime(value).timestamp()
                    return max(0.0, target - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass
        return float(2 ** (attempt + 1))

    def _robots_for(self, url: str) -> RobotFileParser:
        origin = self._origin(url)
        if origin in self._robots:
            return self._robots[origin]

        robots_url = f"{origin}/robots.txt"
        response = self._request(robots_url)
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        self._robots[origin] = parser
        return parser

    def can_fetch(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(self.user_agent, url)

    def fetch(self, url: str, *, resource_kind: str = "category") -> FetchResult:
        is_recipe = urlsplit(url).path.startswith("/receita/")
        if is_recipe and not self.allow_authorized_recipe_pages:
            raise RecipeAuthorizationRequired(
                "Páginas /receita/ estão protegidas por padrão. "
                "Use fixtures ou execute somente com autorização explícita."
            )

        allowed_by_robots = self.can_fetch(url)
        if not allowed_by_robots and not (
            is_recipe and self.override_robots_with_permission
        ):
            raise RobotsBlocked(
                f"robots.txt não permite coletar esta URL ({resource_kind}): {url}"
            )

        response = self._request(url)
        return FetchResult(url=response.url, text=response.text, status_code=response.status_code)

