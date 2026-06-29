## Context

The AI PC needs two complementary kinds of recall: (1) **memory** —
across-session facts about the user (preferences, ongoing projects,
people, recurring intents); (2) **RAG** — fresh retrieval over the
user's actual files, code, browsing history, and (optionally) what
they see and hear on the screen. Memory is the high-precision,
small-volume side; RAG is the high-recall, large-volume side. mem0
covers (1); a bge-m3-indexed Postgres covers (2).

Vectors live in pgvector. Under the expected workload (~100k–500k
vectors total: documents + code chunks + browser snippets + screen
OCR), pgvector is comfortable. Qdrant is the documented upgrade
target when the corpus crosses ~1M vectors or when filtered ANN
queries get slow; until then, shipping it as enabled-by-default
doubles the backup surface and the maintenance footprint with no
user-visible win.

Privacy is non-optional: the data plane is local. The embedder runs
on the iGPU via Lemonade, vectors stay in local Postgres, mem0
stores everything in the same database. The only network egress in
the memory + RAG path is SearXHG's outbound queries from Phase 4,
which is not part of this change.

## Goals / Non-Goals

**Goals:**

- Across-session memory works on first boot once mem0 has anything
  to remember (the wizard primes nothing; mem0 learns from usage).
- The user's Desktop, code repos, browser, and optionally screen +
  audio are indexed and queryable through `aipc rag` within minutes
  of completing firstboot.
- A swap from pgvector to Qdrant is a documented `aipc db migrate
  qdrant` command, not a redesign.
- Zero source-content leaks: no embedder cloud calls, no telemetry
  beyond what the user explicitly opts into (none, in this phase).
- Browser history and screen+audio capture are gated by explicit
  consent. The user can disable, retain-with-TTL, or purge at any
  time.

**Non-Goals:**

- A second specialised vector store (LanceDB, ChromaDB, Weaviate)
  alongside pgvector. One backend; Qdrant is the only upgrade
  target.
- A custom memory framework. mem0 is the chosen abstraction; a
  framework swap is its own change.
- Cross-machine memory sync. Each AI PC owns its own memory; sync is
  a v2 cloud-optional feature.
- Email and calendar ingest as RAG sources. Phase 4 wires email and
  calendar as agent tools (real-time queries); RAG-ing them is
  follow-up work after the four core sources land.
- Live reranker as a separate quadlet. The reranker runs as part of
  the same `rag-embedder` service to share the model cache.

## Decisions

**D1 — pgvector primary, Qdrant opt-in**

*Chosen:* `db-postgres` ships enabled with the `pgvector` extension
loaded. `db-qdrant` ships `.disabled`; `aipc db migrate qdrant` is
the documented path to enable it.

*Alternatives:*
- Qdrant-only: Postgres is still needed for mem0's relational
  metadata; running it without vector duty saves nothing.
- Both by default: per the architecture text, but ops cost
  (backups, snapshots, monitoring) doubles. Postpone until corpus
  size warrants.
- LanceDB / ChromaDB: simpler embedded options, but their
  throughput caps around ~100k–500k vectors; pgvector handles the
  same range and gives SQL joins to mem0 metadata.

*Why chosen:* Under expected corpus size pgvector is enough. SQL
joins are useful for mem0. One backend = one backup, one snapshot,
one place to do RLS / access control later. Migration to Qdrant is
a tooling problem, not a redesign.

**D2 — mem0 as the memory framework**

*Chosen:* `memory-mem0` ships the mem0 server pointed at Postgres,
exposing the mem0 HTTP API for the Phase 4 agents and CLI.

*Alternatives:*
- Letta: heavier, hierarchical memory abstractions; useful but
  more surface than needed for v1.
- Cognee: combines KG + vector + ECL; powerful but complex to
  operate.
- Hand-rolled: simple at first, hits limits fast (deduplication,
  forgetting policies, fact-merge across sessions).

