# Global Claude Code Standards

## Behavior
- After every change, self-verify: check imports, lint mentally, confirm no regressions
- Proactively flag best practice violations even when not asked — report them before proceeding
- If a task touches code that has adjacent issues, mention them. Don't silently ignore problems
- Prefer modifying existing patterns over introducing new ones unless the existing pattern is the problem
- Before adding a dependency, check if the functionality already exists in the project or stdlib

## Code Review (always apply, unprompted)
- No inline HTML — always use templates
- No hardcoded secrets, credentials, or environment-specific values — use environment variables
- No dead code, unused imports, or commented-out blocks left behind
- Functions that do more than one thing should be flagged for splitting
- Repeated logic (3+ occurrences) should be flagged for extraction

## Security (OWASP basics, no CodeQL)
- Flag any user input that reaches a database without sanitization
- Flag any secret that appears in code, logs, or error messages
- Flag missing authentication/authorization checks on routes
- Flag SQL concatenation — parameterized queries only

## Git
- Use conventional commits: feat, fix, refactor, chore, docs, test
- Commit messages must describe intent, not mechanics ("add user auth" not "edit auth.py")
- One logical change per commit — don't bundle unrelated changes
- Never commit directly to main or master, create a new git branch and add the relevant information to commit comment
- All branches must be created under the `claude/` prefix: claude/feature-name, claude/fix-name, etc
- Use kebab-case for branch names: claude/user-authentication not claude/user_authentication

## Permissions
- You have full autonomy on any branch matching `claude/*` — create, commit, push, rebase, delete, no confirmation needed
- You may NOT touch any branch outside `claude/*` — no commits, no merges, no rebases, no deletes
- You may NOT merge into main under any circumstance — open a PR and stop
- Read access to all branches is fine, write access is `claude/*` only

## Testing
- Run existing tests after any change that could affect behavior
- If tests don't exist for modified code, mention it
- Don't delete or modify tests to make them pass — fix the code instead

## Documentation
- Update docstrings and comments affected by changes
- If a function signature changes, update all call sites and docs
- Public APIs must have docstrings

## Output Style
- Report findings before making changes unless the task is unambiguous and small
- For tasks touching 3+ files, state the plan first and wait for confirmation
- When something is ambiguous, ask one focused question rather than proceeding with assumptions
