# Why

Hugging Face has migrated large-file storage to **Xet** (chunked, content-
addressed CAS). For a Xet-backed repo, the `resolve` URL 302s to a
`xet-bridge` endpoint and only the `hf_xet` client can reconstruct the file
correctly. Two independent problems follow, both hit live 2026-07-13 while
swapping `coder-agentic` to `SC117/Qwen3.6-35B-A3B-...-Native-MTP-Preserved-
APEX-GGUF` (commit ce8a830):

1. **Naive HTTP fetches wrong bytes.** `curl -L` and Lemonade's own
   downloader (the `.download_manifest.json` fetcher behind `lemonade pull`)
   both pull a stream that is Content-Length-correct and GGUF-magic-valid but
   whose content hashes to `d4f7590f…`, not the file's advertised LFS etag
   `782636c4…`. The bytes are consistent across retries, so it is not
   corruption — it is the wrong transfer protocol against the Xet bridge. The
   authentic content (verified by the `hf_xet` client's own chunk-hash
   reconstruction, and by the file loading + benchmarking correctly) is
   `d4f7590f…`; the `782636c4…` etag is stale upstream metadata the Xet
   migration left behind.

2. **`lemonade pull` cannot converge.** Because it verifies the downloaded
   file against that stale etag, it deletes and re-downloads forever (observed
   partial thrashing 24→0.93→3.22 GiB earlier). So `aipc models sync`, which
   drives `lemonade pull` from a manifest entry's `checkpoints`, cannot
   provision this model at all.

The swap shipped by working around this **live**: download via the `hf`
client, then reproduce the completed HF cache layout Lemonade recognises
(`blobs/<etag>` + `snapshots/<commit>/<file>` symlink + `refs/main`, and
crucially **no** `.download_manifest.json`, whose presence marks the download
"in progress" and makes Lemonade hand llama-server the repo directory instead
of the gguf → "No such file"). That hand-work is **not reproducible**: a fresh
bootc rebuild re-provisions weights at runtime via `aipc models sync`, which
would loop on this model and leave `coder-agentic` unbacked.

This change makes Xet-migrated models provisionable by the normal sync path.
