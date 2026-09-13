#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from bs4 import XMLParsedAsHTMLWarning
import warnings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

load_dotenv(Path(__file__).parent / ".env")

# ── Configuration ────────────────────────────────────────────────────────────

TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DailyWordBot/1.0; "
        "+https://github.com/tabidots/wotd-notify)"
    )
}

CEST_ZONE = ZoneInfo("Europe/Paris")

# ntfy.sh topic to push the daily summary to. Treat this like a shared
# secret -- anyone who knows the topic name can read/publish to it, since
# it's unauthenticated by default. Pick something unguessable.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# Flag emoji shown per language in the push notification, in display order.
LANGUAGE_FLAGS = {
    "English": "🇺🇸",
    "Spanish": "🇪🇸",
    "Portuguese": "🇧🇷",
    "Italian": "🇮🇹",
    "German": "🇩🇪",
    "Swedish": "🇸🇪",
}


@dataclass
class Word:
    language: str
    word: str
    url: str


# ── Date sanity check ─────────────────────────────────────────────────────────

def check_dates() -> None:
    """Ensure the local calendar date matches the CEST calendar date."""
    local_now = datetime.now().astimezone()
    cest_now = datetime.now(CEST_ZONE)

    print(f"Local time: {local_now.isoformat()}")
    print(f"CEST time:  {cest_now.isoformat()}")

    if local_now.date() != cest_now.date():
        raise RuntimeError(
            f"Date mismatch: local={local_now.date()}, "
            f"CEST={cest_now.date()}"
        )

    print("Date sanity check: OK")


# ── HTTP / HTML helpers ───────────────────────────────────────────────────────

def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


CDATA_PATTERN = re.compile(r"^<!\[CDATA\[(.*)\]\]>$", re.DOTALL)
 
 
def strip_cdata(text: str) -> str:
    """Strip a literal <![CDATA[...]]> wrapper if html.parser left it in.
 
    Whether BeautifulSoup's html.parser backend leaves CDATA markers as
    literal text or strips them appears to vary across Python versions,
    so this is applied defensively rather than relying on that behavior.
    """
    match = CDATA_PATTERN.match(text.strip())
    return match.group(1) if match else text


def require_word(language: str, word: str | None, url: str) -> Word:
    word = clean(word or "")

    if not word:
        raise RuntimeError(
            f"{language}: could not find the daily word at {url}"
        )

    return Word(language, word, url)


# ── Site adapters ─────────────────────────────────────────────────────────────

def merriam_webster() -> Word:
    # The main HTML page (merriam-webster.com/word-of-the-day) returned a
    # 403 from the VPS's IP range, likely bot protection on datacenter
    # IPs. Try the official RSS feed instead -- feed endpoints are
    # typically behind lighter (or no) bot protection than the main site.
    url = "https://www.merriam-webster.com/wotd/feed/rss2"
    soup = get_soup(url)
 
    item = soup.find("item")
    if item is None:
        raise RuntimeError("Merriam-Webster RSS feed had no <item> entries")
 
    title_tag = item.find("title")
    word_text = clean(strip_cdata(title_tag.get_text())) if title_tag else None
 
    pub_date_tag = item.find("pubdate")
    if pub_date_tag is not None:
        pub_date = parsedate_to_datetime(clean(pub_date_tag.get_text()))
        eastern = ZoneInfo("America/New_York")
        eastern_today = datetime.now(eastern).date()
 
        if pub_date.astimezone(eastern).date() != eastern_today:
            raise RuntimeError(
                f"Merriam-Webster RSS word is dated "
                f"{pub_date.astimezone(eastern).date()}, "
                f"but today (ET) is {eastern_today}"
            )
 
    return require_word("English", word_text, url)


def rae() -> Word:
    url = "https://dle.rae.es/"
    soup = get_soup(url)

    word = soup.select_one("a.c-word-day__link span")

    return require_word("Spanish", word.get_text() if word else None, url)


def duden() -> Word:
    url = "https://www.duden.de/wort-des-tages"
    soup = get_soup(url)

    # Duden's page has a dedicated Wort des Tages heading.
    heading = soup.find(
        lambda tag: tag.name == "div"
        and "wort des tages" in clean(tag.get_text()).lower()
    )

    word = None
    if heading:
        word = heading.find_next("h2").get_text()

    return require_word("German", word, url)


def treccani() -> Word:
    url = "https://www.treccani.it/"
    soup = get_soup(url)

    heading = soup.find(lambda tag:
        "parola del giorno" in clean(tag.get_text()).lower()
    )

    word = None
    if heading:
        word = heading.find_next("h5").get_text()

    return require_word("Italian", word or None, url)


