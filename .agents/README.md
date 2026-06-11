# Agents

Project-specific prompts and workflows for AI-assisted development.

These files are operational instructions for Codex or another AI coding tool. They are not user-facing product documentation.

## Available Agents

- `reviews/code_exception_review.md`: review Python code for unhandled exceptions, unsafe failure paths, and missing tests around error handling.

## How To Use

Start a new Codex request and reference the agent file plus the code area to inspect.

Example for the `bt_joy` project:

```text
Use .agents/reviews/code_exception_review.md to review bt_joy for unhandled exceptions.

Focus on:
- bt_joy/bt_joy/client
- bt_joy/bt_joy/server
- CLI startup paths
- UDP/network failures
- config parsing failures
- MSP request/response failures

Return findings only. Do not change code yet.
```

For a narrower review:

```text
Use .agents/reviews/code_exception_review.md to review bt_joy/bt_joy/client/runner.py for unhandled exceptions.

Return:
- file and line
- exception risk
- why it can happen
- recommended fix
- suggested test

Do not edit files.
```
