# wotd-notify

A little script that scrapes "Word of the Day" from several dictionaries and pushes them all to your phone as one notification.

Started life as a way to check the daily r/Calligraphy WotD prompt without having to visit six different dictionary sites — most people just do Merriam-Webster (or Real Academia Española if they're doing the Spanish version), so I figured why not grab every major dictionary that actually publishes one.

## Currently pulls from

| Language | Source |
|---|---|
| 🇺🇸 English | Merriam-Webster |
| 🇪🇸 Spanish | RAE (dle.rae.es) |
| 🇧🇷 Portuguese | Priberam |
| 🇮🇹 Italian | Treccani |
| 🇩🇪 German | Duden |
| 🇸🇪 Swedish | Svenska.se (SAO) |

Each site has its own little scraper ("adapter") since they all structure their pages differently. A few of them (Merriam-Webster, Priberam, SAO) also double-check the date on the source so you don't end up with yesterday's word if a site is slow to update.

If a site's fetcher fails (layout change, site down, etc.) the script just skips it, logs the error, and still sends you a notification with whatever it *did* manage to get. It exits with a non-zero code on partial failure so cron/your log will flag it.

## Notifications

Uses [ntfy.sh](https://ntfy.sh) — free, no signup, just pick a topic name and subscribe to it in the ntfy app. Treat your topic name like a password: anyone who knows it can read (or post to) it, since it's unauthenticated by default.

## Setup

1. Clone the repo and install dependencies (this uses [uv](https://github.com/astral-sh/uv), but any Python env manager works):

   ```bash
   git clone https://github.com/tabidots/wotd-notify.git
   cd wotd-notify
   uv sync   # or: pip install requests beautifulsoup4 python-dotenv
   ```

2. Create a `.env` file in the repo root with your ntfy topic:

   ```
   NTFY_TOPIC=your-unguessable-topic-name
   ```

3. Subscribe to that topic in the ntfy app (iOS/Android/web).

4. Run it:

   ```bash
   uv run main.py
   ```

## Automating it

Set up a cron job to run it daily. **8am UTC is the sweet spot** — it's late enough that every scraped site has flipped over to the new calendar day, but early enough that most timezones still have most of their day left to see it (sorry, New Zealand).

```
0 8 * * * cd /root/wotd-notify && /root/.local/bin/uv run main.py >> wotd.log 2>&1
```

(Adjust paths to wherever you've actually cloned it / installed uv.)

## Notes

- Scraping = fragile by nature. If a site redesigns its homepage, the corresponding adapter will probably break until someone patches the selectors.
- PRs adding more languages/dictionaries welcome, if you want to go down this rabbit hole with me.