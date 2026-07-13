## MODIFIED Requirements

### Requirement: ornith-35b Serves the Uncensored AEON Model With Vision

The `ornith-35b` alias SHALL resolve to
`Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-Q4_K_M` (the mrexodia GGUF of the
uncensored AEON fine-tune of `deepreinforce-ai/Ornith-1.0-35B`), served by
Lemonade's llamacpp:vulkan backend with `-np 4 -kvu` at ctx 131072. Vision
SHALL be provided by grafting SC117 APEX's `mmproj-F16.gguf` as the alias's
`mmproj` checkpoint — dimensionally compatible because AEON and APEX share the
same Qwen3.5-35B-A3B base. The repo definition (`models.yaml`,
`litellm/config.yaml`, and the `llm-lemonade` verify/idle references) SHALL
name this model, so an image rebuild reproduces the uncensored+vision state
rather than reverting to the earlier APEX-I-Balanced build.

#### Scenario: ornith-35b answers a vision request

- **WHEN** a client sends an image + text turn to `ornith-35b` through the
  LiteLLM gateway
- **THEN** the AEON model loads with the borrowed mmproj and returns a correct
  description of the image content (OCR text and scene shapes/colors)

#### Scenario: A rebuilt image keeps the uncensored AEON model

- **WHEN** the image is rebuilt and `aipc models sync` runs
- **THEN** the AEON `main` checkpoint and the borrowed SC117 `mmproj` are both
  fetched, and `ornith-35b` resolves to the AEON model — not APEX-I-Balanced

#### Scenario: verify.sh checks the AEON model, not APEX

- **WHEN** `llm-lemonade/verify.sh` runs
- **THEN** it asserts the AEON model is pulled and that its saved
  `recipe_options` carry `-np` and `-kvu`, failing if the old APEX id is what is
  present
