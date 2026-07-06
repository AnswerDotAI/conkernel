import asyncio, os, signal, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_params = StdioServerParameters(command=sys.executable, args=["-m", "conkernel.mcp"])


async def _text(s, name, **args):
    res = await s.call_tool(name, args)
    return res.content[0].text if res.content else ""


async def test_mcp():
    "One server: every tool's behavior, then the destructive lifecycle (interrupt, restart, external kill)."
    async with stdio_client(_params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        assert {t.name for t in (await s.list_tools()).tools} == {"execute", "restart", "interrupt", "eval_expr"}
        pid1 = int(await _text(s, "execute", code="import os; x = 41; os.getpid()"))
        assert await _text(s, "execute", code="x + 1") == "42"
        r_ = await _text(s, "execute", code="print('hi'); 99")
        assert "<stdout>\nhi\n</stdout>" in r_
        assert "<execute_result>\n99\n</execute_result>" in r_
        r_ = await _text(s, "execute", code="1/0")
        assert "ZeroDivisionError" in r_ and "\x1b[" not in r_
        assert await _text(s, "eval_expr", expr="[x, x + 1]") == "[41, 42]"
        assert "nothing" in (await _text(s, "interrupt")).lower()

        # interrupt a running execute: kernel is warm, so a short settle before SIGINT suffices
        task = asyncio.create_task(s.call_tool("execute", {"code": "import time; time.sleep(30); 'fin'+'ished'"}))
        await asyncio.sleep(0.5)
        assert "interrupt" in (await _text(s, "interrupt")).lower()
        out = (await task).content[0].text
        assert "KeyboardInterrupt" in out and "finished" not in out
        assert await _text(s, "execute", code="40+2") == "42"

        # restart: fresh pid, state gone, clean return
        assert await _text(s, "restart") == "restarted"
        pid2 = int(await _text(s, "execute", code="import os; os.getpid()"))
        assert pid2 != pid1
        assert "NameError" in await _text(s, "execute", code="x")

        # externally killed kernel: the next execute reports lost state (via the pre-check or the
        # mid-execution liveness watchdog, depending on how fast the process dies) and self-heals
        os.kill(pid2, signal.SIGKILL)
        assert "state" in await _text(s, "execute", code="40+2")
        assert await _text(s, "execute", code="40+2") == "42"
