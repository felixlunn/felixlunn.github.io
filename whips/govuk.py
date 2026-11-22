"""GOV.UK's content and search APIs: the pages statistics are published on, and the files attached to them.

Most government statistics are attachments on a GOV.UK page: either a dataset page that is updated in place
(``attachments``), or a collection listing one page per release (``documents``, then ``attachments`` of the
release wanted). Pages are named by their path (``/government/collections/...``), their public URL, or their
content API URL; all three work everywhere here.
"""

from __future__ import annotations

import requests

from .http import get_json

SITE = "https://www.gov.uk"
CONTENT = SITE + "/api/content"
SEARCH = SITE + "/api/search.json"


def api_url(page: str) -> str:
    """The content API URL for a GOV.UK page path, public URL or content API URL."""
    if page.startswith(CONTENT):
        return page
    if page.startswith(SITE):
        page = page[len(SITE):]
    if not page.startswith("/"):
        raise ValueError(f"Not a GOV.UK page: {page}")
    return CONTENT + page


def content(s: requests.Session, page: str, **kwargs) -> dict:
    """The content API's record for a page."""
    return get_json(s, api_url(page), **kwargs)


def attachments(s: requests.Session, page: str, **kwargs) -> list[dict]:
    """The files attached to a page, in page order (each has "title", "url" and, usually, "filename")."""
    return content(s, page, **kwargs).get("details", {}).get("attachments", [])


def documents(s: requests.Session, collection: str, **kwargs) -> list[dict]:
    """The pages a collection links to (each has "title", "base_path" and "public_updated_at")."""
    return content(s, collection, **kwargs).get("links", {}).get("documents", [])


def search(s: requests.Session, query: str, count: int = 20, **params) -> list[dict]:
    """GOV.UK site search results (each has "title" and "link", the page path)."""
    return get_json(s, SEARCH, params={"q": query, "count": count, **params}).get("results", [])
