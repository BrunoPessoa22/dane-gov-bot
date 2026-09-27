"""Read-only client for the public dane.gov.pl API (api.dane.gov.pl/1.4).

Used to check what actually landed on the portal, independently of how it was
delivered (browser upload or XML harvester).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import httpx
from pydantic import BaseModel

from danegov.config import PORTAL_API, PORTAL_WEB
from danegov.models import DaneGovError

logger = logging.getLogger(__name__)


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

    def _get_json(self, path: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        url = f"{PORTAL_API}{path}"
        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
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

    def resources_for_day(self, institution_id: int, day: date) -> list[PortalResource]:
        """Resources whose title ends with the day's date, newest first.

        Listings come from a search index that lags uploads by hours, so an
        empty result does not prove the day is missing.
        """
        suffix = day.isoformat()
        found: list[PortalResource] = []
        for dataset in self.datasets(institution_id):
            payload = self._get_json(
                f"/datasets/{dataset.id}/resources", {"per_page": 20, "sort": "-created"}
            )
            for item in payload["data"]:
                attributes = item.get("attributes", {})
                title = attributes.get("title", "").strip()
                if title.endswith(suffix):
                    found.append(
                        PortalResource(
                            id=str(item["id"]),
                            dataset_id=dataset.id,
                            title=title,
                            created=attributes["created"],
                        )
                    )
        return sorted(found, key=lambda r: r.created, reverse=True)

    def download(self, resource_id: str) -> bytes:
        url = f"https://api.dane.gov.pl/resources/{resource_id}/file"
        try:
            response = self._client.get(url, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortalError(f"cannot download resource {resource_id}: {exc}") from exc
        return response.content