*Why chosen:* Most mature lightweight option; integrates with
LiteLLM out of the box; matches the Phase 4 agent-tool pattern (the
agent calls mem0's REST API).

**D3 — RAG ingest: four sources, all default-on (browser + screen
gated by consent)**

*Chosen:* `rag-ingest` ships four watchers:
1. Desktop documents (`~/Desktop`, `~/Documents`).
2. Local code repos (configured via `~/.config/aipc/rag/repos.yaml`,
   default empty).
3. Browser history + bookmarks (Firefox places.sqlite + Chrome
   History db).
4. Screen OCR + audio transcript (region-selector, TTL'd).

Desktop and code watchers run by default. Browser and screen+audio
require firstboot consent.

*Alternatives:*
- Opt-in per source: better privacy, worse first impression — a
  fresh AI PC should index Desktop without ceremony.
- Skip browser: kills "what did I read last week", a key use case.
- Skip screen+audio: kills the richest passive signal.

*Why chosen:* Privacy is enforced at the source-class level, not
the per-file level: Desktop / code are user-owned and explicit;
browser is gated per-browser; screen+audio is strict opt-in with TTL
and purge.

**D4 — Embedder: bge-m3 + bge-reranker-v2-m3, served together**

*Chosen:* `rag-embedder` is a single HTTP service hosting both
models, exposed through LiteLLM's `embed-bge` alias for embeddings
and a `/rerank` endpoint for reranking.

*Alternatives:*
- Qwen3-Embedding: newer model, but the reranker ecosystem around it
  is thinner.
- bge-m3 without reranker: simpler, but accepts a precision floor.
- Cohere rerank cloud: privacy regression; out by D5.
- Two separate services: doubles model-cache memory; one process
  with both models loaded is cheaper.

*Why chosen:* Best multilingual quality available locally today;
same team for both models; both run on Lemonade ONNX.

**D5 — All RAG data plane is local-only**

*Chosen:* The embedder, the vectors, and mem0's storage all live
on the box. No embedding API or reranker API leaves the host.
SearXHG (Phase 4) is the only outbound-network component in the
broader retrieval surface, and it isn't part of this change.

*Alternatives:*
- Cloud embedder (Voyage, Cohere, OpenAI): cheaper compute, but
  ships every indexed line of code and every browsed URL to a third
  party. Out.

*Why chosen:* CLAUDE.md §5's secrets stance generalises to "user
data doesn't leave the box without explicit opt-in." This is the
implementation.

**D6 — Browser capture: per-browser opt-in at firstboot**

*Chosen:* Firstboot wizard asks per browser ("Index Firefox history?
Index Chrome history?"). Each consent independently enables a
watcher on the corresponding database file. Consent revocation
stops the watcher and (with explicit `--purge`) drops the vectors.

*Alternatives:*
- Auto-enroll all browsers: creepy first-boot moment.
- No browser support: lose a core use case.

*Why chosen:* Browser data is among the most sensitive user data;
explicit per-browser consent is the right default.

**D7 — Screen OCR + audio transcript: strict opt-in with region
selector and TTL**

*Chosen:* Disabled until the user opts in. When enabled, the user
picks which monitor(s) / app(s) / windows are eligible (region
selector), and the captured chunks carry a TTL (default 7 days,
configurable). One keystroke (`aipc rag purge screen-audio`)
deletes everything in this source.

*Alternatives:*
- Always-on: privacy nightmare even with local processing.
- Never ship: lose the richest passive signal.

*Why chosen:* Opt-in protects the user; TTL bounds the exposure
window; one-shot purge is the panic button.

## Risks / Trade-offs

- **pgvector scale ceiling**: at ~1M+ vectors with filtered ANN
  queries, pgvector slows. **Mitigation**: `aipc db migrate qdrant`
  is the documented escape; `aipc doctor` warns when the vector
  count crosses a configurable threshold.
- **mem0 maturity**: mem0 is younger than RAG infra; APIs may shift.
  **Mitigation**: pin the mem0 version in `memory-mem0/packages.txt`;
  upgrade as its own change.
- **Browser DB locking**: Firefox places.sqlite locks during writes;
  the watcher must copy + read, not read live. **Mitigation**: the
  watcher polls a snapshot copy at a configurable interval (default
  5 minutes); documented in `rag-ingest` README.
- **Screen OCR cost**: continuous OCR is expensive even on iGPU.
  **Mitigation**: capture rate is throttled (e.g., one frame per N
  seconds) and gated by user-selected region; the user sees the
  current cost in `aipc rag status`.
- **Audio transcript privacy**: passive transcription of ambient
  audio is the highest-risk source. **Mitigation**: opt-in only,
  separate consent screen, TTL, and the same `aipc-voice-mute.target`
  (Phase 3 D7) pauses capture during screen-lock / DND / voice-mute.

## Migration Plan

No prior memory / RAG surface exists on this image. Phase 2 is
net-new. The two ordering concerns are:

1. Phase 1 must be deployed before Phase 2 so the `embed-bge`
   LiteLLM alias is live.
2. Phase 7 owns the firstboot wizard runner; Phase 2 contributes
   the consent prompts. If Phase 7 lands later, the consent prompts
   default to "off" and can be turned on later via `aipc rag
   enable <source>`.

The pgvector-to-Qdrant migration is documented under D1: when the
user runs `aipc db migrate qdrant`, a one-shot job dumps the
pgvector data, brings up `db-qdrant`, re-indexes, and flips
`rag-embedder` to point at Qdrant. The migration is reversible by
re-running the inverse command; both databases can coexist during
cutover.

## Open Questions

- **Q1 — Browser support beyond Firefox and Chrome**: Brave, Arc,
  and Vivaldi all share Chrome's schema; LibreWolf shares Firefox's.
  Probably worth a registry-driven approach later, but v1 ships
  Firefox + Chrome only.
- **Q2 — Audio transcript pipeline**: should it share Phase 3's
  `voice-stt-paraformer` streaming service or run its own? Sharing
  is simpler (one Paraformer instance) but couples Phase 2's
  audio source to Phase 3 being installed and active. Suggested
  default: share Paraformer; if Phase 3 isn't deployed, the
  audio-transcript source stays disabled with a clear status
  message.
- **Q3 — Code-repo chunking strategy**: whole-file (simple, large
  chunks), line-window (fast, no structure), tree-sitter AST
  (best for code search, requires per-language parsers). v1 ships
  line-window; tree-sitter is a v2 follow-up once the cost / value
  is measured against real corpora.
