# ops-doctor

Unified health-check aggregation: extends `tools/aipc_lib/doctor.py` with
service monitoring, GPU/NPU probes, and cross-module status reporting.

## What it does

- Ships a service catalog at `/etc/aipc/doctor/services.yaml` listing all
  managed services to health-check.
- The actual extension to `doctor.py` is separate work; this module declares
  the spec contract and provides the configuration data.

## Design decisions

- **D2**: `verify.sh` + GPU/NPU probes + services aggregation into a single
  `aipc doctor` output. One command tells you the full system health.

## Notes

- This module's `verify.sh` currently exits 2 (disabled). When enabled, it will
  run GPU/NPU probe checks and validate service catalog entries.
- The `doctor.py` extension is tracked as separate implementation work.

## Dependencies

- `llm-ollama` (ollama service)
- `llm-litellm` (litellm service)
- `data-postgres` (postgres service)
- `data-qdrant` (qdrant service)
- `ai-voice-pipecat` (pipecat service)
- `memory-mem0` (mem0 service)

## Spec cross-ref

- `openspec/changes/phase-7-ops/design.md` §D2
