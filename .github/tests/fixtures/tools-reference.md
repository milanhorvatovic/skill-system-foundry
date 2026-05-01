# Tools reference (synthetic test fixture)

Synthetic markdown fixture for the tool-catalog-drift extractor
tests. The structure mirrors what the helper expects from
`code.claude.com/docs/en/tools-reference.md` (Mintlify-rendered
markdown) — a `Tool | Description | Permission Required` table
preceded by some prose. Tool names are real (so tests can pin
canonical entries like `Bash` and `LSP`), but the surrounding prose
is minimal and synthetic to avoid vendoring upstream documentation
verbatim. Update this file when the canonical tool list changes
upstream and rerun the helper test suite.

| Tool                   | Description                                                                                                                  | Permission Required |
| :--------------------- | :--------------------------------------------------------------------------------------------------------------------------- | :------------------ |
| `Agent`                | Synthetic description for the Agent tool.                                                                                    | No                  |
| `AskUserQuestion`      | Synthetic description for the AskUserQuestion tool.                                                                          | No                  |
| `Bash`                 | Synthetic description for the Bash tool.                                                                                     | Yes                 |
| `CronCreate`           | Synthetic description for the CronCreate tool.                                                                               | No                  |
| `CronDelete`           | Synthetic description for the CronDelete tool.                                                                               | No                  |
| `CronList`             | Synthetic description for the CronList tool.                                                                                 | No                  |
| `Edit`                 | Synthetic description for the Edit tool.                                                                                     | Yes                 |
| `EnterPlanMode`        | Synthetic description for the EnterPlanMode tool.                                                                            | No                  |
| `EnterWorktree`        | Synthetic description for the EnterWorktree tool.                                                                            | No                  |
| `ExitPlanMode`         | Synthetic description for the ExitPlanMode tool.                                                                             | Yes                 |
| `ExitWorktree`         | Synthetic description for the ExitWorktree tool.                                                                             | No                  |
| `Glob`                 | Synthetic description for the Glob tool.                                                                                     | No                  |
| `Grep`                 | Synthetic description for the Grep tool.                                                                                     | No                  |
| `ListMcpResourcesTool` | Synthetic description for the ListMcpResourcesTool tool.                                                                     | No                  |
| `LSP`                  | Synthetic description for the LSP tool.                                                                                      | No                  |
| `Monitor`              | Synthetic description for the Monitor tool.                                                                                  | Yes                 |
| `NotebookEdit`         | Synthetic description for the NotebookEdit tool.                                                                             | Yes                 |
| `PowerShell`           | Synthetic description for the PowerShell tool.                                                                               | Yes                 |
| `Read`                 | Synthetic description for the Read tool.                                                                                     | No                  |
| `ReadMcpResourceTool`  | Synthetic description for the ReadMcpResourceTool tool.                                                                      | No                  |
| `SendMessage`          | Synthetic description for the SendMessage tool.                                                                              | No                  |
| `Skill`                | Synthetic description for the Skill tool.                                                                                    | Yes                 |
| `TaskCreate`           | Synthetic description for the TaskCreate tool.                                                                               | No                  |
| `TaskGet`              | Synthetic description for the TaskGet tool.                                                                                  | No                  |
| `TaskList`             | Synthetic description for the TaskList tool.                                                                                 | No                  |
| `TaskOutput`           | Synthetic description for the TaskOutput tool.                                                                               | No                  |
| `TaskStop`             | Synthetic description for the TaskStop tool.                                                                                 | No                  |
| `TaskUpdate`           | Synthetic description for the TaskUpdate tool.                                                                               | No                  |
| `TeamCreate`           | Synthetic description for the TeamCreate tool.                                                                               | No                  |
| `TeamDelete`           | Synthetic description for the TeamDelete tool.                                                                               | No                  |
| `TodoWrite`            | Synthetic description for the TodoWrite tool.                                                                                | No                  |
| `ToolSearch`           | Synthetic description for the ToolSearch tool.                                                                               | No                  |
| `WebFetch`             | Synthetic description for the WebFetch tool.                                                                                 | Yes                 |
| `WebSearch`            | Synthetic description for the WebSearch tool.                                                                                | Yes                 |
| `Write`                | Synthetic description for the Write tool.                                                                                    | Yes                 |
