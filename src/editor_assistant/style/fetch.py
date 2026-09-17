"""M2.1B article fetching — GET-only, chernomorie-bg.com only.

Deterministic pacing (1-2s), raw HTML snapshots to git-ignored
var/style_corpus/raw/, extractor via M2.1A parse_article_html.
No POST, no redirects outside the allowed host, no query strings.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from editor_assistant.style.corpus import (
    ArticleRecord,
    FailureRecord,
    article_to_dict,
    find_duplicates,
)
from editor_assistant.style.extract import ArticleParseError, parse_article_html

ALLOWED_HOST = "chernomorie-bg.com"
USER_AGENT = "editor-assistant-m21b-corpus/0.1 (chernomorie pilot; GET-only)"
FETCH_DELAY_SECONDS = (1.0, 2.0)
TIMEOUT_SECONDS = 20


def is_allowed_article_url(url: str) -> bool:
    """Only https://chernomorie-bg.com/post/<slug> pages, no query strings."""
    text = (url or "").strip()
    if not text.startswith(f"https://{ALLOWED_HOST}/post/"):
        return False
    return "?" not in text and "#" not in text


def fetch_article(url: str, *, delay: float | None = None) -> tuple[str | None, str | None]:
    """GET one article page. Returns (html, error). Never raises."""
    if not is_allowed_article_url(url):
        return None, f"disallowed article url: {url}"
    pause = delay if delay is not None else sum(FETCH_DELAY_SECONDS) / 2
    if pause > 0:
        time.sleep(pause)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            final_url = response.geturl() or url
            if not final_url.startswith(f"https://{ALLOWED_HOST}/"):
                return None, f"redirect outside allowed host: {final_url}"
            return response.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}: {url}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _snapshot_path(raw_dir: str | Path, url: str) -> Path:
    from editor_assistant.style.extract import extract_post_id, stable_article_id

    # article_id is canonical-URL-derived -> unique per URL, no post_id overwrites
    article_id = stable_article_id(url, extract_post_id(url))
    return Path(raw_dir) / f"{article_id}.html"


def collect_corpus(
    selected_urls: list[str],
    *,
    raw_dir: str | Path,
    delay: float | None = None,
) -> dict[str, object]:
    """Fetch + extract + persist. Failures quarantined; nothing deleted.

    Raw snapshots land in raw_dir (git-ignored); records + failures go
    to JSONL beside them; duplicate signals recorded, never destroyed.
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    records: list[ArticleRecord] = []
    failures: list[FailureRecord] = []
    from datetime import datetime, timezone

    observed_at = datetime.now(timezone.utc).isoformat()
    for url in selected_urls:
        html, error = fetch_article(url, delay=delay)
        if html is None:
            failures.append(
                FailureRecord(
                    url=url,
                    failure_type="FETCH",
                    failure_detail=error or "unknown fetch error",
                    observed_at=observed_at,
                )
            )
            continue
        snapshot = _snapshot_path(raw_dir, url)
        snapshot.write_text(html, encoding="utf-8")
        try:
            records.append(parse_article_html(html, url=url))
        except ArticleParseError as exc:
            failures.append(
                FailureRecord(
                    url=url,
                    failure_type="MISSING_CONTENT",
                    failure_detail=str(exc),
                    observed_at=observed_at,
                )
            )
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            failures.append(
                FailureRecord(
                    url=url,
                    failure_type="MALFORMED",
                    failure_detail=f"{type(exc).__name__}: {exc}",
                    observed_at=observed_at,
                )
            )
    base = raw_dir.parent
    articles_path = base / "articles.jsonl"
    with articles_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(article_to_dict(record), ensure_ascii=False) + "\n")
    failures_path = base / "failures.jsonl"
    with failures_path.open("w", encoding="utf-8") as fh:
        for failure in failures:
            fh.write(
                json.dumps(
                    {
                        "url": failure.url,
                        "failure_type": failure.failure_type,
                        "failure_detail": failure.failure_detail,
                        "observed_at": failure.observed_at,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    duplicates = find_duplicates(records)
    duplicates_path = base / "duplicates.json"
    duplicates_path.write_text(
        json.dumps(duplicates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "requested": len(selected_urls),
        "fetched": len(records),
        "failed": len(failures),
        "duplicates": duplicates,
        "articles_path": str(articles_path),
        "failures_path": str(failures_path),
        "duplicates_path": str(duplicates_path),
    }
