import os, pty, select, signal, subprocess, sys, time

TIMEOUT = 30


def _readline(p, timeout=TIMEOUT):
    r, _, _ = select.select([p.stdout], [], [], timeout)
    assert r, "timeout waiting for line"
    return p.stdout.readline().decode()


def _body(p, delim):
    "Read the `.` ack then response lines up to the delimiter."
    assert _readline(p) == ".\n"
    body = []
    while (line := _readline(p)) != delim + "\n": body.append(line)
    return "".join(body)


def send(p, delim, code):
    p.stdin.write((code + "\n").encode())
    p.stdin.flush()
    return _body(p, delim)


def test_cli():
    p = subprocess.Popen([sys.executable, "-m", "conkernel.cli"], bufsize=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    delim = _readline(p, 60).rstrip("\n")  # first line printed is the session delimiter
    assert delim.startswith("--") and len(delim) == 7

    assert send(p, delim, "40+2") == "42\n"
    send(p, delim, "x = 41")
    assert send(p, delim, "x + 1") == "42\n"

    p.stdin.write(f"--\ndef f(a):\n    return a + 1\n\nf(2)\n{delim}\n".encode())
    p.stdin.flush()
    assert _body(p, delim) == "3\n"

    r = send(p, delim, "1/0")
    assert "ZeroDivisionError" in r and "\x1b[" not in r

    # SIGINT while idle is ignored; while running, it interrupts the code and state survives
    p.send_signal(signal.SIGINT)
    time.sleep(0.2)
    assert p.poll() is None
    assert send(p, delim, "1+1") == "2\n"
    p.stdin.write(b"import time; time.sleep(30)\n")
    p.stdin.flush()
    assert _readline(p) == ".\n"
    time.sleep(0.5)
    p.send_signal(signal.SIGINT)
    body = []
    while (line := _readline(p)) != delim + "\n": body.append(line)
    assert "KeyboardInterrupt" in "".join(body)
    assert send(p, delim, "x") == "41\n"

    # exit() stops the worker: ack, final delimiter, clean exit
    p.stdin.write(b"exit()\n")
    p.stdin.flush()
    assert _readline(p) == ".\n"
    assert _readline(p) == delim + "\n"
    assert p.wait(timeout=10) == 0


def test_cli_tty():
    "PTY-driven worker: input isn't echoed, output stays LF (no ONLCR CR), and long lines survive canonical-mode limits."
    master, slave = pty.openpty()
    try: p = subprocess.Popen([sys.executable, "-m", "conkernel.cli"], stdin=slave, stdout=slave, close_fds=True)
    finally: os.close(slave)
    buf = bytearray()
    def readline(timeout=TIMEOUT):
        nonlocal buf
        while b"\n" not in buf:
            r, _, _ = select.select([master], [], [], timeout)
            assert r, f"timeout waiting for pty line; buffer: {bytes(buf)!r}"
            chunk = os.read(master, 4096)
            assert chunk, "pty EOF"
            buf.extend(chunk)
        line, _, rest = bytes(buf).partition(b"\n")
        buf = bytearray(rest)
        return line + b"\n"
    try:
        first = readline(60)
        assert b"\r" not in first
        delim = first.decode().rstrip("\n")
        assert delim.startswith("--") and len(delim) == 7
        os.write(master, b"1+1\n")
        assert readline() == b".\n"  # no echo: the ack is the first thing back
        assert readline() == b"2\n"  # and bare LF: ONLCR is off
        assert readline() == delim.encode() + b"\n"
        # long line: canonical mode would drop bytes past MAX_CANON (1024 on macOS) with BEL spam
        os.write(master, f"--\ns = 'b{'b' * 5000}'\nlen(s)\n{delim}\n".encode())
        assert readline() == b".\n"
        assert readline() == b"5001\n"
        assert readline() == delim.encode() + b"\n"
        os.write(master, b"exit()\n")
        assert readline() == b".\n"
        assert readline() == delim.encode() + b"\n"
        assert p.wait(timeout=10) == 0
    finally:
        os.close(master)
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)
