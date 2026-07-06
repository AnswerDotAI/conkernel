"MCP frontend: execute/restart/interrupt/eval_expr tools over one persistent kernel Session."
import asyncio
from fastcore.script import call_parse
from conkernel.core import DeadKernelError, Session

_DIED = "NOTE: the kernel process had died; a fresh one was started, and all previous session state (imports, variables, monkeypatches) is gone.\n"


@call_parse
def main(kernel:str=None):  # Kernel server module to launch (default: XDG config, else ipymini)
    "The conkernel MCP server"
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP('conkernel')
    state = dict(sess=None, lock=asyncio.Lock())

    async def _sess():
        "The running Session, restarted with a state-lost note if its kernel died; started on first use"
        note = ''
        if state['sess'] is None: state['sess'] = await Session(kernel).start()
        elif not await state['sess'].km.is_alive():
            note = _DIED
            await state['sess'].restart()
        return state['sess'], note

    @mcp.tool(structured_output=False)
    async def execute(code:str  # IPython-compatible code to run in the persistent session
                     )->str:   # Rendered outputs (stdout, display data, last-expression result, errors)
        "Run `code` in the persistent IPython session, keeping state across calls (imports, variables, monkeypatches, cached objects). If the kernel process has died since the last call, a fresh one is started automatically and the response notes that session state was lost."
        async with state['lock']:
            s, note = await _sess()
            try: return note + await s.execute(code)
            except DeadKernelError:
                await s.restart()
                return note + _DIED + "<internal-error>\nthe kernel died while executing this request; a fresh kernel is running\n</internal-error>"

    @mcp.tool(structured_output=False)
    async def eval_expr(expr:str  # A Python expression (no statements)
                       )->str:  # repr of its value
        "Evaluate `expr` in the session and return its value's repr -- cheaper and cleaner than `execute` for reading state, since it doesn't touch outputs or history."
        async with state['lock']:
            s, note = await _sess()
            return note + repr(await s.eval(expr))

    @mcp.tool(structured_output=False)
    async def restart()->str:
        "Kill the kernel process and start a fresh one: new pid, `sys.modules` genuinely reset, all session state (imports, variables, monkeypatches, cached objects) discarded. Use for a clean slate, after rebuilding a native extension, or after reloading a module that other already-imported modules had patched. Also works when `execute` is stuck: the stuck call returns an error and the kernel comes back fresh. After restarting, redo any imports/setup the task still needs."
        if state['sess'] is None: return 'no kernel running yet'
        await state['sess'].restart()  # no lock: reconnect fails any stuck pending reply, freeing `execute`
        return 'restarted'

    @mcp.tool(structured_output=False)
    async def interrupt()->str:
        "Interrupt the code the kernel is currently running (SIGINT, i.e. KeyboardInterrupt): the in-flight `execute` call returns with a KeyboardInterrupt traceback, and session state survives. Prefer this over `restart` when a call is merely taking too long. Only meaningful while an `execute` call is running."
        s = state['sess']
        if s is None or not s.busy: return 'nothing is running'
        await s.interrupt()
        return 'interrupt sent; the running `execute` call will return with a KeyboardInterrupt'

    mcp.run()
