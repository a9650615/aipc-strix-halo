# agent-screen-control

ydotool input wrapper + Qwen2-VL screenshot bridge for screen control
(design.md D4, tasks 4.7/4.8). A pure-Python library under
`/usr/lib/aipc-agent/aipc_agent_screen_control/`, same shape as
`agent-tools-files` — no daemon of its own, nothing to `systemctl enable`.
The session-gate/always-on mode switch and its CLI (`aipc agent screen
--mode ...`) are task 5.3, not this module; this module only ever *asks*
the gate whether an action is currently allowed and refuses if not.

## Current status: implemented, still `.disabled`

Every action (mouse move/click, key type/press, screenshot+VLM describe)
calls `gate.check_action()` first, which enforces two independent
fail-closed checks before anything real happens:
1. `aipc-agent-gate` grants the `screen-control` action right now.
2. The active window's class is not on the blacklist — and if the class
   can't even be determined, that also counts as blacklisted (unknown is
   never treated as safe).

Stays `.disabled` for two reasons, both explained in detail below:
- **No vision-capable model is registered in LiteLLM.** Task 4.8's VLM
  bridge is wired correctly but every real call 400s.
- **`kdotool` (window-class detection) was never hardware-verified.** It's
  declared in `packages.txt` for the real image build but isn't installed
  on this dev host, and couldn't be live-installed to test either (see
  below) — so the blacklist check currently fails closed on *every*
  window, because it can never determine a window's class at all.

## Files
- `files/usr/lib/aipc-agent/aipc_agent_screen_control/`
  - `gate.py` — `check_action()`: the shared gate-RPC + blacklist check
    every other file calls first. `check_gate()`, `is_blacklisted()`.
  - `window.py` — `get_active_window_class()` via `kdotool`.
  - `input.py` — `mouse_move`, `mouse_click`, `key_type`, `key_press`,
    each shelling out to `ydotool` after `gate.check_action()` passes.
  - `vlm.py` — `capture_screenshot()` (`spectacle -b -n -o`) +
    `describe_screen()` (base64 → LiteLLM `vlm-qwen2vl` chat completion →
    parsed text description).
- `files/etc/aipc/agent-gate/screen-blacklist.conf` — the D4 default
  blacklist (plain text, one window class per line, `#` comments), at the
  exact path design.md D4 names. Replaces an earlier scaffold config at
  `/etc/aipc/agent/screen-control.yaml` (removed) that used a different,
  non-spec path and a `mode:` field that belongs to task 5.3's CLI, not
  this module.

