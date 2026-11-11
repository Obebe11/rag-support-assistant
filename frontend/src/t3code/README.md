# UI kit adapted from T3 Code

The files in this folder are copied or adapted from the web app of T3 Code.

- Project: T3 Code, <https://github.com/pingdotgg/t3code>
- Source folder: `apps/web/src`
- Commit: `be7d35aae` (2026-08-21)
- License: MIT, Copyright (c) 2026 T3 Tools Inc. The license text is in [LICENSE](LICENSE).

Handoff AI is an independent project. It is not affiliated with or endorsed by T3 Tools Inc., and it uses no T3 Code names, logos, icons or interface texts. Everything outside this folder is original Handoff AI code under the repository's MIT License.

The rest of the frontend imports this folder through the `~` alias (`~/components/ui/button`), so the copied files keep their original import paths.

## Files copied without changes

| File | Source in `apps/web/src` |
| --- | --- |
| `components/ui/alert-dialog.tsx`, `alert.tsx`, `badge.tsx`, `button.tsx`, `card.tsx`, `collapsible.tsx`, `dialog-styles.ts`, `dialog.tsx`, `empty.tsx`, `field.tsx`, `fieldset.tsx`, `form.tsx`, `input.tsx`, `kbd.tsx`, `label.tsx`, `popover.tsx`, `scroll-area.tsx`, `separator.tsx`, `sheet.tsx`, `sidebarState.ts`, `skeleton.tsx`, `spinner.tsx`, `table.tsx`, `textarea.tsx`, `toggle.tsx`, `tooltip.tsx` | `components/ui/` (same names) |
| `components/RightPanelSheet.tsx` | `components/RightPanelSheet.tsx` |
| `components/preview/RightPanelResizeHandle.tsx` | `components/preview/RightPanelResizeHandle.tsx` |
| `hooks/useMediaQuery.ts` | `hooks/useMediaQuery.ts` |
| `workspaceTitlebar.ts` | `workspaceTitlebar.ts` |

## Files copied with small changes

Each change is marked in the file with a `Handoff AI:` comment.

| File | Source | Change |
| --- | --- | --- |
| `components/ui/sidebar.tsx` | `components/ui/sidebar.tsx` | A plain type guard replaces Effect Schema; the cookie write is skipped where the Cookie Store API is missing. |
| `components/preview/PreviewPanelShell.tsx` | `components/preview/PreviewPanelShell.tsx` | Own storage key; the desktop drag region is removed. |
| `components/WorkspacePageHeader.tsx` | `components/WorkspacePageHeader.tsx` | The desktop window options are removed. |
| `components/WorkspaceBreadcrumb.tsx` | `components/WorkspaceBreadcrumb.tsx` | A comment about the desktop window is removed. |
| `hooks/useResizableWidth.ts` | `hooks/useResizableWidth.ts` | A plain type guard replaces Effect Schema. |
| `rightPanelLayout.ts` | `rightPanelLayout.ts` | The window-controls-overlay classes are removed. |
| `lib/utils.ts` | `lib/utils.ts` | Only `cn` is kept. |
| `index.css` | `index.css` | The default token set, the base layer, the glass, scroll-fade and safe-area utilities, scrollbars and the chat markdown rules are kept. Named themes and their artwork, the desktop window chrome, and the terminal, diff, settings and composer-drawer styles are removed. |

## Files adapted from several sources

These files keep the markup and class names of the originals and drop what a support chat does not need. The header comment of each file lists what was kept and what was left out.

| File | Sources |
| --- | --- |
| `components/AppShell.tsx` | `components/AppSidebarLayout.tsx` |
| `components/RightPanel.tsx` | `components/RightPanelTabs.tsx`, `RightPanelSheet.tsx`, `preview/PreviewPanelShell.tsx`, `chat/PanelLayoutControls.tsx` |
| `components/StatusBanner.tsx` | `components/chat/ProviderStatusBanner.tsx` |
| `components/chat/Timeline.tsx` | `components/chat/MessagesTimeline.tsx`, `DraftHeroHeadline.tsx` |
| `components/chat/Composer.tsx` | `components/ChatView.tsx`, `chat/ChatComposer.tsx`, `ComposerPromptEditor.tsx`, `chat/ComposerPrimaryActions.tsx` |
| `components/chat/ChatMarkdown.tsx` | `components/ChatMarkdown.tsx` |

## Written for Handoff AI

`hooks/useLocalStorage.ts` is not a copy. It keeps the two function names that the copied files import and stores one validated value, without Effect Schema.

## Deliberate differences from T3 Code

- The timeline's top spacer is taller (`h-14`), so a one-row status banner fits above the first message and covers nothing.
- The status banner is a single row with an optional action instead of a dismiss button.
- The composer is a textarea with the original editor's classes. Model, mode and attachment controls are not ported.
- The right panel has a fixed list of tabs supplied by the page.

## Not taken

- Brand: product names, logos, icons, splash screens and interface texts.
- Fonts and theme artwork. The interface uses the system font stack.
- The dark theme is not enabled. Its tokens came with `index.css`, but nothing in the app switches the theme and no dark screen has been reviewed.
- The desktop shell, keybindings, command palette, settings, terminal, diff viewer, file tree, thread and project state, the virtualized message list, the rich-text editor and syntax highlighting.
- Dependencies that only those parts need, including Effect.
