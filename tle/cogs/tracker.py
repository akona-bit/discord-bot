# ruff: noqa: E501
import asyncio
import logging
from collections import defaultdict

import discord
from discord.ext import commands

from tle import constants
from tle.util import (
    codeforces_api as cf,
    discord_common,
)

logger = logging.getLogger(__name__)


class TrackerCogError(commands.CommandError):
    pass


class Tracker(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Track the latest submission time (creationTimeSeconds) per handle
        self.last_submission_times: dict[str, int] = {}

        self.tracker_task = self.bot.loop.create_task(self._tracker_loop())

    def cog_unload(self) -> None:
        self.tracker_task.cancel()

    @commands.group(brief='Bảng Vàng Tự Động', invoke_without_command=True)
    async def tracker(self, ctx: commands.Context) -> None:
        """Quản lý tính năng tự động gửi thông báo khi có người nộp bài Accepted (Bảng vàng)."""  # noqa: E501
        await ctx.send_help(ctx.command)

    @tracker.command(brief='Bật theo dõi Bảng vàng', usage='[channel]')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def set(
        self, ctx: commands.Context, channel: discord.TextChannel = None
    ) -> None:
        """Kích hoạt Bảng vàng tại kênh được chỉ định (mặc định là kênh hiện tại)."""
        channel = channel or ctx.channel
        await self.bot.user_db.set_tracker_channel(ctx.guild.id, channel.id)
        await ctx.send(
            embed=discord_common.embed_success(
                f'Đã kích hoạt Bảng vàng tự động tại {channel.mention}'
            )
        )

    @tracker.command(brief='Tắt theo dõi Bảng vàng')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def off(self, ctx: commands.Context) -> None:
        """Tắt tính năng thông báo Bảng vàng."""
        rc = await self.bot.user_db.clear_tracker_channel(ctx.guild.id)
        if rc:
            await ctx.send(
                embed=discord_common.embed_success('Đã tắt Bảng vàng tự động.')
            )
        else:
            await ctx.send(
                embed=discord_common.embed_alert('Bảng vàng hiện chưa được bật.')
            )

    async def _send_ac_notification(
        self, guild_id: int, channel_id: int, handle: str, sub: cf.Submission
    ) -> None:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        user = await self.bot.user_db.fetch_cf_user(handle)

        problem = sub.problem
        problem_name = f'{problem.index}. {problem.name}'
        problem_url = f'https://codeforces.com/contest/{problem.contestId}/problem/{problem.index}'  # noqa: E501

        embed = discord.Embed(
            title=problem_name,
            url=problem_url,
            color=cf.rating2rank(user.rating).color_embed
            if user
            else discord_common._SUCCESS_GREEN,
            description=f'**{handle}** vừa giải thành công bài tập này!',
        )
        embed.set_author(name='🎉 AC Mới!')

        if problem.rating:
            embed.add_field(name='Rating', value=str(problem.rating), inline=True)
        if problem.tags:
            embed.add_field(name='Tags', value=', '.join(problem.tags), inline=True)

        embed.set_footer(text=f'Ngôn ngữ: {sub.programmingLanguage}')

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning(
                f'Không có quyền gửi tin nhắn vào kênh {channel_id} ở {guild_id}'
            )

    async def _tracker_loop(self) -> None:
        """Background task to poll Codeforces for new Accepted submissions."""
        await self.bot.wait_until_ready()

        # Wait a bit before starting the loop to let caches populate
        await asyncio.sleep(10)

        while not self.bot.is_closed():
            try:
                # 1. Fetch all configured tracker channels
                tracker_configs = await self.bot.user_db.get_all_tracker_channels()
                if not tracker_configs:
                    await asyncio.sleep(60)
                    continue

                # 2. Collect all handles that need to be tracked
                # Mapping from handle to list of (guild_id, channel_id)
                handle_subscribers: dict[str, list[tuple[int, int]]] = defaultdict(list)

                for guild_id, channel_id in tracker_configs:
                    handles = await self.bot.user_db.get_handles_for_guild(guild_id)
                    for _user_id, handle in handles:
                        handle_subscribers[handle].append((guild_id, channel_id))

                # 3. Poll each handle slowly
                for handle, subscribers in handle_subscribers.items():
                    try:
                        subs = await cf.user.status(handle=handle, count=5)
                    except cf.CodeforcesApiError as e:
                        logger.warning(f'CF API Error polling status for {handle}: {e}')
                        await asyncio.sleep(2)
                        continue
                    except Exception as e:
                        logger.warning(f'Unexpected error polling {handle}: {e}')
                        await asyncio.sleep(2)
                        continue

                    if not subs:
                        await asyncio.sleep(2)
                        continue

                    # Sort submissions by creation time (oldest to newest)
                    subs.sort(key=lambda x: x.creationTimeSeconds)

                    is_first_time = handle not in self.last_submission_times

                    for sub in subs:
                        # Skip if it's not a new submission
                        if sub.creationTimeSeconds <= self.last_submission_times.get(
                            handle, 0
                        ):
                            continue

                        # Update the latest seen submission time
                        self.last_submission_times[handle] = sub.creationTimeSeconds

                        # Only notify if it's Accepted and it's not the first time we're seeding the tracker  # noqa: E501
                        if not is_first_time and sub.verdict == 'OK':
                            for guild_id, channel_id in subscribers:
                                await self._send_ac_notification(
                                    guild_id, channel_id, handle, sub
                                )

                    # Sleep for 2.5 seconds between requests to strictly respect CF rate limits (1 req/sec limit)  # noqa: E501
                    await asyncio.sleep(2.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f'Error in tracker loop: {e}')
                await asyncio.sleep(60)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tracker(bot))
