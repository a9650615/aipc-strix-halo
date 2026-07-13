# Tasks

## 1. Repo reality-sync

- [x] 1.1 `models.yaml`: `ornith-35b` → AEON `model_id`, AEON `main`
  checkpoint, keep borrowed SC117 `mmproj`, add `vision` label; rewrite the
  comment block to the AEON + borrowed-mmproj story.
- [x] 1.2 `litellm/config.yaml`: `ornith-35b` `model` → AEON id; update comment.
- [x] 1.3 `llm-lemonade/verify.sh`: pulled-grep + recipe_options `-np/-kvu` key
  → AEON id.
- [x] 1.4 `llm-lemonade/lemonade-idle-release.py`: self-check fixture `model_id`
  → AEON id.

## 2. Verify

- [x] 2.1 `openspec validate 0018-ornith-aeon-uncensored-vision --strict`.
- [x] 2.2 Render bootc + ansible --check stay in sync.
- [x] 2.3 Hardware: mmproj grafted onto live AEON, vision reads OCR + scene
  correctly via `ornith-35b` (see how.md — done before the change was written).