## The permission-gate RPC — reconciled against the real module mid-dispatch
This dispatch's brief said to *assume* a contract for `aipc-agent-gate`
(phase-4-agent#5.1) since it "almost certainly" wasn't running yet.
Partway through, a parallel agent's live-hotfix actually brought
`aipc-agent-gate.service` up for real on this machine
(`modules/agent-gate/`, socket at `/run/aipc-agent-gate.sock`). Read its
`server.py` docstring directly and hardware-verified against the live
socket — the assumed contract below is exactly what it implements, no
changes needed:

```
request:  {"cmd": "check", "action": "screen-control"}
response: {"allowed": true|false, "grant_id": <str>|null}
```

Verified live, then cleaned up immediately (no grant left active
afterward):
```
check_gate() before any grant  -> False
grant screen-control, 60s session scope
check_gate()                   -> True
revoke that grant_id
check_gate() after revoke      -> False
```
Also verified: with a real grant active but `kdotool` absent, `input.
mouse_move()` still correctly raises `BlacklistedWindow` (not
`GateDenied`) — the gate layer opens, the blacklist layer (fail-closed on
unknown window class) still blocks it. This is real behavior on this box
today: no input action can succeed until `kdotool` is actually installed.

**`agent-tools-files/tools.py` (phase-4-agent#4.1, landed first) assumed a
different, now-stale contract for the same then-unbuilt gate** — plaintext
`"check <action>\n"` answered with `b"GRANTED"`. That one still needs
updating to the real JSON contract above; this module's does not. Flagging
for the 大哥 rather than editing `agent-tools-files` myself — out of this
dispatch's scope (§0.2.2, only touch the named files).

## kdotool — why it's the right tool and why it's untested here
Wayland has no compositor-agnostic "get the focused window" call. KWin's
own DBus interface (`org.kde.KWin`, checked directly on this session) does
NOT expose it cleanly: `queryWindowInfo()` blocks waiting for an
interactive pointer click (unusable headless), `getWindowInfo(uuid)` needs
a uuid we don't have up front. `kdotool` (Fedora package `kdotool`,
"xdotool-like tool to manipulate windows on KDE Wayland") wraps KWin's own
scripting API to do this properly — the native-platform choice over
hand-rolling a KWin script + journal-scrape.

It is declared in `packages.txt` but is not installed on this dev host,
and a live `sudo dnf install kdotool` was attempted and did not work: this
machine boots a read-only composefs/ostree image (`mount` shows `/` as
`overlay (ro,...)`; `rpm --rebuilddb` fails with "read-only file system"
on `/usr/share/rpm/.rpm.lock`). `dnf install`/`rpm-ostree install` would
be the correct live-hotfix path but that's a real system mutation outside
this dispatch's scope (screenshot/gate/VLM testing, not package installs)
— so `window.py`'s `get_active_window_class()` is **static-only**: syntax-
checked, never actually run against a real `kdotool` binary. Hardware
verification needs a real `bootc switch` + reboot (or a scoped live-hotfix
package install, if the 大哥 wants one) followed by confirming `kdotool
getactivewindow` / `getwindowclassname <id>` actually behave as assumed.

## VLM bridge — `vlm-qwen2vl` does not exist right now
Checked `GET http://127.0.0.1:4000/v1/models` directly: `resident-small,
coder-agentic, ornith-35b, main-cloud, coder-cloud, thinking-cloud,
gpt4o-cloud, gemini-cloud` — no vision model. `modules/llm-models/files/
etc/aipc/models/models.yaml`'s own comment confirms `vlm-qwen2vl` was cut
in the 2026-07-04 trim ("too many resident/on-demand models loaded for no
real benefit"). Confirmed live: `POST /v1/chat/completions` with
`model: vlm-qwen2vl` returns HTTP 400 `Invalid model name passed in
model=vlm-qwen2vl`.

This is a real gap, not a naming mismatch — **no vision-capable model is
registered in LiteLLM at all** right now. `gpt4o-cloud`/`gemini-cloud` are
vision-capable upstream but are cloud aliases gated on secrets (CLAUDE.md
§5); whether their keys are actually decrypted on this box was not
checked here, and picking one would be a model-choice call for the 大哥,
not something to do silently in this dispatch. `vlm.py`'s `VLM_MODEL`
constant stays `"vlm-qwen2vl"`, matching the spec — everything up to the
LiteLLM call (screenshot capture, base64 encode, request body, HTTP POST)
is hardware-verified; only the final model resolution 400s, confirmed with
a real screenshot in a real request against the real gateway.

## Blacklist default set
Per design.md D4/Q4: "suggested set is 1Password, GNOME Keyring, banking
domains, SSH terminals... [Q4] needs hardware verification once the
bazzite-dx image is on the AI PC to confirm what is actually installed and
what window classes they expose" — design.md itself says these are
unverified guesses, not confirmed window-class strings. Shipped as-is with
that caveat inline in the conf file. Two design gaps also documented
there:
- "SSH terminals" is blacklisted as *entire terminal apps* (konsole,
  gnome-terminal, xterm) — window class can't distinguish an SSH session
  from any other shell in the same app. Coarse; remove entries if that's
  too broad for a given workflow.
- "Banking domains inside Zed/VSCode browser preview" (D4) cannot be
  represented at window-class granularity at all — the preview pane
  shares its host IDE's window class. No blacklist entry can implement
  this; it's a documented gap, not an oversight (matches design.md's own
  Risks section on this exact limitation).

## Verification tiers (per piece, not blanket)
| Piece | Tier | Evidence |
|---|---|---|
| `spectacle` screenshot capture | **Hardware-verified** | Ran for real: 1,956,339-byte PNG, valid `\x89PNG` header |
| VLM bridge wire format (b64 encode, POST body, endpoint) | **Hardware-verified** | Real screenshot POSTed to real LiteLLM; got the expected HTTP 400 (model gap, not a code bug) — everything up to model resolution confirmed working |
| VLM bridge actual vision response | **Not verified — cannot be**, no vision model registered (see above) |
| `aipc-agent-gate` check RPC (deny path) | **Hardware-verified** | `check_gate()` False with no grant active, against the real live socket |
| `aipc-agent-gate` check RPC (allow path) | **Hardware-verified** | Granted a real 60s session `screen-control` grant, `check_gate()` True, revoked immediately, confirmed False again after |
| Blacklist fail-closed (unknown window class) | **Hardware-verified** | With a real grant active, `input.mouse_move()` still raised `BlacklistedWindow`, not `GateDenied` — proves the second gate layer independently blocks when `kdotool` can't resolve a class |
| `kdotool` window-class detection itself | **Static-only** | Package not installed on this dev host; live install blocked by read-only ostree `/usr` (see above); syntax-checked only |
| Real input injection (`ydotool` moving a real pointer/typing into a real window) | **Static-only (code read-through)** | Per this dispatch's safety constraint, would require spawning a disposable target window and confirming it's focused via the window-list query — but that query is exactly the untested `kdotool` piece, so targeting couldn't be cleanly confirmed. Skipped rather than fake a hardware-verified claim; `ydotool` itself was already confirmed working in this session's environment setup (`ydotool mousemove 0 0` exits 0) |
| Fail-closed self-tests (`input.py`/`vlm.py` `--self-test`) | **Hardware-verified** | Ran against the real live gate with no active grant; both raised the expected exception before touching `ydotool`/`spectacle`/network |

## Dependencies
- ai-rocm (intended VLM inference backend once a vision model exists)
- llm-litellm
- agent-gate (`aipc-agent-gate.sock`, phase-4-agent#5.1 — RPC contract above)

## Spec
openspec/changes/phase-4-agent — tasks 4.7, 4.8 (this module's logic);
task 1.4 scaffolded the module shell.
