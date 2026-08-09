import asyncio
import datetime
import logging
import random
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from tle import constants
from tle.util import (
    codeforces_api as cf,
    discord_common,
)

logger = logging.getLogger(__name__)


class DailyProblem(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Run daily problem job at 07:00 AM UTC+7 (Vietnam Time)
        self.daily_time = datetime.time(
            hour=7, minute=0, tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')
        )
        self.task = self.bot.loop.create_task(self._daily_loop())

    def cog_unload(self) -> None:
        self.task.cancel()

    @commands.group(brief='Quản lý Daily Problem', invoke_without_command=True)
    async def daily(self, ctx: commands.Context) -> None:
        """Quản lý bài tập hàng ngày tự động."""
        await ctx.send_help(ctx.command)

    @daily.command(brief='Bật Daily Problem tại kênh hiện tại', usage='[channel]')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def set(
        self, ctx: commands.Context, channel: discord.TextChannel = None
    ) -> None:
        channel = channel or ctx.channel
        await self.bot.user_db.set_daily_channel(ctx.guild.id, channel.id)
        await ctx.send(
            embed=discord_common.embed_success(
                f'Đã bật Daily Problem tại {channel.mention}. Bài tập sẽ được gửi mỗi ngày lúc 7:00 AM (VN).'  # noqa: E501
            )
        )

    @daily.command(brief='Tắt Daily Problem')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def off(self, ctx: commands.Context) -> None:
        rc = await self.bot.user_db.clear_daily_channel(ctx.guild.id)
        if rc:
            await ctx.send(embed=discord_common.embed_success('Đã tắt Daily Problem.'))
        else:
            await ctx.send(
                embed=discord_common.embed_alert('Daily Problem hiện chưa được bật.')
            )

    @daily.command(brief='Gửi Daily Problem ngay lập tức (dành cho Admin)')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def now(self, ctx: commands.Context) -> None:
        """Kích hoạt gửi bài Daily Problem ngay lập tức cho server hiện tại."""
        channel_id = await self.bot.user_db.get_daily_channel(ctx.guild.id)
        if not channel_id:
            await ctx.send(
                embed=discord_common.embed_alert(
                    'Bạn chưa set kênh cho Daily Problem! Hãy dùng `;daily set` trước.'
                )
            )
            return

        channel = (
            self.bot.get_channel(channel_id)
            or ctx.guild.get_channel(channel_id)
            or ctx.guild.get_thread(channel_id)
        )
        if not channel:
            await ctx.send(
                'Kênh đã được set không tồn tại hoặc bot không có quyền truy cập.'
            )
            return

        await ctx.send('Đang lấy dữ liệu và gửi bài Daily Problem...')
        await self._send_daily_problem_to_guild(ctx.guild.id, channel)

    async def _send_daily_problem_to_guild(
        self, guild_id: int, channel: discord.TextChannel
    ) -> None:
        # 1. Calculate average rating
        handles = await self.bot.user_db.get_handles_for_guild(guild_id)
        if not handles:
            await channel.send('Server hiện chưa có ai đăng ký handle Codeforces!')
            return

        users = []
        for _, handle in handles:
            try:
                user = await self.bot.user_db.fetch_cf_user(handle)
                if user and user.rating:
                    users.append(user)
            except Exception:
                continue

        if not users:
            avg_rating = 1000
        else:
            avg_rating = sum(u.rating for u in users) / len(users)

        # Round to nearest 100, clamp to [800, 3500]
        target_rating = round(avg_rating / 100) * 100
        target_rating = max(800, min(3500, target_rating))

        # 2. Get all submissions from these users to avoid solved problems
        solved_problem_names = set()
        for user in users:
            try:
                subs = await cf.user.status(handle=user.handle)
                for sub in subs:
                    if sub.verdict == 'OK':
                        solved_problem_names.add(sub.problem.name)
            except Exception as e:
                logger.warning(f'Error fetching status for {user.handle}: {e}')

        # 3. Pick a random problem that has the target_rating and is unsolved
        available_problems = [
            prob
            for prob in self.bot.cf_cache.problem_cache.problems
            if prob.rating == target_rating and prob.name not in solved_problem_names
        ]

        if not available_problems:
            await channel.send(
                f'Không tìm thấy bài nào rating {target_rating} mà server chưa giải!'
            )
            return

        problem = random.choice(available_problems)

        # 4. Send the embed
        embed = discord.Embed(
            title=f'{problem.index}. {problem.name}',
            url=f'https://codeforces.com/contest/{problem.contestId}/problem/{problem.index}',  # noqa: E501
            color=cf.rating2rank(target_rating).color_embed
            if target_rating
            else discord_common._SUCCESS_GREEN,
            description=f'Rating trung bình của server là khoảng **{target_rating}**.\nĐây là bài tập dành cho hôm nay!',  # noqa: E501
        )
        embed.set_author(name='📅 Daily Problem')
        embed.add_field(name='Rating', value=str(problem.rating), inline=True)
        if problem.tags:
            embed.add_field(name='Tags', value=', '.join(problem.tags), inline=True)

        await channel.send(embed=embed)

    async def _daily_loop(self) -> None:
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            now = datetime.datetime.now(ZoneInfo('Asia/Ho_Chi_Minh'))
            target_time = now.replace(
                hour=self.daily_time.hour,
                minute=self.daily_time.minute,
                second=self.daily_time.second,
                microsecond=0,
            )

            if now >= target_time:
                # If we passed the time today, wait for tomorrow
                target_time += datetime.timedelta(days=1)

            sleep_seconds = (target_time - now).total_seconds()
            logger.info(f'Next Daily Problem scheduled in {sleep_seconds} seconds.')

            await asyncio.sleep(sleep_seconds)

            # Time to send daily problem!
            try:
                configs = await self.bot.user_db.get_all_daily_channels()
                for guild_id, channel_id in configs:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue
                    channel = (
                        self.bot.get_channel(channel_id)
                        or guild.get_channel(channel_id)
                        or guild.get_thread(channel_id)
                    )
                    if not channel:
                        continue

                    # Send problem, with a bit of sleep to avoid rate limits if many guilds  # noqa: E501
                    await self._send_daily_problem_to_guild(guild_id, channel)
                    await asyncio.sleep(5)
            except Exception as e:
                logger.exception(f'Error in Daily Problem loop: {e}')


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyProblem(bot))
