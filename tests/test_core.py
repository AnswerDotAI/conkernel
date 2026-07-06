import asyncio
from conkernel.core import Session, default_kernel, DEFAULT_KERNEL


async def test_default_kernel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_kernel() == DEFAULT_KERNEL == "ipymini"
    (tmp_path/"conkernel").mkdir()
    (tmp_path/"conkernel"/"kernel").write_text("ipykernel_launcher\n")
    assert default_kernel() == "ipykernel_launcher"


async def test_session():
    async with Session() as s:
        # execute: results, state, multiple outputs, clean errors
        assert await s.execute("40+2") == "42"
        assert await s.execute("x = 41") == ""
        assert await s.execute("x + 1") == "42"
        r = await s.execute("print('hi'); 99")
        assert "<stdout>\nhi\n</stdout>" in r
        assert "<execute_result>\n99\n</execute_result>" in r
        r = await s.execute("1/0")
        assert "ZeroDivisionError" in r and "\x1b[" not in r
        assert await s.eval("[i*2 for i in range(3)]") == [0, 2, 4]

        # interrupt: the running execute returns KeyboardInterrupt, state survives
        t = asyncio.ensure_future(s.execute("import time; time.sleep(30)"))
        while not s.busy: await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)
        await s.interrupt()
        assert "KeyboardInterrupt" in await t
        assert await s.eval("x") == 41

        # restart: fresh process, state gone, session usable
        pid1 = s.km.provisioner.pid
        await s.restart()
        assert s.km.provisioner.pid != pid1
        assert "NameError" in await s.execute("x")
        assert await s.execute("40+2") == "42"


async def test_alternate_kernel():
    async with Session(kernel="ipykernel_launcher") as s: assert await s.execute("1+1") == "2"
