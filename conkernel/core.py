"Persistent Jupyter kernel session: the shared core under conkernel's CLI and MCP frontends."
import asyncio, sys
from fastcore.utils import *
from fastcore.nbio import render_text
from fastcore.ansi import strip_ansi
from fastcore.xdg import xdg_config_home
from conkernelclient import ConKernelManager, DeadKernelError
from conkernelclient.ops import nb_outputs, parent_id, reconnect
from jupyter_client.kernelspec import KernelSpec

DEFAULT_KERNEL = 'ipymini'


def default_kernel():
    "Kernel server module to launch: `$XDG_CONFIG_HOME/conkernel/kernel` (a one-line file) overrides `ipymini`"
    p = xdg_config_home()/'conkernel'/'kernel'
    return p.read_text().strip() if p.exists() else DEFAULT_KERNEL


class ModuleKernelManager(ConKernelManager):
    "Launches `python -m <module> -f <connection_file>`, so no kernelspec install is needed"
    def __init__(self, module=DEFAULT_KERNEL, **kw):
        super().__init__(**kw)
        self._kernel_spec = KernelSpec(language='python', display_name=module,
            argv=[sys.executable, '-Xfrozen_modules=off', '-m', module, '-f', '{connection_file}'])


class Session:
    "One persistent kernel and client, with the operations an agent workbench needs"
    def __init__(self, kernel=None): self.kernel,self.km,self.kc,self.busy = kernel or default_kernel(),None,None,0

    async def start(self):
        "Launch the kernel process and connect the client"
        self.km = ModuleKernelManager(module=self.kernel)
        await self.km.start_kernel()
        self.kc = await self.km.client().start_channels()
        return self

    async def execute(self, code, timeout=None):
        """Run `code` in the kernel; return its rendered outputs (ANSI-stripped). A ZMQ peer dying is
        silent -- no EOF, the reply just never comes -- so while waiting we poll kernel liveness and
        raise `DeadKernelError` if it dies mid-execution rather than hanging forever."""
        self.busy += 1
        try:
            t = asyncio.ensure_future(self.kc.execute(code, reply=True, timeout=timeout))
            while True:
                done, _ = await asyncio.wait({t}, timeout=1)
                if done: break
                if not await self.km.is_alive():
                    t.cancel()
                    raise DeadKernelError('kernel died while executing')
            msgs = await self.kc.iopub_drain(parent_id(t.result()))
        finally: self.busy -= 1
        return strip_ansi(render_text(nb_outputs(msgs)))

    async def eval(self, expr, **kw):
        "Value of `expr` in the kernel (see conkernelclient's `eval_expr`)"
        return await self.kc.eval_expr(expr, **kw)

    async def interrupt(self):
        "Interrupt the running code; session state survives"
        return await self.kc.interrupt()

    async def restart(self):
        "Fresh kernel process: new pid, `sys.modules` reset, all session state discarded"
        self.kc = await reconnect(self.km, self.kc)

    async def close(self):
        "Stop the client channels and shut the kernel down"
        if self.kc is not None: self.kc.stop_channels()
        if self.km is not None and await self.km.is_alive(): await self.km.shutdown_kernel(now=True)

    async def __aenter__(self): return await self.start()
    async def __aexit__(self, *exc): await self.close()
