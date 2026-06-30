# Foro SDK Repository Instructions

## Commit Messages

All commit messages **must** follow [Conventional Commits](https://www.conventionalcommits.org/) format.

### Format

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Types

- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Changes that don't affect code meaning (formatting, etc.)
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `perf`: Code change that improves performance
- `test`: Adding or updating tests
- `chore`: Changes to build process, dependencies, etc.
- `ci`: Changes to CI/CD configuration

### Examples

```
feat(typescript): add client initialization method
fix(python): resolve import path in __init__.py
docs: update publishing checklist
chore(deps): bump typescript to 5.7.0
```

### Breaking Changes

For breaking changes, add `!` before the colon:

```
feat!: remove deprecated API methods
feat(sdk)!: change initialization signature
```

**All automated tools (Copilot, AI agents) must respect this convention when generating commit messages.**
