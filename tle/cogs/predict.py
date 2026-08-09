import logging

import discord
from discord.ext import commands

from tle.util import discord_common
from tle.util.ranklist.ranklist import RanklistError

logger = logging.getLogger(__name__)


class Predict(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(brief='Dự đoán rating sau contest', usage='<contest_id>')
    async def predict(self, ctx: commands.Context, contest_id: int) -> None:
        """Tính toán rating delta dựa trên ranklist hiện tại của contest."""
        handles = await self.bot.user_db.get_handles_for_guild(ctx.guild.id)
        if not handles:
            await ctx.send(
                embed=discord_common.embed_alert(
                    'Server chưa có ai đăng ký handle Codeforces!'
                )
            )
            return

        guild_handles = {handle for _, handle in handles}

        msg = await ctx.send(
            f'Đang tính toán dự đoán rating cho cuộc thi {contest_id}...\n*(Quá trình này có thể mất thời gian nếu server Codeforces phản hồi chậm)*'  # noqa: E501
        )

        try:
            ranklist = await self.bot.cf_cache.ranklist_cache.generate_ranklist(
                contest_id,
                fetch_changes=False,
                predict_changes=True,
                show_unofficial=False,
            )
        except RanklistError as e:
            await msg.edit(content=f'Lỗi Ranklist: {e}')
            return
        except Exception as e:
            logger.exception(f'Error predicting rating: {e}')
            await msg.edit(content='Có lỗi xảy ra khi dự đoán rating.')
            return

        if ranklist.deltas_status != 'Predicted':
            await msg.edit(
                content=f'Không thể dự đoán contest này. Trạng thái: {ranklist.deltas_status}'  # noqa: E501
            )
            return

        embed = discord.Embed(
            title=f'Dự đoán Rating: {ranklist.contest.name}',
            url=f'https://codeforces.com/contest/{contest_id}',
            color=discord_common._SUCCESS_GREEN,
        )

        results = []
        for handle in guild_handles:
            try:
                row = ranklist.get_standing_row(handle)
                delta = ranklist.get_delta(handle)
                if delta is not None:
                    results.append((handle, row.rank, delta))
            except RanklistError:
                pass

        if not results:
            await msg.edit(
                content='Không có ai trong server này tham gia (hoặc có mặt trên ranklist official) của cuộc thi này!'  # noqa: E501
            )
            return

        # Sort by rank
        results.sort(key=lambda x: x[1])

        desc = ''
        for handle, rank, delta in results:
            sign = '+' if delta > 0 else ''
            desc += f'`#{rank:<4}` **[{handle}](https://codeforces.com/profile/{handle})** : {sign}{delta}\n'  # noqa: E501

        embed.description = desc
        embed.set_footer(text='Dự đoán chỉ mang tính tham khảo.')

        await msg.delete()
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Predict(bot))
