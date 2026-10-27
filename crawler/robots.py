"""robots.txt handling on top of the standard library parser.

Status handling follows RFC 9309 (section 2.3.1): a missing robots.txt (4xx)
means no rules, an unreachable one (5xx, network error) means stay out. 429
is treated like 5xx because the site is already rate-limiting us.
"""

from urllib.robotparser import RobotFileParser

import requests


class RobotsRules:
    """Wraps RobotFileParser so the file is fetched with our own session/headers."""

    def __init__(self, session, base_url, user_agent, timeout):
        self.url = base_url.rstrip("/") + "/robots.txt"
        self._user_agent = user_agent
        self._parser = RobotFileParser()
        self.response = None
        self.status = None      # HTTP status, or the exception name of a network error
        self.body = b""         # robots.txt exactly as received, when rules were parsed
        self.challenge = False  # an HTML (anti-bot) page was served instead of robots.txt
        self.problem = ""       # why the whole site is disallowed for this run
        try:
            response = session.get(self.url, timeout=timeout)
        except requests.RequestException as exc:
            self.status = type(exc).__name__
            self._disallow_all("robots.txt unreachable ({})".format(self.status))
            return
        self.response = response
        self.status = response.status_code
        if response.status_code == 429 or response.status_code >= 500:
            self._disallow_all("robots.txt unavailable (HTTP {})".format(response.status_code))
        elif response.status_code >= 400:
            # No robots.txt (e.g. 404, also 401/403 per RFC 9309): no restrictions.
            self._parser.allow_all = True
        elif "<html" in response.text[:2000].lower():
            # HTML instead of robots.txt (e.g. an anti-bot challenge): the rules are unknown, so stay out.
            self.challenge = True
            self._disallow_all("HTML page instead of robots.txt (anti-bot challenge?)")
        else:
            self.body = response.content
            self._parser.parse(response.text.splitlines())

    def _disallow_all(self, reason):
        self.problem = reason + ", RFC 9309: whole site disallowed for this run"
        self._parser.disallow_all = True

    def allowed(self, url):
        return self._parser.can_fetch(self._user_agent, url)

    def crawl_delay(self):
        delay = self._parser.crawl_delay(self._user_agent)
        return float(delay) if delay else 0.0
