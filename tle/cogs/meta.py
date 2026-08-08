import os
import subprocess
import sys
import textwrap
import time

from discord.ext import commands

from tle import constants
from tle.util.codeforces_common import pretty_time_format


# Adapted from numpy sources.
# https://github.com/numpy/numpy/blob/master/setup.py#L64-85
def git_history() -> str:
    def _minimal_ext_cmd(cmd: list[str]) -> bytes:
        # construct minimal environment
        env = {}
        for k in ['SYSTEMROOT', 'PATH']:
            v = os.environ.get(k)
            if v is not None:
                env[k] = v
        # LANGUAGE is used on win32
        env['LANGUAGE'] = 'C'
        env['LANG'] = 'C'
        env['LC_ALL'] = 'C'
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env)
        out = proc.communicate(timeout=10)[0]
        return out

    try:
        out = _minimal_ext_cmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        branch = out.strip().decode('ascii')
        out = _minimal_ext_cmd(['git', 'log', '--oneline', '-5'])
        history = out.strip().decode('ascii')
        return (
            'Branch:\n'
            + textwrap.indent(branch, '  ')
            + '\nCommits:\n'
            + textwrap.indent(history, '  ')
        )
    except OSError:
        return 'Fetching git info failed'


class Meta(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.start_time = time.time()

    @commands.hybrid_group(brief='Điều khiển bot', fallback='show')
    async def meta(self, ctx: commands.Context) -> None:
        """Command the bot or get information about the bot."""
        await ctx.send_help(ctx.command)

    @meta.command(brief='Tắt TLE')
    @commands.has_role(constants.TLE_ADMIN)
    async def kill(self, ctx: commands.Context) -> None:
        """Tắt bot một cách trơn tru."""
        await ctx.send('Đang tắt...')
        await self.bot.close()
        sys.exit(0)

    @meta.command(brief='TLE còn hoạt động?')
    async def ping(self, ctx: commands.Context) -> None:
        """Phản hồi với một ping."""
        start = time.perf_counter()
        message = await ctx.send(':ping_pong: Pong!')
        end = time.perf_counter()
        duration = (end - start) * 1000
        await message.edit(
            content=(
                f'Độ trễ REST API: {int(duration)}ms\n'
                f'Độ trễ Gateway API: {int(self.bot.latency * 1000)}ms'
            )
        )

    @meta.command(brief='Lấy thông tin git')
    async def git(self, ctx: commands.Context) -> None:
        """Trả về thông tin git."""
        await ctx.send('```yaml\n' + git_history() + '```')

    @meta.command(brief='Hiển thị thời gian chạy bot')
    async def uptime(self, ctx: commands.Context) -> None:
        """Trả về thời gian bot đã chạy."""
        await ctx.send(
            'TLE đã chạy trong '
            + pretty_time_format(time.time() - self.start_time)
        )

    @meta.command(brief='Liệt kê server bot')
    @commands.has_role(constants.TLE_ADMIN)
    async def guilds(self, ctx: commands.Context) -> None:
        """Trả về thông tin các server mà bot tham gia"""
        msg = [
            ' | '.join(
                [
                    f'ID Server: {guild.id}',
                    f'Tên: {guild.name}',
                    f'Chủ sở hữu: {guild.owner.id}',
                    f'Icon: {guild.icon.url if guild.icon else None}',
                ]
            )
            for guild in self.bot.guilds
        ]
        await ctx.send('```' + '\n'.join(msg) + '```')


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meta(bot))
