# web-tool-use

<!-- aipc process teaching skill — generic tool procedure, not domain answers -->

## Purpose

High-level guidance for external fact lookup on this AI PC.
**No titles, cast lists, or site shortcuts are seeded here.**
Site-specific paths accumulate only under the machine skill root after *you* succeed with tools.

## When to use tools

- User asks for live / external facts (product or catalog codes, docs, links, current data).
- Chat-only memory is not enough — open tools instead of inventing.

## Procedure (generic)

1. Prefer **local machine skills** if injected (hosts you already proved on this PC).
2. Use **web_search** and/or open a **search engine** in the browser sandbox
   (DuckDuckGo, Brave, Bing, Google, local SearXNG when available).
3. Open 1–2 **result pages** (any useful site — official or side path).
   `browser_navigate` → `browser_snapshot`.
4. Extract only fields present on the page (title, ids, people, dates, item URL).
5. Reply with those facts plus **at least one non-homepage item URL**.
6. If one path fails (captcha / 403), try another engine or result — do not invent.
7. On success, path-harvest merges proven hosts into the **machine** skill tree
   (`/var/lib/aipc-agent/skills/…`) for next time.

## Do not

- Invent titles, names, or URLs.
- Treat a store or search homepage alone as evidence.
- Write one-shot answers into skills; store **procedures and proven hosts** only.
