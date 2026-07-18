# Development prompts (session history)

This document summarizes the user prompts that shaped MessageManager, captured from the Cursor agent transcript that built the product through **v1.0.8**. System/tool boilerplate is omitted. Wording is lightly cleaned for readability.

Source transcript: [MessageManager build session](6a0a95a1-f35b-4e65-aa70-03c77db33312)

## Product genesis

1. Build an application that reads the local iMessage database, categorizes threads as business or personal, and can summarize each on request.
2. Prefer a local web app; initially planned Apple Intelligence for summaries.
3. Use a local extractive summarizer first.
4. Later: toggle Apple Intelligence summaries on Apple Silicon.

## Contacts & packaging

5. Resolve phone numbers / emails to names from macOS Contacts.
6. Package as a clickable Mac app icon for use on another Mac.
7. Rename the product to **MessageManager**.
8. Explain Gatekeeper “untrusted” opens on the other Mac.
9. Fix “cannot create virtual python environment” on install/launch.

## UX & performance

10. Detect Apple Silicon vs Intel; show a status bar while Messages are loading.
11. Don’t load full thread details up front — show the list first, load details for summarization, and let the user set summary day range.
12. Fix empty thread list (show conversation + latest preview).
13. Avoid long hangs on previews; add progress detail and/or load only the most recent 50.
14. Always rebuild the MessageManager deployment (`.app`) after product changes.
15. Contacts load was hanging; add a slider + **Start loading** for conversation count.
16. If Apple Intelligence is on, don’t silently fall back to extractive; clarify where errors are logged; investigate the app stopping after a few minutes.
17. Summaries should capture the overall discussion context.
18. Provide a paste-ready Apple Shortcut for summarization.
19. Keep-alive control window was closing unexpectedly.
20. When a conversation is selected, load the latest 10 messages; keep any existing summary visible.
21. Max loadable conversations should equal total available (default still 50); clicking Uncategorized should let the user set Business/Personal.
22. Fix max count, category click target, and latest-10 message loading.
23. Category picker should appear just below the Uncategorized label (not top-left of the screen).
24. Rebuild/update the packaged app.
25. App icon: iMessage-style bubble with a magnifying glass.
26. Merge the accumulated changes.

## GitHub, UI layout, settings

27. Push / create a new GitHub repository.
28. Collapse the load controls after loading; put category totals (All / Business / Personal / Unset) at the top of the main pane; allow loading 100 more or all messages.
29. Add **Ignore** category; Settings for defaults (auto-load, recent message count, available categories, hide categories from default All); allow changing category even when already set.
30. Move Apple Intelligence into Settings; allow custom categories; load by count **or** by recent activity (months/years).

## Releases & installers (1.0.x)

31. Cut release **1.0** with a macOS installer that prompts for permissions, checks GitHub for updates, and runs migrations on upgrade.
32. Title **MessageManager v1.0.0**; rename “thread” → “conversation”; merge and publish.
33. App missing from Applications after install; install minimum Python deps; **1.0.1**; publish.
34. Stop putting the version in the `.pkg` filename; ask how to reduce Gatekeeper trust friction.
35. Publish **v1.0.2** with unversioned package name.
36. Python crash / `chat.db` denied despite Full Disk Access; stop conflicting local Python processes.
37. Merge and ship **v1.0.3** with launch-time update check + install prompt.
38. After installing 1.0.3, UI still showed 1.0.2 / “latest”.
39. Still blocked on `chat.db` with FDA on app + Python; in-app Logs viewer; Copy on summary; **v1.0.5**.
40. Transparent icon (no white square); **v1.0.6**; user updates from GitHub to verify the updater.
41. Dock icon click did nothing after icon update.
42. Don’t keep prompting for Full Disk Access when access is already granted.
43. Contacts not reading (Messages OK); magnifying glass fully inside the green bubble → **v1.0.8**.
44. Publish to GitHub; hand off to another machine with prompt summary, updated README, screenshots (test data), install instructions, and a requirements document.

## Notes for continuing on another machine

- Prefer installing from [GitHub Releases](https://github.com/srtviperjr/MessageManager/releases) (`MessageManager.pkg`).
- After code changes, rebuild with `./scripts/create-macos-app.sh` (and installer script when publishing).
- Full Disk Access must be granted to **MessageManager.app**; the native launcher copies Messages + Contacts into Application Support so the Python server can read them.
- Public repo is required for in-app update checks.
