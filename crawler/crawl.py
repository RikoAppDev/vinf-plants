"""Polite single-host crawler.

Usage:
    python -m crawler.crawl --site ncsu --max-pages 600
    python -m crawler.crawl --site ncsu                  # continue until the frontier is empty
    python -m crawler.crawl --site pfaf --reseed         # also queue sitemap URLs that are new
"""

import argparse
import random
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from . import config
from .frontier import Frontier
from .links import extract_links, extract_sitemap_urls
from .robots import RobotsRules
from .storage import Storage

TIMEOUT = (config.CONNECT_TIMEOUT_S, config.READ_TIMEOUT_S)
RETRIABLE_STATUSES = {429, 500, 502, 503, 504}
# 503 counts as a block too: many servers rate-limit with 503 instead of 429.
BLOCKED_STATUSES = {403, 429, 503}


class CrawlStopped(Exception):
    """The site does not let us in (challenge page, robots.txt unavailable)."""


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def retry_wait_seconds(response, attempt):
    """Retry-After (seconds or HTTP date) if sent, else exponential backoff; at most MAX_RETRY_AFTER_S."""
    wait = config.BACKOFF_BASE_S * (2 ** (attempt - 1))
    retry_after = response.headers.get("Retry-After", "").strip() if response is not None else ""
    if retry_after.isdigit():
        wait = float(retry_after)
    elif retry_after:
        try:
            wait = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            pass  # unparsable header: keep the backoff
    return min(max(wait, 0.0), config.MAX_RETRY_AFTER_S)


def fetch(session, url):
    """GET with retries. Returns (response or None, attempts, error text)."""
    error = ""
    response = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=TIMEOUT)
            if response.status_code not in RETRIABLE_STATUSES:
                return response, attempt, ""
            error = "HTTP {}".format(response.status_code)
        except requests.RequestException as exc:
            response = None
            error = type(exc).__name__
        if attempt < config.MAX_RETRIES:
            wait = retry_wait_seconds(response, attempt)
            print("{} for {}, retry in {:.0f}s".format(error, url, wait), flush=True)
            time.sleep(wait)
    return response, config.MAX_RETRIES, error


def canonicalize(site, url):
    for pattern, replacement in site.canonical:
        url = re.sub(pattern, replacement, url)
    return url


def is_challenge(response):
    head = response.text[:4000] if "html" in response.headers.get("Content-Type", "") else ""
    return any(marker in head for marker in config.CHALLENGE_MARKERS)


def is_sitemap(body):
    return b"<urlset" in body or b"<sitemapindex" in body


def seed_frontier(session, site, allow, frontier, storage):
    """Fill the frontier from sitemaps and seeds (first run or --reseed); known URLs are skipped."""
    for sitemap_url in site.sitemaps:
        response, attempts, error = fetch(session, sitemap_url)
        if response is not None and (is_challenge(response) or
                                     response.status_code == 200 and not is_sitemap(response.content)):
            # A block page (often served with 200) must not be stored as the
            # sitemap, and an empty seed list must not look like a finished crawl.
            storage.log(fetched_at_utc=utc_now(), url=sitemap_url, final_url=response.url, status="challenge",
                        content_type=response.headers.get("Content-Type", ""), bytes=len(response.content),
                        attempts=attempts, depth=0, error="anti-bot challenge or non-sitemap page")
            raise CrawlStopped("anti-bot challenge (or other non-sitemap page) instead of {}".format(sitemap_url))
        if response is None or response.status_code != 200:
            print("sitemap failed: {} ({})".format(sitemap_url, error or response.status_code))
            continue
        # The sitemap is crawled data too: stored and logged like a page (a re-seed keeps the first copy).
        file_name, digest = storage.save_page(sitemap_url, response.content, keep_previous=True)
        storage.log(fetched_at_utc=utc_now(), url=sitemap_url, final_url=response.url,
                    status=response.status_code, content_type=response.headers.get("Content-Type", ""),
                    bytes=len(response.content), sha256=digest,
                    elapsed_ms=int(response.elapsed.total_seconds() * 1000), attempts=attempts,
                    depth=0, referrer="", file=file_name, error="")
        urls = (canonicalize(site, url) for url in extract_sitemap_urls(response.text))
        added = sum(frontier.add(url, 1, sitemap_url) for url in urls if allow.match(url))
        print("sitemap {}: {} new URLs queued".format(sitemap_url, added))
    for seed in site.seeds:
        frontier.add(seed, 0, "")


def log_robots(storage, robots):
    """robots.txt is a request too: log it and keep a copy of the rules in force."""
    row = dict(fetched_at_utc=utc_now(), url=robots.url, attempts=1, depth=0, error=robots.problem)
    if robots.response is not None:  # no response = network error, empty status like any page
        response = robots.response
        row.update(final_url=response.url, status="challenge" if robots.challenge else response.status_code,
                   content_type=response.headers.get("Content-Type", ""), bytes=len(response.content),
                   elapsed_ms=int(response.elapsed.total_seconds() * 1000))
    if robots.body:
        storage.save_robots(robots.body)
    storage.log(**row)


