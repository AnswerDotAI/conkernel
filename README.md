# conkernel

`conkernel` gives an LLM agent a persistent, real Jupyter kernel: send code, wait for the result, read concise text, and keep the Python state. It is the sibling of [clikernel](https://github.com/AnswerDotAI/clikernel), which wraps a tiny in-process shell; `conkernel` runs a full kernel (ipymini by default) in its own process, driven through [conkernelclient](https://github.com/AnswerDotAI/conkernelclient), so interrupt and restart are real protocol operations and the kernel process is fully isolated from the server.

There are two frontends over one core:

- `conkernel` -- a plain stdin/stdout process using clikernel's delimiter protocol, for harnesses that drive background terminals.
- `conkernel-mcp` -- an MCP server exposing `execute`, `restart`, `interrupt`, and `eval_expr` tools.

## Picking a kernel

No kernelspecs. A kernel is just a Python module launchable as `python -m <module> -f <connection_file>` -- `ipymini` (the default) and `ipykernel_launcher` both qualify. Pass `--kernel <module>` to either frontend, or set a default in `$XDG_CONFIG_HOME/conkernel/kernel` (a one-line file naming the module).

## The CLI protocol

clikernel's, including its loading banner: `please wait, loading...`, then `loading complete. first delimiter:`, then the random per-session delimiter signalling readiness (launching the kernel process can take a moment, so the banner reports progress before the delimiter arrives). Then one line per request (or a `--` block for multiline code, terminated by the delimiter), a `.` acknowledgement before execution, rendered outputs, then the delimiter. `exit()` or `quit()` on its own line stops the worker. SIGINT interrupts the running code -- state survives, and an idle kernel ignores it.

## Development

```bash
pip install -e .[dev]
```

## Versioning

Version lives in `conkernel/__init__.py` as `__version__`.
Bump it with:

```bash
ship-bump --part 2   # patch
ship-bump --part 1   # minor
ship-bump --part 0   # major
```

## Release

1) Ensure your GitHub issues are labeled (`bug`, `enhancement`, `breaking`).
2) Run:

```bash
ship-gh
ship-pypi
```
