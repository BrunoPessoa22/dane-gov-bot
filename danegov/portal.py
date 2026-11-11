"""Read-only client for the public dane.gov.pl API (api.dane.gov.pl/1.4).

Used to check what actually landed on the portal, independently of how it was
delivered (browser upload or XML harvester).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel

from danegov.config import PORTAL_API, PORTAL_WEB
from danegov.models import DaneGovError

logger = logging.getLogger(__name__)

# The portal is slow and, reached through a residential proxy, connections drop
# now and then: network errors are retried, HTTP errors are not.
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5.0


class PortalError(DaneGovError):
    pass


class PortalDataset(BaseModel):
    id: str
    title: str
    harvested: bool


class PortalResource(BaseModel):
    id: str
    dataset_id: str
    title: str
    created: datetime

    @property
    def web_url(self) -> str:
        return f"{PORTAL_WEB}/dataset/{self.dataset_id}/resource/{self.id}"


class Portal:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _get(self, url: str, params: dict[str, str | int] | None = None) -> httpx.Response:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                return response
            except httpx.TransportError as exc:
                if attempt == ATTEMPTS:
                    raise
                logger.warning(
                    "dane.gov.pl request failed, retrying",
                    extra={"url": url, "attempt": attempt, "error": str(exc)},
                )
                time.sleep(RETRY_DELAY_SECONDS)
        raise AssertionError("unreachable")

    def _get_json(self, path: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        url = f"{PORTAL_API}{path}"
        try:
            payload = self._get(url, params).json()
        except httpx.HTTPError as exc:
            raise PortalError(f"dane.gov.pl API request failed: {url}: {exc}") from exc
        except ValueError as exc:
            raise PortalError(f"dane.gov.pl API returned invalid JSON: {url}") from exc
        if not isinstance(payload, dict) or "data" not in payload:
            raise PortalError(f"unexpected dane.gov.pl API response for {url}")
        return payload

    def datasets(self, institution_id: int) -> list[PortalDataset]:
        payload = self._get_json(f"/institutions/{institution_id}/datasets", {"per_page": 100})
        datasets: list[PortalDataset] = []
        for item in payload["data"]:
            attributes = item.get("attributes", {})
            source = attributes.get("source") or {}
            datasets.append(
                PortalDataset(
                    id=str(item["id"]),
                    title=attributes.get("title", ""),
                    harvested=source.get("type") == "xml",
                )
            )
        return datasets

    def harvester_active(self, institution_id: int) -> bool:
        return any(d.harvested for d in self.datasets(institution_id))

    def resource(self, resource_id: str) -> PortalResource:
        """One resource by id. Unlike the listings, this is available right after upload."""
        item = self._get_json(f"/resources/{resource_id}")["data"]
        attributes = item.get("attributes", {})
        dataset = item.get("relationships", {}).get("dataset", {}).get("data") or {}
        return PortalResource(
            id=str(item["id"]),
            dataset_id=str(dataset.get("id", "")),
            title=attributes.get("title", "").strip(),
            created=attributes["created"],
        )

    def download(self, resource_id: str) -> bytes:
        url = f"https://api.dane.gov.pl/resources/{resource_id}/file"
        try:
            response = self._get(url)
        except httpx.HTTPError as exc:
            raise PortalError(f"cannot download resource {resource_id}: {exc}") from exc
        return response.content
