---
name: human-webui-interaction
description: >
  Simulates realistic human interaction with web UIs using the Claude-in-Chrome MCP and
  computer-use tools. Use this skill when you need to automate browser tasks in a human-like
  way: clicking buttons, filling forms, navigating pages, scrolling, waiting for elements,
  reading page content, and verifying UI state — as if a real user were performing the
  actions. Covers single-page flows, multi-step workflows, login forms, file uploads,
  modal dialogs, and dynamic/JS-heavy pages. Triggers on requests like "interact with the
  web app", "simulate a user clicking through", "automate the UI", "fill out the form",
  "test the web interface manually", or "act like a human on the website".
---

# Human WebUI Interaction

Simulate a real human browsing and interacting with a web application. Prefer the
**Claude-in-Chrome MCP** (`mcp__Claude_in_Chrome__*`) for web targets — it is DOM-aware and
faster than pixel-level computer-use. Fall back to **computer-use** (`mcp__computer-use__*`)
only for native desktop flows or when the Chrome extension is unavailable.

## Tool priority

| Situation | Primary tool |
|-----------|--------------|
| Web app in Chrome | `mcp__Claude_in_Chrome__*` |
| Native desktop app | `mcp__computer-use__*` |
| Chrome unavailable | `mcp__computer-use__*` |
| File upload dialog (native) | `mcp__computer-use__*` after triggering upload in Chrome |

## Workflow

### 1. Orient

- Call `mcp__Claude_in_Chrome__list_connected_browsers` or `mcp__computer-use__screenshot`
  to confirm what is currently visible.
- If the target URL is not open, call `mcp__Claude_in_Chrome__navigate` to open it.
- Read `references/orientation.md` for page-read and state-check patterns.

### 2. Plan the interaction sequence

Before touching anything, outline the steps as a short ordered list. Ask the user if any step
is ambiguous (credentials, form values, target URL).

### 3. Execute step by step

Follow the patterns in `references/interaction-patterns.md`:

- **Read before act** — call `mcp__Claude_in_Chrome__read_page` or
  `mcp__Claude_in_Chrome__get_page_text` before clicking to confirm the element is present.
- **Find precisely** — use `mcp__Claude_in_Chrome__find` with a CSS selector or text query
  rather than clicking blind coordinates.
- **Type naturally** — use `mcp__Claude_in_Chrome__form_input` for inputs; for computer-use
  flows use `mcp__computer-use__triple_click` to select existing text then `type`.
- **Wait for dynamic content** — after navigation or a click that triggers a fetch, call
  `mcp__Claude_in_Chrome__get_page_text` or take a screenshot to confirm the next state
  loaded before proceeding.
- **Scroll when needed** — use `mcp__Claude_in_Chrome__javascript_tool` with
  `window.scrollBy` or `mcp__computer-use__scroll` to expose off-screen elements.

### 4. Verify each step

After every significant action (navigation, form submit, modal close), confirm the expected
outcome is visible before continuing. Screenshot or page-text check are both valid.

### 5. Report outcome

State clearly: what was done, what the final UI state is, and any warnings or deviations from
the plan. Include a screenshot URL or description of the final screen.

## Output contract

- Ordered summary of actions taken.
- Final UI state description (or screenshot).
- Any errors encountered and how they were handled.
- Explicit note if a step was skipped or required manual intervention.

## When to Use

- Automating browser tasks end-to-end as a human proxy.
- Verifying that a UI feature works by actually using it.
- Filling out multi-step forms or wizard flows.
- Testing login, upload, modal, or checkout flows.
- Extracting visible text or screenshots from a live web app.

## Limitations

- Cannot bypass CAPTCHA, biometric auth, or hardware token prompts — pause and ask the user.
- Browser-tier tools block typing in some IDEs and terminal apps; use Bash for those instead.
- Do not enter real credentials unless the user explicitly provides them for automation.
- Avoid clicking financial "confirm transfer" or "place order" buttons without explicit user
  approval — ask first, act second.
- If the Chrome extension is not connected, fall back to computer-use and note the degraded
  precision.