def redirect_status(site, allow, robots, frontier, url, depth, response):
    """Log status of a 200 answer redirected away from `url`, or "" when the page is stored normally.

    The target is queued under its own URL (unless known), so the redirected copy is never saved.
    """
    final_url = canonicalize(site, response.url)
    if response.status_code != 200 or final_url == url:
        return ""
    if not allow.match(final_url) or not robots.allowed(final_url):
        return "redirect-outside"
    frontier.add(final_url, depth, url)
    return "redirect-duplicate"


def crawl(site_name, data_dir, max_pages, include_aliases, reseed=False):
    site = config.SITES[site_name]
    allow = site.allow_aliases if include_aliases else site.allow
    session = requests.Session()
    session.headers.update(config.DEFAULT_HEADERS)
    storage = Storage(data_dir, site.name)

    robots = RobotsRules(session, site.base_url, config.ROBOTS_AGENT, TIMEOUT)
    log_robots(storage, robots)
    if robots.problem:
        storage.close()
        print("{}; stopping, nothing else is requested. Run the same command later.".format(robots.problem))
        return
    delay = max(site.delay_s, robots.crawl_delay())
    print("robots.txt status {} -> delay {:.1f}s (+0..{:.1f}s jitter)".format(robots.status, delay, config.JITTER_S))
    print("User-Agent: {}".format(config.USER_AGENT))

    frontier = Frontier(storage.discovered_path, storage.fetched_urls())
    downloaded = 0
    consecutive_blocks = 0
    started = time.monotonic()
    try:
        if frontier.discovered_count == 0 or reseed:
            seed_frontier(session, site, allow, frontier, storage)
            time.sleep(delay)  # the sitemap download was a request too

        while max_pages is None or downloaded < max_pages:
            item = frontier.pop()
            if item is None:
                print("frontier is empty, crawl finished" if frontier.discovered_count
                      else "nothing discovered (no sitemap could be read), nothing to crawl")
                break
            url, depth, referrer = item
            if not allow.match(url):
                continue  # discovered under a wider profile than the current one
            if not robots.allowed(url):
                storage.log(fetched_at_utc=utc_now(), url=url, status="robots", depth=depth,
                            referrer=referrer, error="disallowed by robots.txt")
                continue

            response, attempts, error = fetch(session, url)
            row = dict(fetched_at_utc=utc_now(), url=url, attempts=attempts, depth=depth,
                       referrer=referrer, error=error)
            # Challenge pages also come with 403/503, so every status is checked.
            if response is not None and is_challenge(response):
                row.update(final_url=response.url, status="challenge", error="anti-bot challenge page")
                storage.log(**row)
                raise CrawlStopped("anti-bot challenge page received for {}".format(url))
            if response is not None:
                row.update(final_url=response.url, status=response.status_code,
                           content_type=response.headers.get("Content-Type", ""),
                           bytes=len(response.content),
                           elapsed_ms=int(response.elapsed.total_seconds() * 1000))
                redirect = redirect_status(site, allow, robots, frontier, url, depth, response)
                if redirect:
                    row.update(status=redirect, error="redirected, not stored under this URL")
                elif response.status_code == 200:
                    row["file"], row["sha256"] = storage.save_page(url, response.content)
                    downloaded += 1
                    if site.follow_links and "html" in row["content_type"]:
                        for link in extract_links(response.text, response.url):
                            link = canonicalize(site, link)
                            if allow.match(link):
                                frontier.add(link, depth + 1, url)
            storage.log(**row)

            status = response.status_code if response is not None else None
            # Every attempt counts (retries are requests too), so a rate-limiting server gets only a few more.
            consecutive_blocks = consecutive_blocks + attempts if status in BLOCKED_STATUSES else 0
            if consecutive_blocks >= config.MAX_CONSECUTIVE_BLOCKS:
                print("{} blocked responses in a row, stopping to stay polite".format(consecutive_blocks))
                break
            if status in RETRIABLE_STATUSES:
                # Retries are used up, but the server's Retry-After still holds.
                wait = retry_wait_seconds(response, config.MAX_RETRIES)
                print("HTTP {} after {} attempts, waiting {:.0f}s".format(status, attempts, wait), flush=True)
                time.sleep(wait)

            if downloaded and downloaded % 50 == 0 and status == 200:
                minutes = (time.monotonic() - started) / 60
                print("{} pages saved, {} queued, {:.1f} min".format(downloaded, len(frontier), minutes), flush=True)
            time.sleep(delay + random.uniform(0, config.JITTER_S))
    except CrawlStopped as stop:
        print("{}; stopping without retrying. Run the same command later.".format(stop))
    except KeyboardInterrupt:
        print("interrupted, state is saved; run the same command to resume")
    finally:
        frontier.close()
        storage.close()
    print("done: {} pages saved this run, {} still queued".format(downloaded, len(frontier)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Polite crawler for the VINF plant search project")
    parser.add_argument("--site", required=True, choices=sorted(config.SITES))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--max-pages", type=int, default=None, help="stop after this many saved pages in this run")
    parser.add_argument("--include-aliases", action="store_true", help="also crawl near-duplicate alias pages")
    parser.add_argument("--reseed", action="store_true",
                        help="read the sitemaps again and queue URLs that were not discovered yet")
    args = parser.parse_args(argv)
    crawl(args.site, args.data_dir, args.max_pages, args.include_aliases, args.reseed)


if __name__ == "__main__":
    sys.exit(main())
