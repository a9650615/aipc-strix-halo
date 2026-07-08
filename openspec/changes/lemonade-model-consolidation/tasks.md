# Tasks

## 1. Repoint Lemonade HF cache to the shared root

- [x] 1.1 Edit `modules/llm-lemonade/files/etc/systemd/system/lemonade.service`: HF cache `ExecStartPre` mkdir → `/var/lib/aipc-models/hf`; bind volume → `-v /var/lib/aipc-models/hf:/root/.cache/huggingface:Z`.
- [x] 1.2 Live-deploy via hotfix loop (`sudo cp` → `/etc`, daemon-reload, restart). Backup at `/etc/systemd/system/lemonade.service.bak-pre-hf-repoint`.

## 2. Relocate live weights + drop stale duplicates

- [x] 2.1 Stop Lemonade, move `Ornith-1.0-35B-GGUF` + `gemma-4-26B-A4B-it-GGUF` from old hub into `/var/lib/aipc-models/hf/hub`.
- [x] 2.2 Delete stale duplicates in the old cache (`Qwen3.5-122B-A10B-GGUF`, already moved to Ollama 2026-07-07).

## 3. Verify + document

- [x] 3.1 Hardware-verify: service active, lemond reads relocated models (`Cache built: 4 downloaded`), zero SELinux `container_file_t` denials, `/api/v0/models` responds.
- [x] 3.2 Update `modules/llm-lemonade/README.md` HF mount line.
- [x] 3.3 Commit repo unit + README; log row in `docs/agent-log.md` (commit `5716cbf`).

All tasks complete and hardware-verified on the physical Strix Halo AI PC, 2026-07-09.
