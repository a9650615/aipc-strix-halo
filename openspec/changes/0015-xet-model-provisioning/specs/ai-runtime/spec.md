## ADDED Requirements

### Requirement: Xet-Migrated Models Are Provisioned Reproducibly, Not By Hand

A `models.yaml` entry MAY declare that its weights must be fetched with the
Hugging Face Xet client (e.g. `provision: hf_xet`). For such an entry
`aipc models sync` SHALL fetch each `checkpoints` file with the `hf`
(`hf_xet`) client — as the primary user and never into a tmpfs path — and
leave the completed HF cache layout Lemonade recognises as downloaded
(`blobs/<etag>`, `snapshots/<commit>/<file>` symlink, `refs/main`, and no
Lemonade `.download_manifest.json`). Sync SHALL NOT run `lemonade pull` for a
flagged entry. Integrity SHALL be established by the Xet client's chunk-hash
reconstruction and a successful model load, NOT by comparing the blob to the
LFS etag, which for these repos is expected to be stale. Entries without the
flag SHALL be pulled exactly as before.

#### Scenario: Xet model provisions without a re-download loop

- **WHEN** `aipc models sync` runs for an entry flagged `provision: hf_xet`
  whose weights are not yet present
- **THEN** the file is fetched via the `hf_xet` client into Lemonade's cache
  in the completed layout, `lemonade pull` is not invoked, Lemonade counts the
  model downloaded, and no `.partial`/re-download loop occurs

#### Scenario: Provisioning is idempotent

- **WHEN** `aipc models sync` runs again and the completed layout for the
  pinned commit already exists
- **THEN** no re-download happens and the entry is reported synced

#### Scenario: Stale LFS etag does not block the model

- **WHEN** the fetched blob's content hash differs from the repo's advertised
  LFS etag (a stale etag from the HF Xet migration)
- **THEN** sync still treats the model as validly provisioned, relying on the
  Xet chunk-hash reconstruction and a successful load rather than the etag
