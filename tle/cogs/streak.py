import datetime
import logging
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from tle.util import codeforces_api as cf, discord_common

logger = logging.getLogger(__name__)


class Streak(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(brief='Xem chuỗi ngày giải bài (Streak)', usage='[handle]')
    async def streak(self, ctx: commands.Context, handle: str = None) -> None:
        """Đếm chuỗi ngày liên tiếp có ít nhất 1 bài Accepted trên Codeforces.
        Nếu không chỉ định handle, sẽ dùng handle đã liên kết
        với tài khoản Discord của bạn.
        """
        if not handle:
            user_id = ctx.author.id
            handle = await self.bot.user_db.get_handle(user_id, ctx.guild.id)
            if not handle:
                await ctx.send(
                    embed=discord_common.embed_alert(
                        'Bạn chưa liên kết tài khoản Codeforces! Dùng lệnh `;handle set <handle>`.'  # noqa: E501
                    )
                )
                return

        await ctx.send(f'Đang tính toán streak cho **{handle}**...')

        try:
            subs = await cf.user.status(handle=handle)
        except cf.CodeforcesApiError as e:
            await ctx.send(
                embed=discord_common.embed_alert(f'Lỗi từ Codeforces API: {e}')
            )
            return
        except Exception as e:
            await ctx.send(
                embed=discord_common.embed_alert('Có lỗi xảy ra khi lấy dữ liệu!')
            )
            logger.exception(f'Error fetching status for {handle}: {e}')
            return

        if not subs:
            await ctx.send(
                embed=discord_common.embed_alert(
                    f'{handle} chưa nộp bài nào trên Codeforces!'
                )
            )
            return

        # Filter only AC submissions
        ac_subs = [sub for sub in subs if sub.verdict == 'OK']

        if not ac_subs:
            await ctx.send(
                embed=discord_common.embed_alert(f'{handle} chưa có bài nào Accepted!')
            )
            return

        # Group ACs by Date (in UTC+7)
        tz = ZoneInfo('Asia/Ho_Chi_Minh')
        ac_dates = set()
        for sub in ac_subs:
            dt = datetime.datetime.fromtimestamp(sub.creationTimeSeconds, tz)
            ac_dates.add(dt.date())

        sorted_dates = sorted(list(ac_dates), reverse=True)

        current_streak = 0
        max_streak = 0
        temp_streak = 0

        # Calculate max streak
        for i in range(len(sorted_dates)):
            if i == 0:
                temp_streak = 1
            else:
                diff = (sorted_dates[i - 1] - sorted_dates[i]).days
                if diff == 1:
                    temp_streak += 1
                else:
                    max_streak = max(max_streak, temp_streak)
                    temp_streak = 1
        max_streak = max(max_streak, temp_streak)

        # Calculate current streak
        today = datetime.datetime.now(tz).date()
        yesterday = today - datetime.timedelta(days=1)

        if sorted_dates[0] == today or sorted_dates[0] == yesterday:
            current_streak = 1
            for i in range(1, len(sorted_dates)):
                if (sorted_dates[i - 1] - sorted_dates[i]).days == 1:
                    current_streak += 1
                else:
                    break
        else:
            current_streak = 0

        # Build Embed
        user_info = await self.bot.user_db.fetch_cf_user(handle)
        color = (
            cf.rating2rank(user_info.rating).color_embed
            if user_info and user_info.rating
            else discord_common._DEFAULT_COLOR
        )

        embed = discord.Embed(
            title=f'🔥 Thống kê Streak của {handle}',
            url=f'https://codeforces.com/profile/{handle}',
            color=color,
        )

        if user_info and user_info.avatar:
            embed.set_thumbnail(url=user_info.avatar)

        # Progress bar emoji representation
        flames = '🔥' * min(current_streak, 10)
        if current_streak == 0:
            flames = '🧊 Đã đóng băng'
        elif current_streak > 10:
            flames += '...'

        embed.add_field(
            name='Streak Hiện Tại',
            value=f'**{current_streak}** ngày\n{flames}',
            inline=True,
        )
        embed.add_field(
            name='Kỷ Lục Streak', value=f'**{max_streak}** ngày', inline=True
        )
        embed.add_field(
            name='Tổng Ngày AC', value=f'**{len(ac_dates)}** ngày', inline=False
        )

        if sorted_dates:
            embed.set_footer(
                text=f'Lần AC gần nhất: {sorted_dates[0].strftime("%d/%m/%Y")}'
            )

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Streak(bot))
