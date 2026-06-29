# Orientation Patterns

## Check what is currently visible

Always start with a state check before taking action.

```
# Chrome MCP (preferred)
mcp__Claude_in_Chrome__list_connected_browsers {}
mcp__Claude_in_Chrome__tabs_context_mcp {}

# Fallback
mcp__computer-use__screenshot {}
```

## Confirm correct page

After navigating, read the page title or a landmark element:
```
mcp__Claude_in_Chrome__javascript_tool { code: "document.title" }
mcp__Claude_in_Chrome__javascript_tool { code: "location.href" }
```

## Map the interaction flow before executing

Write a numbered plan, for example:
1. Navigate to login page.
2. Fill email field.
3. Fill password field.
4. Click Sign In.
5. Verify dashboard heading appears.

For complex flows, check for branching states (error banners, redirect loops, 2FA prompts)
and handle them explicitly rather than assuming the happy path.

## Detect error states

After each submit or navigation:
```
mcp__Claude_in_Chrome__read_console_messages {}          # JS errors
mcp__Claude_in_Chrome__get_page_text {}                  # visible error banners
mcp__Claude_in_Chrome__read_network_requests {}          # failed API calls
```

Common error signals in page text: "error", "invalid", "required", "failed", "unauthorized",
"404", "500".

## Identify the right Chrome tab

```
mcp__Claude_in_Chrome__tabs_context_mcp {}
# returns list of open tabs; pick target by URL or title, then:
mcp__Claude_in_Chrome__select_browser { ... }
```
