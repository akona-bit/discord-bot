import asyncio
import datetime
import logging
import random
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from tle import constants
from tle.util import codeforces_api as cf, discord_common

logger = logging.getLogger(__name__)


class Weekly(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Run weekly job on Monday 00:00 AM UTC+7
        self.task = self.bot.loop.create_task(self._weekly_loop())

    def cog_unload(self) -> None:
        self.task.cancel()

    @commands.group(brief='Thử thách hàng tuần', invoke_without_command=True)
    async def weekly(self, ctx: commands.Context) -> None:
        """Xem bài tập thử thách của tuần này."""
        challenge = await self.bot.user_db.get_weekly_challenge(ctx.guild.id)
        if not challenge:
            await ctx.send(
                embed=discord_common.embed_neutral(
                    'Tuần này chưa có bài thử thách nào! Hãy đợi bot chọn hoặc yêu cầu admin dùng lệnh `;weekly set`.'  # noqa: E501
                )
            )
            return

        channel_id, problem_name, contest_id, p_index, start_time, end_time = challenge

        embed = discord.Embed(
            title=f'🎯 Thử thách tuần này: {p_index}. {problem_name}',
            url=f'https://codeforces.com/contest/{contest_id}/problem/{p_index}',
            color=discord_common._SUCCESS_GREEN,
            description='Hãy giải bài tập này trong tuần để nhận **100 XP**!',
        )
        end_date = datetime.datetime.fromtimestamp(
            end_time, ZoneInfo('Asia/Ho_Chi_Minh')
        )
        embed.set_footer(text=f'Kết thúc vào: {end_date.strftime("%d/%m/%Y %H:%M")}')

        await ctx.send(embed=embed)

    @weekly.command(brief='Kiểm tra hoàn thành thử thách')
    async def check(self, ctx: commands.Context) -> None:
        """Kiểm tra xem bạn đã giải được bài tuần này chưa và nhận XP."""
        challenge = await self.bot.user_db.get_weekly_challenge(ctx.guild.id)
        if not challenge:
            await ctx.send(
                embed=discord_common.embed_alert('Tuần này không có thử thách!')
            )
            return

        _, problem_name, contest_id, p_index, start_time, end_time = challenge

        handle = await self.bot.user_db.get_handle(ctx.author.id, ctx.guild.id)
        if not handle:
            await ctx.send(
                embed=discord_common.embed_alert('Bạn chưa liên kết handle Codeforces!')
            )
            return

        # We need to check if user solved it THIS WEEK (between start_time and end_time)
        try:
            subs = await cf.user.status(handle=handle, count=50)  # only recent subs
            solved = False
            for sub in subs:
                if sub.verdict == 'OK' and sub.problem.name == problem_name:
                    if start_time <= sub.creationTimeSeconds <= end_time:
                        solved = True
                        break
        except Exception:
            await ctx.send(
                embed=discord_common.embed_alert(
                    'Lỗi khi lấy dữ liệu từ Codeforces API.'
                )
            )
            return

        if not solved:
            await ctx.send(
                embed=discord_common.embed_alert(
                    f'Bạn chưa giải được bài **{problem_name}** trong tuần này. Cố lên nhé!'  # noqa: E501
                )
            )
            return

        # Give XP
        new_xp, new_level, leveled_up = await self.bot.user_db.add_xp(
            ctx.author.id, 100
        )

        msg = f'🎉 Chúc mừng {ctx.author.mention}! Bạn đã hoàn thành thử thách tuần và nhận được **100 XP**.'  # noqa: E501
        if leveled_up:
            msg += f'\n⭐ Bạn đã thăng cấp lên **Level {new_level}**!'

        await ctx.send(embed=discord_common.embed_success(msg))

    @weekly.command(brief='Admin tự thiết lập bài (nếu cần)')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def set(self, ctx: commands.Context, contest_id: int, p_index: str) -> None:
        """Kích hoạt bot tự động chọn bài ngay bây giờ."""
        await ctx.send(
            'Tính năng tự động chọn bài đang được kích hoạt cho server này...'
        )
        await self._roll_weekly_challenge(ctx.guild)
        await ctx.send('Đã tạo thử thách mới! Dùng lệnh `;weekly` để xem.')

    async def _roll_weekly_challenge(self, guild: discord.Guild) -> None:
        # Calculate target rating (avg + 200 to make it challenging)
        handles = await self.bot.user_db.get_handles_for_guild(guild.id)
        if not handles:
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
            target_rating = 1200
        else:
            avg_rating = sum(u.rating for u in users) / len(users)
            target_rating = round((avg_rating + 200) / 100) * 100

        # Pick a random problem
        available_problems = [
            prob
            for prob in self.bot.cf_cache.problem_cache.problems
            if prob.rating == target_rating
        ]

        if not available_problems:
            return
        problem = random.choice(available_problems)

        tz = ZoneInfo('Asia/Ho_Chi_Minh')
        now = datetime.datetime.now(tz)
        start_time = now.timestamp()

        # End time is next Monday
        days_ahead = 7 - now.weekday()
        if days_ahead == 0:
            days_ahead = 7
        next_monday = (now + datetime.timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_time = next_monday.timestamp()

        # Save to DB. By default we just use guild's system channel if exists, else 0
        channel_id = guild.system_channel.id if guild.system_channel else 0
        await self.bot.user_db.set_weekly_challenge(
            guild.id,
            channel_id,
            problem.name,
            problem.contestId,
            problem.index,
            start_time,
            end_time,
        )

        # Send announcement
        if channel_id != 0:
            channel = (
                self.bot.get_channel(channel_id)
                or guild.get_channel(channel_id)
                or guild.get_thread(channel_id)
            )
            if channel:
                embed = discord.Embed(
                    title=f'🎯 THỬ THÁCH TUẦN MỚI: {problem.index}. {problem.name}',
                    url=f'https://codeforces.com/contest/{problem.contestId}/problem/{problem.index}',  # noqa: E501
                    color=discord_common._SUCCESS_GREEN,
                    description=f'Bài tập tuần này có rating **{target_rating}**.\nGiải bài này trong tuần và dùng lệnh `;weekly check` để nhận **100 XP**!',  # noqa: E501
                )
                await channel.send(embed=embed)

    async def _weekly_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            tz = ZoneInfo('Asia/Ho_Chi_Minh')
            now = datetime.datetime.now(tz)

            # Find next Monday 00:00
            days_ahead = 7 - now.weekday()
            if days_ahead == 0 and now.hour == 0 and now.minute == 0:
                pass  # It's exactly now, proceed
            else:
                next_monday = (now + datetime.timedelta(days=days_ahead)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                sleep_seconds = (next_monday - now).total_seconds()
                logger.info(f'Next Weekly Challenge in {sleep_seconds} seconds.')
                await asyncio.sleep(sleep_seconds)

            # Roll for all guilds
            try:
                for guild in self.bot.guilds:
                    # Check if they want weekly challenge? Currently we roll for all guilds  # noqa: E501
                    await self._roll_weekly_challenge(guild)
                    await asyncio.sleep(5)
            except Exception as e:
                logger.exception(f'Error in Weekly Challenge loop: {e}')

            # Sleep 1 day to avoid re-triggering on same Monday
            await asyncio.sleep(86400)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Weekly(bot))