def priberam() -> Word:
    url = "https://dicionario.priberam.org/DoDiaRSS.aspx"
    soup = get_soup(url)
 
    item = soup.find("item")
    if item is None:
        raise RuntimeError("Priberam RSS feed had no <item> entries")
 
    # html.parser lowercases tag names, so pubDate -> pubdate.
    pub_date_tag = item.find("pubdate")
    pub_date_str = clean(pub_date_tag.get_text()) if pub_date_tag else ""
 
    try:
        pub_date = datetime.strptime(pub_date_str, "%d %b %Y").date()
    except ValueError as exc:
        raise RuntimeError(
            f"Could not parse Priberam pubDate {pub_date_str!r}"
        ) from exc
 
    today = datetime.now(CEST_ZONE).date()
    if pub_date != today:
        raise RuntimeError(
            f"Priberam RSS word is dated {pub_date}, but today is {today}"
        )
 
    # <description> holds HTML, escaped inside the RSS XML -- parse it
    # a second time to get at the actual word spans.
    description_tag = item.find("description")
    description_html = description_tag.get_text() if description_tag else ""
    entry_soup = BeautifulSoup(description_html, "html.parser")
 
    # Prefer the Brazilian Portuguese spelling (varpb) when the header
    # gives one; European Portuguese (varpt) is the fallback, then
    # whatever the RSS <title> says.
    word = entry_soup.select_one(".dp-definicao-header span.varpb")
    if word is None:
        word = entry_soup.select_one(".dp-definicao-header span.varpt")
 
    word_text = word.get_text(strip=True) if word else None
 
    if not word_text:
        title_tag = item.find("title")
        word_text = title_tag.get_text(strip=True) if title_tag else None
 
    return require_word("Portuguese", word_text, url)


def sao() -> Word:
    url = "https://svenska.se/"
    soup = get_soup(url)

    script = soup.select_one("#__NUXT_DATA__")
    if not script or not script.string:
        raise RuntimeError("Could not find __NUXT_DATA__")

    data = json.loads(script.string)

    # Root → data → ShallowReactive → actual data object
    root = data[1]
    data_obj = data[data[root["data"]][1]]

    # Daily word object
    dagens_ord = data[data_obj["dagens-ord"]]

    # Resolve the word
    entry = data[dagens_ord["entry"]]
    word = data[entry["ortografi"]]

    # Resolve the day number
    day_of_year = data[dagens_ord["day_of_year"]]

    # Sanity-check that we're getting today's entry
    today = datetime.now(ZoneInfo("Europe/Paris")).timetuple().tm_yday

    if day_of_year != today:
        raise RuntimeError(
            f"SAO word is for day {day_of_year}, but today is day {today}"
        )

    return require_word("Swedish", word, url)


# ── Notification ──────────────────────────────────────────────────────────────

def format_message(results: list[Word]) -> str:
    """Build the one-line 'flag word' summary, in LANGUAGE_FLAGS order."""
    by_language = {r.language: r.word for r in results}

    parts = [
        f"{flag} {by_language[lang]}"
        for lang, flag in LANGUAGE_FLAGS.items()
        if lang in by_language
    ]

    return "  ".join(parts)


def send_notification(message: str, *, title: str = "Words of the Day") -> None:
    response = requests.post(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            # ntfy defaults to Latin-1 for headers; force UTF-8 for
            # non-ASCII text you put in headers (not needed for the flags,
            # since those live in the body, but harmless to set).
            "Content-Type": "text/plain; charset=utf-8",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # check_dates()

    fetchers = [
        merriam_webster,
        rae,
        duden,
        treccani,
        priberam,
        sao,
    ]

    results: list[Word] = []
    failures: list[str] = []

    for fetch in fetchers:
        try:
            result = fetch()
            print(f"{result.language:12} {result.word}")
            results.append(result)
        except Exception as exc:
            print(f"{fetch.__name__:12} ERROR: {exc}", file=sys.stderr)
            failures.append(f"{fetch.__name__}: {exc}")

    if not results:
        print("All fetchers failed, nothing to send.", file=sys.stderr)
        sys.exit(1)

    message = format_message(results)
    print(f"\nNotification text:\n{message}")

    send_notification(message)

    if failures:
        # Still exit non-zero so cron mails you / your log shows a problem,
        # even though a (partial) notification went out.
        print(f"\n{len(failures)} site(s) failed:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()