# agent-screen-control

ydotool input wrapper + Qwen2-VL screenshot bridge for screen control
(design.md D4, tasks 4.7/4.8). A pure-Python library under
`/usr/lib/aipc-agent/aipc_agent_screen_control/`, same shape as
`agent-tools-files` — no daemon of its own, nothing to `systemctl enable`.
The session-gate/always-on mode switch and its CLI (`aipc agent screen
--mode ...`) are task 5.3, not this module; this module only ever *asks*
the gate whether an action is currently allowed and refuses if not.

## Current status: enabled — full hardware pass 2026-07-11

Every action (mouse move/click, key type/press, screenshot+VLM describe)
calls `gate.check_action()` first, which enforces two independent
fail-closed checks before anything real happens:
1. `aipc-agent-gate` grants the `screen-control` action right now.
2. The active window's class is not on the blacklist — and if the class
   can't even be determined, that also counts as blacklisted (unknown is
   never treated as safe).

The two reasons this module stayed `.disabled` are both resolved and the
whole chain is hardware-verified end-to-end (see Verification tiers):
- **`kdotool` window-class detection** is installed and verified live —
  `getactivewindow` + `getwindowclassname` correctly returns
  `org.kde.konsole` for a focused terminal, so the blacklist actually
  fires instead of only failing closed on unknown.
- **Vision model exists**: `vlm-screen` (Qwen2.5-VL-7B) is registered in
  LiteLLM; a real screenshot POSTed through the bridge returned a correct
  desktop description. `vlm.py`'s default is already `vlm-screen`.
- Full chain verified in one pass: no-grant → `GateDenied`; grant →
  konsole blacklisted → `BlacklistedWindow`; grant + empty blacklist →
  real `ydotool` pointer move; screenshot → `vlm-screen` description;
  revoke → `GateDenied` again.

Assistant callers reach this through the Daily Assistant tools
`screen_click` / `screen_type` / `screen_key` (read-only look is
`screen_describe`). A grant is still required first
(`aipc agent screen --grant-session <seconds>`); the tools return
`needs_permission` rather than acting when no grant is active.

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
| VLM bridge actual vision response | **Hardware-verified 2026-07-11** | `vlm-screen` (Qwen2.5-VL-7B) registered; real screenshot returned a correct desktop description |
| `aipc-agent-gate` check RPC (deny path) | **Hardware-verified** | `check_gate()` False with no grant active, against the real live socket |
| `aipc-agent-gate` check RPC (allow path) | **Hardware-verified** | Granted a real 60s session `screen-control` grant, `check_gate()` True, revoked immediately, confirmed False again after |
| Blacklist fail-closed (unknown window class) | **Hardware-verified** | With a real grant active, `input.mouse_move()` still raised `BlacklistedWindow`, not `GateDenied` — proves the second gate layer independently blocks when `kdotool` can't resolve a class |
| `kdotool` window-class detection itself | **Hardware-verified 2026-07-11** | Installed via `rpm-ostree`-staged layer (live-extracted binary this pass); `getactivewindow` + `getwindowclassname` returned `org.kde.konsole` for a focused terminal |
| Real input injection (`ydotool` moving a real pointer/typing into a real window) | **Hardware-verified 2026-07-11** | With a real grant + empty blacklist, `input.mouse_move(5, 5)` shelled out to `ydotool` and moved the real pointer, exit 0 |
| Fail-closed self-tests (`input.py`/`vlm.py` `--self-test`) | **Hardware-verified** | Ran against the real live gate with no active grant; both raised the expected exception before touching `ydotool`/`spectacle`/network |
| `ydotool.service` override syntax + manual restart | **Hardware-verified 2026-07-11** | `daemon-reload` + `systemctl restart ydotool.service` → active; `ydotool mousemove 0 0` as uid 1000 → exit 0 |
| `ydotool.service` boot-time race actually eliminated | **Reboot-pending** | Dependency ordering (`After=`/`Requires=user-runtime-dir@1000.service`) is correct systemd syntax and matches the diagnosed failure mode, but only a real reboot proves the race is gone — this session could not reboot without dropping the task |

## ydotool.service — boot-time race fix (phase-4-agent#4.7)
`input.py` needs `ydotoold` reachable at an unprivileged, uid-1000-owned
socket (`ydotool` shells out as the logged-in user, not root). The
upstream `ydotool` package's base unit is `ExecStart=/usr/bin/ydotoold`
with no args — root-only default socket, disabled by Fedora's preset.

Diagnosed live on 2026-07-11: a hand-applied `/etc/systemd/system/
ydotool.service.d/override.conf` (not previously in the repo) pointed
`ydotoold` at `/run/user/1000/.ydotool_socket`, but the unit
(`WantedBy=default.target`) had no ordering against
`user-runtime-dir@1000.service`, the unit that actually creates
`/run/user/1000`. Early in boot, `ydotoold` sometimes starts before that
directory exists, fails to bind the socket, and — because `Restart=always`
hits its start-limit burst faster than the directory shows up — ends up
`failed` (status=2) until someone runs `systemctl restart ydotool` by hand
(which always works once `/run/user/1000` exists).

**Fix chosen: option (a), a repo-tracked drop-in with an explicit
`After=`/`Requires=user-runtime-dir@1000.service`** —
`files/etc/systemd/system/ydotool.service.d/override.conf` — over rewriting
`ydotool.service` as a systemd `--user` unit. Reasons:
- The socket-own design is already single-uid (`socket-own=1000:1000`,
  matching the AI PC's single-user assumption, CLAUDE.md §6); a `--user`
  unit would add per-session lifecycle (start/stop on login/logout,
  lingering requirements) for no behavioral gain over a system unit that's
  simply ordered correctly.
- `Requires=` (not just `After=`) makes systemd actually pull
  `user-runtime-dir@1000.service` in as a dependency rather than only
  hoping it's already up — this is the actual root-cause fix, not a
  restart-count band-aid.
- Smallest diff: one drop-in file, no unit-type rewrite, no change to
  `input.py`'s socket path assumption.

`post-install.sh` now does `systemctl enable ydotool.service` (symlink
write only, no `--now`) so a fresh image ships the unit enabled instead of
relying on someone enabling it by hand on the live box, as had happened
here.

**Verification**: `systemctl daemon-reload` + `systemctl restart
ydotool.service` → `active (running)`; `ydotool mousemove 0 0` as uid 1000
→ exit 0 (hardware-verified, 2026-07-11). The boot-time race itself is
only provable by a real reboot — this session cannot reboot without
dropping the task, so **the dependency ordering is syntax/behavior-checked
live via manual restart, but elimination of the boot race is
reboot-pending** or the unit config verified across a `bootc switch` +
reboot cycle (CLAUDE.md §9 hardware-verified tier for the boot-order claim
specifically).

## Dependencies
- ai-rocm (intended VLM inference backend once a vision model exists)
- llm-litellm
- agent-gate (`aipc-agent-gate.sock`, phase-4-agent#5.1 — RPC contract above)

## Spec
openspec/changes/phase-4-agent — tasks 4.7, 4.8 (this module's logic);
task 1.4 scaffolded the module shell.
