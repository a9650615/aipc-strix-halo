## ADDED Requirements

### Requirement: Vector Store Topology — pgvector Primary, Qdrant Opt-In

The `db-postgres` module SHALL ship Postgres 16 with the `pgvector`
extension loaded as the default vector store. The `db-qdrant` module
SHALL ship with its quadlet marked `.disabled`; enabling Qdrant
SHALL require running `aipc db migrate qdrant`. Both modules SHALL
be installable side-by-side but only one SHALL be the active vector
backend at any time, recorded in `/etc/aipc/memory/backend`
(`pgvector` or `qdrant`).

#### Scenario: pgvector is active backend on a fresh image

- **WHEN** the image is freshly deployed
- **THEN** `cat /etc/aipc/memory/backend` prints `pgvector` and
  `psql -d aipc -c '\dx pgvector'` lists the extension as installed

#### Scenario: Qdrant ships disabled

- **WHEN** the image is freshly deployed
- **THEN** the qdrant quadlet file under `modules/db-qdrant/quadlet/`
  is named with the `.disabled` suffix and `systemctl is-enabled
  qdrant.service` returns `not-found` or `disabled`

#### Scenario: Migration command swaps the backend

- **WHEN** `aipc db migrate qdrant` completes successfully
- **THEN** `cat /etc/aipc/memory/backend` prints `qdrant`, the
  qdrant quadlet is enabled, and the embedder configuration points
  at Qdrant

---

### Requirement: mem0 Is The Memory Framework, Backed By pgvector

The `memory-mem0` module SHALL ship the mem0 server as a systemd
service, configured to use the active vector backend declared in
`/etc/aipc/memory/backend`. mem0 SHALL expose its HTTP API on
`http://127.0.0.1:7000` (or the equivalent host-only address). The
agent runtime (Phase 4) and CLI tools SHALL consume mem0 through
this HTTP API; no module SHALL import mem0 in-process.

#### Scenario: mem0 service active and reachable

- **WHEN** the image is freshly deployed
- **THEN** `systemctl is-active aipc-mem0.service` returns `active`
  and `curl http://127.0.0.1:7000/healthz` returns HTTP 200

#### Scenario: mem0 writes land in pgvector

- **WHEN** a memory write is issued to the mem0 API and the active
  backend is `pgvector`
- **THEN** a row appears in the corresponding pgvector-backed
  Postgres table

---

### Requirement: Four RAG Ingest Watchers Ship

The `rag-ingest` module SHALL ship four watchers: Desktop documents
(`~/Desktop` and `~/Documents`), local code repos (declared in
`~/.config/aipc/rag/repos.yaml`), browser history + bookmarks (per
browser), and screen OCR + audio transcript. Desktop and code
watchers SHALL be enabled on a fresh image. Browser and screen+audio
watchers SHALL be disabled until consent is recorded per R6 and R7.
Each watcher SHALL be a separately enable-/disable-able systemd
service.

#### Scenario: Desktop and code watchers active on fresh image

- **WHEN** the image is freshly deployed
- **THEN** `systemctl is-active aipc-rag-desktop.service` and
  `systemctl is-active aipc-rag-code.service` both return `active`

#### Scenario: Browser and screen+audio watchers disabled by default

- **WHEN** the image is freshly deployed and no consent has been
  recorded
- **THEN** `systemctl is-enabled aipc-rag-browser-firefox.service`,
  `aipc-rag-browser-chrome.service`, and
  `aipc-rag-screen-audio.service` each return `disabled`

#### Scenario: Watchers populate the active vector store

- **WHEN** a new file is dropped into `~/Desktop` and the Desktop
  watcher runs its next cycle
- **THEN** at least one new vector row referencing the file's path
  appears in the active vector backend

---

### Requirement: Embedder And Reranker Served As One Service Through LiteLLM

The `rag-embedder` module SHALL ship a single HTTP service hosting
both `bge-m3` (embeddings) and `bge-reranker-v2-m3` (reranking).
Embeddings SHALL be reachable through the Phase 1 LiteLLM gateway's
`embed-bge` alias at `http://127.0.0.1:4000/v1/embeddings`. The
reranker endpoint SHALL be exposed at the service's `/rerank` path.
The service SHALL run on the iGPU via the Lemonade runtime, or fall
back to CPU when the iGPU is unavailable.

#### Scenario: Embedder healthy and LiteLLM alias resolves

- **WHEN** the image is freshly deployed
- **THEN** `curl http://127.0.0.1:8201/healthz` (rag-embedder)
  returns HTTP 200 and `curl -X POST
  http://127.0.0.1:4000/v1/embeddings -d '{"model":"embed-bge",
  "input":"hello"}'` returns a 200 with a non-empty embedding
  vector

#### Scenario: Reranker endpoint responds

- **WHEN** the embedder service is active
- **THEN** `curl -X POST http://127.0.0.1:8201/rerank -d
  '{"query":"x","documents":["a","b"]}'` returns HTTP 200 with
  ranked scores

---

### Requirement: Local-Only Data Plane

