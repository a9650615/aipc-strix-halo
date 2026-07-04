# phase-1-ai-runtime

AI runtime: ROCm + XDNA driver + Lemonade (NPU + iGPU via llamacpp:vulkan) + LiteLLM gateway + vLLM on-demand + models manifest

Superseded 2026-07-05: iGPU main inference moved from Ollama to Lemonade's
`llamacpp:vulkan` backend (see `design.md` D3, `specs/ai-runtime/spec.md`).
`llm-ollama` stays installed but idle.
