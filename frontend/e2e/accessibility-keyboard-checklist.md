# CRM accessibility keyboard regression

Automated axe checks do not prove keyboard usability. Run this checklist before releasing changes to the listed controls.

## Setup

1. Start the local stack with `make dev`.
2. Sign in as an owner-level seeded user with representative CRM data.
3. Test once at **1440 x 900** and once at **390 x 844**.
4. Use only `Tab`, `Shift+Tab`, arrow keys, `Space`, `Enter`, `Escape`, `Home`, `End`, and `PageDown`.
5. Repeat the mobile pass at 200% browser zoom; verify 400% reflow on one Settings and one financial route.

## Route matrix

| Route                                                                      | Keyboard path                                                                                          | Pass condition                                                                                                                                |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `/contacts`                                                                | Tab through search, filters, Add Contact, row actions, and pagination.                                 | Every icon button has a spoken name; focus is visible; no action is pointer-only.                                                             |
| `/quotes`                                                                  | Tab through quote actions, line-item controls, and proposal actions.                                   | Controls announce their action and selected/disabled state; focus order follows the page.                                                     |
| `/calendar`                                                                | Use Tab plus arrow keys on previous/next and view controls, then open and close an appointment dialog. | Calendar controls are named; focus enters the dialog and returns to its trigger on `Escape`.                                                  |
| `/reports`                                                                 | Tab to the named Reports region, then press `PageDown`, `End`, and `Home`.                             | The scroll region retains visible focus and scrolls without trapping the keyboard. Financial values remain readable in light and dark themes. |
| `/settings?tab=profile`                                                    | Focus the Settings tab list and use Left/Right, Home/End, and Enter.                                   | Every icon-only mobile tab announces its full label and selected state; the matching panel appears.                                           |
| `/settings?tab=proposals`                                                  | Tab through logo, brand/accent color pickers and hex fields, then save.                                | Each field announces the visible purpose and value; color and hex controls have distinct names.                                               |
| `/settings?tab=pricing`                                                    | Tab through offering, category, option, package, and enable controls.                                  | Labels match their exact input; each switch announces its purpose and state.                                                                  |
| `/agents/create`                                                           | Tab through step buttons and inputs; activate a completed step with Enter.                             | Every step announces number, label, and current/completed/upcoming state.                                                                     |
| `/campaigns/sms/new`, `/campaigns/voice/new`, `/campaigns/pre-booking/new` | Repeat the stepper test; operate all selects and switches with the keyboard.                           | Step names remain available on mobile; comboboxes and switches announce purpose and state.                                                    |
| `/experiments/new`, `/offers/new`                                          | Repeat the stepper test and toggle option switches.                                                    | Focus is visible and state changes are announced without relying on color.                                                                    |
| `/sales-wizard`                                                            | Open a configured proposal, reach Design Packages, then operate each quantity control.                 | Decrease, quantity, and increase controls announce the item name; zero disables only Decrease; Enter/Space and typed values work.             |
| Valid public proposal URL                                                  | Focus the package selector and use all four arrow keys, Space, and Enter.                              | The group and each package have names; one package is checked; focus and selection move together.                                             |
| Agent embed configuration                                                  | Open Embed, enable it, tab through fields/code/share link, then close with Escape.                     | Every field and switch is named; horizontal code regions scroll while focused; focus returns to the Embed trigger.                            |
| Valid public embed URL                                                     | Open chat, send a message, focus message history, and operate voice/close controls if enabled.         | Icon controls are named; new messages are announced; the history region scrolls from the keyboard.                                            |

## Record

Record browser, operating system, viewport, theme, route, pass/fail, and the first failing control. A release is blocked by any missing name, invisible focus, keyboard trap, pointer-only action, unreadable normal text, or focus loss after a dialog closes.

Screen-reader output and browser zoom remain manual evidence. Do not describe the scoped routes as WCAG conformant based on axe and this checklist alone.
