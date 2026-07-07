"Delimiter-protocol frontend: clikernel's CLI protocol, backed by a real kernel."
import asyncio, secrets, signal, string, sys, termios, traceback, tty
from fastcore.script import call_parse
from conkernel.core import Session

_ALPHANUM = string.ascii_letters + string.digits
_MULTILINE = '--'


def _new_delim():
    "A random per-session delimiter, unlikely to appear in generated code, logs, or transcript text"
    return '--' + ''.join(secrets.choice(_ALPHANUM) for _ in range(5))


def _write_response(delim, body=None):
    "Print `body` (ensuring it ends with a newline), then the delimiter line"
    if body: print(body, end='' if body.endswith('\n') else '\n', flush=True)
    print(delim, flush=True)


async def _readline():
    """Read one stdin line in a worker thread, since a blocking read in the coroutine would wedge the
    event loop -- which must stay live while idle so SIGINT handlers fire promptly and the kernel
    client's background reader keeps running."""
    return await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)


def _tty_clear(stream, idx, mask, cc=None):
    "Clear `mask` bits in termios field `idx` when `stream` is a TTY, with optional `cc` char overrides; returns state for `_tty_restore`"
    if not stream.isatty(): return None
    fd = stream.fileno()
    attrs = termios.tcgetattr(fd)
    new_attrs = attrs[:]
    new_attrs[idx] &= ~mask
    if cc:
        new_attrs[6] = attrs[6][:]
        for k, v in cc.items(): new_attrs[6][k] = v
    termios.tcsetattr(fd, termios.TCSADRAIN, new_attrs)
    return fd, attrs


def _tty_restore(state):
    if state: termios.tcsetattr(state[0], termios.TCSADRAIN, state[1])


async def _read_block(delim):
    "Read a multiline code block terminated by a `delim` line; returns `(code, err)`"
    lines = []
    while True:
        line = await _readline()
        if not line: return '', f'missing block terminator: {delim}'
        if line.rstrip('\n') == delim: return ''.join(lines), None
        lines.append(line)


async def _serve(kernel):
    # Both lines print after main's ONLCR clear, so they stay bare LF.
    print("please wait, loading...", flush=True)
    async with Session(kernel) as s:
        delim = _new_delim()
        # SIGINT means 'interrupt the running code'; an idle kernel just ignores it
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, lambda: asyncio.ensure_future(s.interrupt()))
        print("loading complete. first delimiter:", flush=True)
        _write_response(delim)
        while True:
            line = await _readline()
            if not line: break
            line = line.rstrip('\n')
            if line == _MULTILINE:
                code, err = await _read_block(delim)
                if err:
                    _write_response(delim, f'<protocol-error>\n{err}</protocol-error>')
                    continue
            else: code = line
            print('.', flush=True)
            if code.strip() in ('exit()', 'quit()'):
                _write_response(delim)
                break
            try: out = await s.execute(code)
            except Exception: out = f'<internal-error>\n{traceback.format_exc()}</internal-error>'
            _write_response(delim, out)


@call_parse
async def main(kernel:str=None):  # Kernel server module to launch (default: XDG config, else ipymini)
    "The conkernel stdin/stdout worker: read one request per line (or `--` block), answer with rendered outputs. A clikernel-style loading banner precedes the session delimiter that signals readiness"
    # ONLCR off so protocol output stays bare LF; ECHO off (echoed input corrupts the protocol) and ICANON
    # off (canonical mode drops bytes past MAX_CANON with BEL spam; VMIN/VTIME make non-canonical reads
    # return per byte; ISIG stays on so ^C still interrupts)
    tty_states = (_tty_clear(sys.__stdout__, tty.OFLAG, termios.ONLCR),
        _tty_clear(sys.stdin, tty.LFLAG, termios.ECHO | termios.ICANON, {termios.VMIN: 1, termios.VTIME: 0}))
    try: await _serve(kernel)
    finally:
        for st in tty_states: _tty_restore(st)