No `memory-rag` module SHALL declare a cloud embedding URL, a cloud
reranker URL, or a cloud vector-store URL. The embedder, the
vectors, and mem0 storage SHALL all live on the host. The only
component permitted any outbound network traffic in the broader
retrieval surface is SearXHG (Phase 4), which is outside this
change.

#### Scenario: No cloud URL in any memory-rag module config

- **WHEN** `grep -rE
  '(api\\.openai\\.com|api\\.cohere\\.com|api\\.voyageai\\.com|generativelanguage\\.googleapis\\.com|api\\.anthropic\\.com)'`
  is run against `modules/db-postgres/`, `modules/db-qdrant/`,
  `modules/rag-embedder/`, `modules/rag-ingest/`,
  `modules/memory-mem0/`
- **THEN** the command exits non-zero (no matches found)

#### Scenario: Watcher processes have no network egress

- **WHEN** the Desktop or code watcher runs an indexing cycle with
  network monitoring active
- **THEN** no outbound connections originate from the watcher
  process (embedder calls go to `127.0.0.1` only)

---

### Requirement: Browser Capture Requires Per-Browser Consent

The firstboot wizard SHALL prompt once per supported browser
(Firefox, Chrome) asking whether to index that browser's history
and bookmarks. The user's answer SHALL be recorded in
`/etc/aipc/rag/browser-consent.yaml`. The corresponding watcher
SHALL start only when the file records consent for that browser.
Revoking consent (via `aipc rag disable browser-<name>`) SHALL stop
the watcher; passing `--purge` SHALL additionally drop all vectors
sourced from that browser.

#### Scenario: No browser watcher runs without consent

- **WHEN** the image is freshly deployed and the wizard has not
  recorded consent for either browser
- **THEN** neither `aipc-rag-browser-firefox.service` nor
  `aipc-rag-browser-chrome.service` is active

#### Scenario: Consent enables the corresponding watcher

- **WHEN** the firstboot wizard records `firefox: true` in
  `/etc/aipc/rag/browser-consent.yaml`
- **THEN** `aipc-rag-browser-firefox.service` is enabled and active

#### Scenario: Purge drops sourced vectors

- **WHEN** the user runs `aipc rag disable browser-firefox --purge`
- **THEN** the Firefox watcher stops and the active vector backend
  no longer contains rows tagged with the Firefox source

---

### Requirement: Screen+Audio Capture Strict Opt-In With Region Selector And TTL

The screen OCR + audio transcript watcher SHALL be disabled by
default and SHALL require explicit opt-in via a dedicated firstboot
wizard screen (or `aipc rag enable screen-audio`). Opting in SHALL
require the user to select eligible region(s) (monitor / window /
app allow-list) recorded in `/etc/aipc/rag/screen-audio.yaml`.
Captured chunks SHALL carry a TTL with a default of 7 days,
configurable in the same file. `aipc rag purge screen-audio` SHALL
delete all vectors and OCR / transcript artefacts from this source
in one command. The watcher SHALL pause whenever
`aipc-voice-mute.target` (Phase 3) is active.

#### Scenario: Screen+audio disabled on fresh image

- **WHEN** the image is freshly deployed
- **THEN** `systemctl is-active aipc-rag-screen-audio.service`
  returns `inactive` and `/etc/aipc/rag/screen-audio.yaml` does
  not exist

#### Scenario: Opt-in records region selection and TTL

- **WHEN** the user opts in via the wizard and chooses a monitor
  region and a 14-day TTL
- **THEN** `/etc/aipc/rag/screen-audio.yaml` contains the chosen
  region and `ttl_days: 14`, and the watcher service starts

#### Scenario: Voice-mute target pauses screen+audio capture

- **WHEN** `aipc-voice-mute.target` is active
- **THEN** the screen+audio watcher pauses (no new captures
  ingested) while the target remains active

#### Scenario: One-shot purge removes all sourced data

- **WHEN** `aipc rag purge screen-audio` is run
- **THEN** the watcher stops, all OCR / transcript artefacts under
  the screen+audio data directory are removed, and the active
  vector backend no longer contains rows tagged with this source

---

### Requirement: aipc rag CLI Surface

The `aipc rag` subcommand SHALL provide at minimum the following
verbs: `list-sources` (print all sources and their state),
`status` (per-source last-cycle timestamp, item count, vector
count), `enable <source>` and `disable <source>` (toggle watcher
+ persist consent state), `reindex <source>` (force a full
re-index), and `purge <source>` (drop watcher vectors; require
`--confirm` for irreversible deletes).

#### Scenario: list-sources prints all four canonical sources

- **WHEN** `aipc rag list-sources` is run on a fresh image
- **THEN** the output includes `desktop`, `code`, `browser-firefox`,
  `browser-chrome`, and `screen-audio`, each with its current
  enable/disable state

#### Scenario: status reports per-source vector counts

- **WHEN** `aipc rag status` is run after Desktop and code watchers
  have completed at least one cycle
- **THEN** the output lists each active source with a last-cycle
  timestamp and a vector-count column

#### Scenario: purge requires confirm

- **WHEN** `aipc rag purge desktop` is run without `--confirm`
- **THEN** the command exits non-zero with a message naming the
  required flag and the user-visible side effects
