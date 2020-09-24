import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from redbot.core import commands

from .paginator import *


@dataclass
class CompilerOptions:
    compilerOptions: Dict[str, bool]
    filters: Dict[str, bool]
    userArguments: str = ""
    tools: List[str] = field(default_factory=list)
    libraries: List[str] = field(default_factory=list)

    @staticmethod
    def default_execute(comp_args: str="") -> "CompilerOptions":
        comp_opts: Dict[str, bool] = {
            "executorRequest": True
        }
        filters: Dict[str, bool] = {
            "execute": True
        }
        return CompilerOptions(comp_opts, filters, userArguments=comp_args)

    @staticmethod
    def default_disassembly(comp_args: str="") -> "CompilerOptions":
        comp_opts: Dict[str, bool] = {
            "skipAsm": False,
            "executorRequest": False
        }
        filters: Dict[str, bool] = {
            "binary": False,
            "commentOnly": True,
            "demangle": True,
            "directives": True,
            "execute": False,
            "intel": True,
            "labels": True,
            "libraryCode": False,
            "trim": False
        }
        return CompilerOptions(comp_opts, filters, userArguments=comp_args)

@dataclass
class RequestData:
    source: str
    compiler: str
    lang: str
    options: CompilerOptions
    allowStoreCodeDebug: bool = False

class GodBolt(commands.Cog):
    def __init__(self) -> None:
        self._url_base = "https://godbolt.org"

    def _endpoint(self, end: str) -> str:
        return f"{self._url_base}{end}"

    @commands.cooldown(1, 2)
    @commands.group()
    async def godbolt(self, ctx: commands.Context) -> None:
        """
        Commands for utilizing the Godbolt Compiler Explorer commands over discord.
        """
        pass

    @godbolt.command(name="languages")
    async def godbolt_languages(self, ctx: commands.Context) -> None:
        """
        Lists all of the languages available via the API.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(self._endpoint("/api/languages"),
                        headers={"accept": "application/json"}) as resp:

                resp_data: List[Dict[str, str]] = await resp.json()
                page_data: List[str] = [ str(d["id"]) + " - " + str(d["name"]) for d in resp_data ]
                
                p: Pages = Pages(ctx, entries=page_data, per_page=20)
                p.embed.title = "Available Languages"
                p.embed.description = "Listed id - language. Use the ID for other commands."

                await p.paginate()

    @godbolt.command(name="compilers")
    async def godbolt_compilers(self, ctx: commands.Context, language: str) -> None:
        """
        Lists all of the compilers available for a given language.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(self._endpoint(f"/api/compilers/{language}"),
                        headers={"accept": "application/json"}) as resp:
                resp_data: List[Dict[str, str]] = await resp.json()
                page_data: List[str] = [ str(d["id"]) + " - " + str(d["name"]) for d in resp_data ]

                p: Pages = Pages(ctx, entries=page_data, per_page=20)
                p.embed.title = f"Available Compilers ({language})"
                p.embed.description = "Listed id - compiler name. Use the ID for other commands."

                await p.paginate()

    def _unpack_raw(self, raw: str) -> Tuple[str, str, str]:
        start_idx: int = raw.find("```")
        
        if start_idx < 0:
            raise ValueError("Invalid source code format given. Please encode the source code in code blocks.")

        start_idx += 3
        end_idx: int = raw.find("```", start_idx)

        if end_idx < 0:
            raise ValueError("Invalid source code format given. Please encode the source code in code blocks.")

        args: str = raw[0:start_idx] or ""
        raw = raw[start_idx:end_idx]
        
        match: Optional[re.Match] = re.match(r"\w+", raw)
        if not match:
            raise ValueError("Language not specified, as expected per format.")

        lang_end: int = match.span()[1]
        lang: str = raw[0:lang_end]
        source: str = raw[lang_end + 1:end_idx]

        return lang, args, source

    def _to_codeblock(self, data: List[Dict[str, str]], limit: int=500) -> str:
        if not len(data):
            return ""

        content: str = "\n".join([ d["text"] for d in data ])

        return f"```\n{content[:limit]}```"

    @godbolt.command(name="run")
    async def godbolt_run(self, ctx: commands.Context, compiler: str, comp_args: str, *, raw) -> None:
        """
        Executes the given input with the specified compiler. The code must be placed inside of code
        blocks. Use the "compilers" command to determine which compilers are used for which languages.

        For example, this will compile the code with GCC 8.2 with C++ (using flags O3 and Wall):
        !godbolt run c++ g82 -O3 -Wall ```c++
        #include <stdio.h>
        int main() { printf("hi"); }
        ```
        """
        try:
            lang, args, source = self._unpack_raw(raw)
        except ValueError as err:
            await ctx.send(f"Error in formatting. {err}")
            return

        compiler_settings: CompilerOptions = CompilerOptions.default_execute(comp_args=args)
        data: RequestData = RequestData(source, compiler, lang, compiler_settings)

        async with aiohttp.ClientSession() as session:
            async with session.post(self._endpoint(f"/api/compiler/{compiler}/compile"),
                        headers={"accept": "application/json"}, json=asdict(data)) as resp:
                resp_data: Dict[str, Any] = await resp.json()

                if resp_data["didExecute"]:
                    build_result: str = "Execution successful."
                    stdout: str = self._to_codeblock(resp_data["stdout"])
                    stderr: str = self._to_codeblock(resp_data["stderr"])
                    exit_code: int = resp_data["code"]
                else:
                    build_result = "**Compilation failed.**"
                    stdout = self._to_codeblock(resp_data["buildResult"]["stdout"])
                    stderr = self._to_codeblock(resp_data["buildResult"]["stderr"])
                    exit_code = resp_data["buildResult"]["code"]

                stdout = stdout or "EMPTY"
                stderr = stderr or "EMPTY"

                await ctx.send(f"{build_result}. Exit code: `{exit_code}`\nstdout:\n{stdout}\nstderr:\n{stderr}")

    @godbolt.command(name="dissassemble", aliases=["disas", "asm"])
    async def godbolt_asm(self, ctx: commands.Context, compiler: str, *, raw) -> None:
        """
        Disassembles the given input with the specified compiler. The code must be placed inside of code
        blocks. Use the "compilers" command to determine which compilers are used for which languages.

        For example, this will compile the code with GCC 8.2 with C++ (using flags O3 and Wall):
        !godbolt asm c++ g82 -O3 -Wall ```c++
        double square(int num) {
            return num * num;
        }
        ```
        """
        try:
            lang, args, source = self._unpack_raw(raw)
        except ValueError as err:
            await ctx.send(f"Error in formatting. {err}")
            return

        compiler_settings: CompilerOptions = CompilerOptions.default_disassembly()
        data: RequestData = RequestData(source, compiler, lang, compiler_settings)

        async with aiohttp.ClientSession() as session:
            async with session.post(self._endpoint(f"/api/compiler/{compiler}/compile"),
                        headers={"accept": "application/json"}, json=asdict(data)) as resp:
                resp_data: Dict[str, Any] = await resp.json()

                if resp_data["code"] == 0:
                    build_result: str = "Compilation successful."
                    output: str = self._to_codeblock(resp_data["asm"], 1500)
                else:
                    build_result = "**Compilation failed.**"
                    output = self._to_codeblock(resp_data["stderr"], 1500)

                await ctx.send(f"{build_result}\n{output}")
