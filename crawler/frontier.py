"""File-backed FIFO frontier (breadth-first crawl order).

State lives in an append-only TSV, nothing is ever deleted: after a crash or
Ctrl+C the crawl resumes from `discovered - already fetched`.
"""

import os
from collections import deque


class Frontier:
    def __init__(self, discovered_path, fetched_urls):
        self._path = discovered_path
        self._seen = set()
        self._queue = deque()
        ends_with_newline = True
        if os.path.exists(discovered_path):
            with open(discovered_path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    ends_with_newline = line.endswith("\n")
                    try:
                        url, depth, referrer = line.rstrip("\n").split("\t")
                        depth = int(depth)
                    except ValueError:
                        # A kill mid-write leaves a cut last line; skip it, the URL is found again from its source.
                        print("discovered.tsv line {} is malformed, skipped: {!r}".format(number, line[:200]))
                        continue
                    self._seen.add(url)
                    if url not in fetched_urls:
                        self._queue.append((url, depth, referrer))
        os.makedirs(os.path.dirname(discovered_path), exist_ok=True)
        self._handle = open(discovered_path, "a", encoding="utf-8")
        if not ends_with_newline:
            # Never glue the next URL onto a cut line.
            self._handle.write("\n")
            self._handle.flush()

    def add(self, url, depth, referrer):
        """Queue a URL unless it was already discovered. Returns True when added."""
        if url in self._seen:
            return False
        self._seen.add(url)
        self._queue.append((url, depth, referrer))
        self._handle.write("{}\t{}\t{}\n".format(url, depth, referrer))
        # Flush every line: a kill must not lose discovered URLs still in the buffer.
        self._handle.flush()
        return True

    def pop(self):
        return self._queue.popleft() if self._queue else None

    def __contains__(self, url):
        """True when the URL was ever discovered (queued or already fetched)."""
        return url in self._seen

    def __len__(self):
        return len(self._queue)

    @property
    def discovered_count(self):
        return len(self._seen)

    def close(self):
        self._handle.close()
