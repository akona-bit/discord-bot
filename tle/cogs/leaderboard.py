import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from tle.util import codeforces_api as cf, discord_common

logger = logging.getLogger(__name__)


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get_ac_count(self, handle: str, since_ts: float) -> int:
        """Fetch AC count for a handle since since_ts (timestamp)."""
        try:
            # We only need recent submissions. 200 is more than enough for a week or month.  # noqa: E501
            subs = await cf.user.status(handle=handle, count=300)
            ac_count = 0
            solved_problems = set()
            for sub in subs:
                if sub.creationTimeSeconds < since_ts:
                    break  # Since it's ordered by time descending (newest first)
                if sub.verdict == 'OK':
                    # Ensure unique problems
                    prob_id = f'{sub.problem.contestId}{sub.problem.index}'
                    if prob_id not in solved_problems:
                        solved_problems.add(prob_id)
                        ac_count += 1
            return ac_count
        except Exception as e:
            logger.warning(f'Error fetching status for {handle}: {e}')
            return 0

    @commands.group(brief='Bảng xếp hạng giải bài', invoke_without_command=True)
    async def lb(self, ctx: commands.Context) -> None:
        """Xem bảng xếp hạng số bài AC của server. Dùng lệnh con: week, month."""
        await ctx.send_help(ctx.command)

    async def _generate_leaderboard(
        self, ctx: commands.Context, duration: str, since_ts: float
    ) -> None:
        handles = await self.bot.user_db.get_handles_for_guild(ctx.guild.id)
        if not handles:
            await ctx.send(
                embed=discord_common.embed_alert(
                    'Server chưa có ai đăng ký handle Codeforces!'
                )
            )
            return

        msg = await ctx.send(
            f'Đang tính toán bảng xếp hạng cho {len(handles)} người dùng. Việc này có thể mất vài chục giây...'  # noqa: E501
        )

        user_ac = []
        # Process in chunks to avoid blocking and respect rate limits
        chunk_size = 5
        for i in range(0, len(handles), chunk_size):
            chunk = handles[i : i + chunk_size]
            tasks = [self._get_ac_count(handle, since_ts) for _, handle in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (_user_id, handle), ac_count in zip(chunk, results, strict=False):
                if isinstance(ac_count, int) and ac_count > 0:
                    user_ac.append((handle, ac_count))

            await asyncio.sleep(1)  # Rate limiting safety

        if not user_ac:
            await msg.edit(
                content=f'Trong {duration} qua chưa ai trong server giải được bài nào! 🧊'  # noqa: E501
            )
            return

        # Sort by AC descending
        user_ac.sort(key=lambda x: x[1], reverse=True)
        top_10 = user_ac[:10]

        desc = ''
        medals = ['🥇', '🥈', '🥉']
        for i, (handle, ac) in enumerate(top_10):
            rank = medals[i] if i < 3 else f'**#{i + 1}**'
            desc += f'{rank} **[{handle}](https://codeforces.com/profile/{handle})**: {ac} bài AC\n'  # noqa: E501

        embed = discord.Embed(
            title=f'🏆 Bảng Xếp Hạng AC ({duration})',
            description=desc,
            color=discord_common._SUCCESS_GREEN,
        )
        embed.set_footer(text=f'Bao gồm {len(user_ac)} người dùng có AC.')
        await msg.edit(content=None, embed=embed)

    @lb.command(brief='Bảng xếp hạng tuần này')
    async def week(self, ctx: commands.Context) -> None:
        """Bảng xếp hạng số bài AC tính từ đầu tuần (thứ 2)."""
        tz = ZoneInfo('Asia/Ho_Chi_Minh')
        now = datetime.datetime.now(tz)
        # Find the most recent Monday
        monday = now - datetime.timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        await self._generate_leaderboard(ctx, 'tuần này', monday.timestamp())

    @lb.command(brief='Bảng xếp hạng tháng này')
    async def month(self, ctx: commands.Context) -> None:
        """Bảng xếp hạng số bài AC tính từ đầu tháng."""
        tz = ZoneInfo('Asia/Ho_Chi_Minh')
        now = datetime.datetime.now(tz)
        first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        await self._generate_leaderboard(ctx, 'tháng này', first_day.timestamp())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leaderboard(bot))
