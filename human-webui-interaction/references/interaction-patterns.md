# Interaction Patterns

## Navigation

```
mcp__Claude_in_Chrome__navigate { url: "https://example.com/login" }
```

After navigation, always verify the page loaded:
```
mcp__Claude_in_Chrome__get_page_text {}
```

## Finding elements

Prefer CSS selectors over coordinates:
```
mcp__Claude_in_Chrome__find { selector: "button[type=submit]" }
mcp__Claude_in_Chrome__find { selector: "input[name=email]" }
mcp__Claude_in_Chrome__find { text: "Sign In" }
```

## Clicking

```
mcp__Claude_in_Chrome__find { selector: "#login-btn" }
# then
mcp__Claude_in_Chrome__javascript_tool { code: "document.querySelector('#login-btn').click()" }
```

Or use computer-use left_click after a screenshot to locate coordinates.

## Typing into inputs (Chrome MCP)

```
mcp__Claude_in_Chrome__form_input { selector: "input[name=email]", value: "user@example.com" }
mcp__Claude_in_Chrome__form_input { selector: "input[name=password]", value: "••••••••" }
```

## Typing into inputs (computer-use fallback)

```
mcp__computer-use__triple_click { coordinate: [x, y] }   # select existing text
mcp__computer-use__type { text: "replacement value" }
```

## Scrolling

Chrome MCP:
```
mcp__Claude_in_Chrome__javascript_tool { code: "window.scrollBy(0, 600)" }
mcp__Claude_in_Chrome__javascript_tool { code: "document.querySelector('.results').scrollIntoView()" }
```

computer-use:
```
mcp__computer-use__scroll { coordinate: [760, 400], direction: "down", amount: 5 }
```

## Waiting for dynamic content

There is no explicit wait tool. Pattern: read page text / take screenshot after action, and
retry once if the expected element is absent. For long-running fetches, add a brief
`javascript_tool` poll:
```javascript
// poll up to 3s
await new Promise(r => {
  const t = Date.now();
  const i = setInterval(() => {
    if (document.querySelector('.loaded') || Date.now()-t>3000) { clearInterval(i); r(); }
  }, 300);
});
```

## File upload

1. Click the file input with Chrome MCP or computer-use.
2. Use `mcp__Claude_in_Chrome__file_upload` if available, or `mcp__computer-use__type` the
   path into the native file dialog after it opens.

## Reading page state

```
mcp__Claude_in_Chrome__get_page_text {}          # visible text only
mcp__Claude_in_Chrome__read_page {}              # structured DOM snapshot
mcp__computer-use__screenshot {}                 # pixel screenshot
mcp__Claude_in_Chrome__read_console_messages {}  # JS console for error detection
```

## Handling modals and dialogs

- Detect modal: `find { selector: "[role=dialog]" }` or look for overlay in `read_page`.
- Dismiss with ESC: `mcp__computer-use__key { text: "Escape" }`.
- Confirm: find and click the confirm button inside the modal selector scope.

## Form submission

Prefer clicking the submit button over pressing Enter — it matches human behavior and triggers
validation handlers:
```
mcp__Claude_in_Chrome__javascript_tool { code: "document.querySelector('form').submit()" }
```
Or find and click `button[type=submit]`.

## Anti-pattern: clicking blind coordinates

Bad:
```
mcp__computer-use__left_click { coordinate: [340, 210] }   # fragile, breaks on resize
```

Good: use `find` + `javascript_tool` click, or screenshot first and verify the element is at
the expected position before clicking.
