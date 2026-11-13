# Old Directories Cleanup Checklist

**No source directory was deleted in this consolidation.** Do not delete anything until the VerbaTrail project is committed, validated, the Git bundle and database backup are verified, and the owner reviews this list.

| Directory | Cleanup condition | Notes |
|---|---|---|
| `D:\Projects\UnlearnLoop-argon` | May be removed only after comparing the archived prototypes in `D:\Projects\VerbaTrail\docs\design\archived\` and verifying the bundle. | Linked worktree metadata currently lives inside the `UnlearnLoop` common repository. |
| `D:\Projects\UnlearnLoop-codex` | May be removed after verifying API Client branch history in the bundle/new clone. | Linked worktree; source was clean. |
| `D:\Projects\UnlearnLoop-ielts` | May be removed only after the consolidation commit and report/screenshots are present in VerbaTrail and the bundle is verified. | Contains the valuable uncommitted dual-theme UI; source remains untouched now. |
| `D:\Projects\UnlearnLoop-integration` | May be removed only after verifying the archived planning docs and that the copied DB hash matches the external backup. | Contains an uncommitted SQLite DB and planning files; source remains untouched now. |
| `D:\Projects\UnlearnLoop` | Remove last, and only as part of cleaning the entire legacy worktree set. | This is the common Git directory for the four linked worktrees above. Deleting it first would leave their `.git` pointers broken. It also has local main divergence, preserved in the backup bundle. |
| `D:\Temp\unlearnloop-main-docs-ielts1` | Optional extra worktree; remove only after verifying the main-docs commit is reachable in VerbaTrail. | Discovered in `git worktree list`; not one of the five listed roots, but it depends on the old common repository. |

Suggested user-controlled cleanup order: preserve the external bundle/database backup; close any process whose working directory is an old folder; remove the four linked worktree directories and the extra temporary worktree; remove the old common repository last. This document is a checklist only; it does not perform cleanup.
