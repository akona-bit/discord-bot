import datetime
import logging
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from tle.util import codeforces_api as cf, discord_common

logger = logging.getLogger(__name__)

# List of defined badges with their criteria
BADGE_DEFINITIONS = {
    'First Blood': 'Giải được bài tập đầu tiên',
    'Centurion': 'Giải được 100 bài tập',
    'Grandmaster': 'Giải được 500 bài tập',
    'Dedicated': 'Đạt chuỗi streak 7 ngày liên tiếp',
    'Specialist': 'Đạt rating 1400+',
    'Expert': 'Đạt rating 1600+',
    'Candidate Master': 'Đạt rating 1900+',
}


class Achievements(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _check_and_award_badges(
        self, ctx: commands.Context, user_id: int, handle: str
    ) -> list[str]:
        """Check all badges for a user and award new ones."""
        new_badges = []
        try:
            # 1. Fetch user data
            user = await self.bot.user_db.fetch_cf_user(handle)
            subs = await cf.user.status(handle=handle)
            ac_subs = [s for s in subs if s.verdict == 'OK']

            # Unique AC count
            unique_ac = len(
                set(f'{s.problem.contestId}{s.problem.index}' for s in ac_subs)
            )

            # 2. Check criteria
            earned = set()
            if unique_ac >= 1:
                earned.add('First Blood')
            if unique_ac >= 100:
                earned.add('Centurion')
            if unique_ac >= 500:
                earned.add('Grandmaster')

            if user and user.rating:
                if user.rating >= 1400:
                    earned.add('Specialist')
                if user.rating >= 1600:
                    earned.add('Expert')
                if user.rating >= 1900:
                    earned.add('Candidate Master')

            # 3. Calculate streak for 'Dedicated' badge
            tz = ZoneInfo('Asia/Ho_Chi_Minh')
            ac_dates = sorted(
                list(
                    set(
                        datetime.datetime.fromtimestamp(
                            s.creationTimeSeconds, tz
                        ).date()
                        for s in ac_subs
                    )
                ),
                reverse=True,
            )
            max_streak = 0
            temp_streak = 0
            for i in range(len(ac_dates)):
                if i == 0:
                    temp_streak = 1
                else:
                    diff = (ac_dates[i - 1] - ac_dates[i]).days
                    if diff == 1:
                        temp_streak += 1
                    else:
                        max_streak = max(max_streak, temp_streak)
                        temp_streak = 1
            max_streak = max(max_streak, temp_streak)

            if max_streak >= 7:
                earned.add('Dedicated')

            # 4. Save to DB
            existing = set(await self.bot.user_db.get_achievements(user_id))
            now_ts = datetime.datetime.now().timestamp()

            for badge in earned:
                if badge not in existing:
                    added = await self.bot.user_db.add_achievement(
                        user_id, badge, now_ts
                    )
                    if added:
                        new_badges.append(badge)
                        # Add XP for new badge
                        await self.bot.user_db.add_xp(user_id, 50)

        except Exception as e:
            logger.warning(f'Error checking badges for {handle}: {e}')

        return new_badges

    @commands.command(brief='Xem hồ sơ, cấp độ và huy hiệu', usage='[member]')
    async def profile(
        self, ctx: commands.Context, member: discord.Member = None
    ) -> None:
        """Hiển thị hồ sơ cá nhân: cấp độ (Level), XP, và danh sách huy hiệu (Badges)."""  # noqa: E501
        member = member or ctx.author

        handle = await self.bot.user_db.get_handle(member.id, ctx.guild.id)
        if not handle:
            await ctx.send(
                embed=discord_common.embed_alert(
                    f'{member.display_name} chưa liên kết handle Codeforces!'
                )
            )
            return

        msg = await ctx.send(f'Đang tải hồ sơ của {member.display_name}...')

        # Check and award badges on the fly
        new_badges = await self._check_and_award_badges(ctx, member.id, handle)
        if new_badges:
            badge_str = ', '.join([f'**{b}**' for b in new_badges])
            await ctx.send(
                embed=discord_common.embed_success(
                    f'🎉 Chúc mừng {member.mention}! Bạn vừa mở khóa huy hiệu mới: {badge_str}!'  # noqa: E501
                )
            )

        # Get latest data
        xp, level = await self.bot.user_db.get_user_level(member.id)
        badges = await self.bot.user_db.get_achievements(member.id)

        try:
            cf_user = await self.bot.user_db.fetch_cf_user(handle)
            color = (
                cf.rating2rank(cf_user.rating).color_embed
                if cf_user.rating
                else discord_common._DEFAULT_COLOR
            )
            avatar = cf_user.avatar
        except Exception:
            color = discord_common._DEFAULT_COLOR
            avatar = member.display_avatar.url

        embed = discord.Embed(
            title=f'Hồ sơ của {member.display_name}',
            url=f'https://codeforces.com/profile/{handle}',
            color=color,
        )
        embed.set_thumbnail(url=avatar)

        # Calculate XP to next level
        # level = sqrt(xp/100) + 1 => xp = 100 * (level-1)^2
        xp_current_level = 100 * (level - 1) ** 2
        xp_next_level = 100 * (level) ** 2

        progress = (xp - xp_current_level) / (xp_next_level - xp_current_level)
        bar_length = 15
        filled = int(progress * bar_length)
        bar = '█' * filled + '░' * (bar_length - filled)

        embed.add_field(
            name=f'⭐ Level {level}',
            value=f'{xp} / {xp_next_level} XP\n`{bar}`',
            inline=False,
        )

        if badges:
            badge_text = '\n'.join(
                [f'🏆 **{b}**: *{BADGE_DEFINITIONS.get(b, "")}*' for b in badges]
            )
        else:
            badge_text = 'Chưa có huy hiệu nào.'

        embed.add_field(name='Huy hiệu (Badges)', value=badge_text, inline=False)

        await msg.delete()
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Achievements(bot))
