import logging

import discord
from discord.ext import commands

from tle.util import codeforces_api as cf, discord_common

logger = logging.getLogger(__name__)


class Compare(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(brief='So sánh 2 user', usage='<handle1> <handle2>')
    async def compare(self, ctx: commands.Context, handle1: str, handle2: str) -> None:
        """So sánh các chỉ số của 2 người dùng Codeforces (rating, AC count...)."""
        msg = await ctx.send(
            f'Đang lấy dữ liệu so sánh giữa **{handle1}** và **{handle2}**...'
        )

        try:
            users = await cf.user.info(handles=[handle1, handle2])
            if len(users) != 2:
                await msg.edit(content='Không tìm thấy đủ 2 handle trên Codeforces!')
                return

            u1, u2 = users[0], users[1]

            # Fetch subs to count ACs
            subs1 = await cf.user.status(handle=handle1)
            subs2 = await cf.user.status(handle=handle2)

            ac1 = len(
                set(
                    f'{s.problem.contestId}{s.problem.index}'
                    for s in subs1
                    if s.verdict == 'OK'
                )
            )
            ac2 = len(
                set(
                    f'{s.problem.contestId}{s.problem.index}'
                    for s in subs2
                    if s.verdict == 'OK'
                )
            )

            # Formatting
            r1 = u1.rating or 0
            r2 = u2.rating or 0
            mr1 = u1.maxRating or 0
            mr2 = u2.maxRating or 0

            def get_emoji(v1: int, v2: int) -> tuple[str, str]:
                if v1 > v2:
                    return '🏆', ''
                if v2 > v1:
                    return '', '🏆'
                return '🤝', '🤝'

            e_r1, e_r2 = get_emoji(r1, r2)
            e_mr1, e_mr2 = get_emoji(mr1, mr2)
            e_ac1, e_ac2 = get_emoji(ac1, ac2)

            embed = discord.Embed(
                title=f'⚔️ So sánh: {u1.handle} vs {u2.handle}',
                color=discord_common._SUCCESS_GREEN,
            )

            embed.add_field(
                name='Chỉ số',
                value='**Rating hiện tại**\n**Max Rating**\n**Tổng bài AC**',
                inline=True,
            )
            embed.add_field(
                name=u1.handle,
                value=f'{r1} {e_r1}\n{mr1} {e_mr1}\n{ac1} {e_ac1}',
                inline=True,
            )
            embed.add_field(
                name=u2.handle,
                value=f'{e_r2} {r2}\n{e_mr2} {mr2}\n{e_ac2} {ac2}',
                inline=True,
            )

            embed.set_footer(text='Số bài AC chỉ tính các bài duy nhất.')

            await msg.delete()
            await ctx.send(embed=embed)

        except cf.CodeforcesApiError as e:
            await msg.edit(content=f'Lỗi API Codeforces: {e}')
        except Exception as e:
            logger.exception(f'Error comparing users: {e}')
            await msg.edit(content='Có lỗi xảy ra khi lấy dữ liệu so sánh!')


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Compare(bot))
