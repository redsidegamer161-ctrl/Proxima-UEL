import discord
from discord import app_commands
import sqlite3
import datetime
import os
import asyncio
import functools
from keep_alive import keep_alive

# --- IMPORTS FOR IMAGE GENERATION ---
from PIL import Image, ImageDraw, ImageFont
import io
import aiohttp
import urllib.request

# --- CONFIGURATION ---
TOKEN = os.environ.get('TOKEN')
DEFAULT_BG_FILE = "proxima_default.jpg"

# --- AUTO-DOWNLOAD FONT (Bebas Neue) ---
def check_and_download_font():
    if not os.path.exists("font.ttf"):
        print("System: Font missing. Downloading Bebas Neue...")
        try:
            url = "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf"
            urllib.request.urlretrieve(url, "font.ttf")
            print("System: Bebas Neue downloaded successfully!")
        except Exception as e:
            print(f"System: Could not download font. Text will be small. Error: {e}")

check_and_download_font()

# --- DATABASE HELPER (non-blocking) ---
def run_db(func, *args, **kwargs):
    """Run a database function in a thread pool with a fresh connection."""
    async def wrapper():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: db_worker(func, *args, **kwargs)
        )
    return wrapper

def db_worker(func, *args, **kwargs):
    """Worker that creates a new connection, runs the query, and closes it."""
    conn = sqlite3.connect('team_manager.db')
    c = conn.cursor()
    try:
        result = func(c, *args, **kwargs)
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# --- DATABASE QUERY FUNCTIONS (synchronous, expecting cursor as first argument) ---
def init_db(c):
    c.execute("""CREATE TABLE IF NOT EXISTS global_config (
                 guild_id INTEGER PRIMARY KEY,
                 manager_role_id INTEGER,
                 asst_role_id INTEGER,
                 contract_channel_id INTEGER,
                 free_agent_role_id INTEGER,
                 window_open INTEGER DEFAULT 1,
                 demand_limit INTEGER DEFAULT 3
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS teams (
                 team_role_id INTEGER PRIMARY KEY,
                 logo TEXT,
                 roster_limit INTEGER,
                 transaction_image TEXT
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS free_agents (
                 user_id INTEGER PRIMARY KEY,
                 region TEXT,
                 position TEXT,
                 description TEXT,
                 timestamp TEXT
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS player_stats (
                 user_id INTEGER PRIMARY KEY,
                 transfers INTEGER DEFAULT 0,
                 demands INTEGER DEFAULT 0
                 )""")
    # Migrations
    for col in ["free_agent_role_id", "window_open", "demand_limit"]:
        try:
            c.execute(f"ALTER TABLE global_config ADD COLUMN {col} INTEGER")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE teams ADD COLUMN transaction_image TEXT")
    except:
        pass
    return True

def get_global_config(c, guild_id):
    c.execute("SELECT * FROM global_config WHERE guild_id = ?", (guild_id,))
    return c.fetchone()

def get_team_data(c, role_id):
    c.execute("SELECT * FROM teams WHERE team_role_id = ?", (role_id,))
    return c.fetchone()

def get_all_teams(c):
    c.execute("SELECT * FROM teams")
    return c.fetchall()

def get_player_stats(c, user_id):
    c.execute("SELECT * FROM player_stats WHERE user_id = ?", (user_id,))
    data = c.fetchone()
    if not data:
        c.execute("INSERT INTO player_stats (user_id, transfers, demands) VALUES (?, 0, 0)", (user_id,))
        return (user_id, 0, 0)
    return data

def update_stat(c, user_id, stat_type, amount=1):
    get_player_stats(c, user_id)
    if stat_type == "transfer":
        c.execute("UPDATE player_stats SET transfers = transfers + ? WHERE user_id = ?", (amount, user_id))
    elif stat_type == "demand":
        c.execute("UPDATE player_stats SET demands = demands + ? WHERE user_id = ?", (amount, user_id))

def delete_free_agent(c, user_id):
    c.execute("DELETE FROM free_agents WHERE user_id = ?", (user_id,))

def insert_free_agent(c, user_id, region, position, description):
    c.execute("INSERT OR REPLACE INTO free_agents VALUES (?, ?, ?, ?, ?)",
              (user_id, region, position, description, datetime.datetime.now().isoformat()))

def get_free_agents(c):
    c.execute("SELECT * FROM free_agents")
    return c.fetchall()

def set_global_config(c, guild_id, manager_id, asst_id, channel_id, fa_role_id, window_state, demand_limit):
    c.execute("INSERT OR REPLACE INTO global_config VALUES (?, ?, ?, ?, ?, ?, ?)",
              (guild_id, manager_id, asst_id, channel_id, fa_role_id, window_state, demand_limit))

def update_window(c, guild_id, status):
    c.execute("UPDATE global_config SET window_open = ? WHERE guild_id = ?", (status, guild_id))

def insert_team(c, team_role_id, logo, roster_limit, trans_img):
    c.execute("INSERT OR REPLACE INTO teams VALUES (?, ?, ?, ?)", (team_role_id, logo, roster_limit, trans_img))

def delete_team(c, team_role_id):
    c.execute("DELETE FROM teams WHERE team_role_id = ?", (team_role_id,))

def update_team_transaction_image(c, team_role_id, image_url):
    c.execute("UPDATE teams SET transaction_image = ? WHERE team_role_id = ?", (image_url, team_role_id))

def get_top_transfers(c):
    c.execute("SELECT user_id, transfers FROM player_stats ORDER BY transfers DESC LIMIT 15")
    return c.fetchall()

# --- ASYNC WRAPPERS ---
async def init_db_async():
    await run_db(init_db)()

async def get_global_config_async(guild_id):
    return await run_db(get_global_config, guild_id)()

async def get_team_data_async(role_id):
    return await run_db(get_team_data, role_id)()

async def get_all_teams_async():
    return await run_db(get_all_teams)()

async def get_player_stats_async(user_id):
    return await run_db(get_player_stats, user_id)()

async def update_stat_async(user_id, stat_type, amount=1):
    await run_db(update_stat, user_id, stat_type, amount)()

async def delete_free_agent_async(user_id):
    await run_db(delete_free_agent, user_id)()

async def insert_free_agent_async(user_id, region, position, description):
    await run_db(insert_free_agent, user_id, region, position, description)()

async def get_free_agents_async():
    return await run_db(get_free_agents)()

async def set_global_config_async(guild_id, manager_id, asst_id, channel_id, fa_role_id, window_state, demand_limit):
    await run_db(set_global_config, guild_id, manager_id, asst_id, channel_id, fa_role_id, window_state, demand_limit)()

async def update_window_async(guild_id, status):
    await run_db(update_window, guild_id, status)()

async def insert_team_async(team_role_id, logo, roster_limit, trans_img):
    await run_db(insert_team, team_role_id, logo, roster_limit, trans_img)()

async def delete_team_async(team_role_id):
    await run_db(delete_team, team_role_id)()

async def update_team_transaction_image_async(team_role_id, image_url):
    await run_db(update_team_transaction_image, team_role_id, image_url)()

async def get_top_transfers_async():
    return await run_db(get_top_transfers)()

# --- HELPER FUNCTIONS (async) ---
def is_staff(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

async def is_window_open_async(guild_id):
    config = await get_global_config_async(guild_id)
    if not config:
        return True
    try:
        return config[5] == 1
    except IndexError:
        return True

async def find_user_team_async(member):
    for role in member.roles:
        data = await get_team_data_async(role.id)
        if data:
            trans_img = data[3] if len(data) > 3 else None
            return (role, data[1], data[2], trans_img)
    return None

async def get_managers_of_team_async(guild, team_role):
    config = await get_global_config_async(guild.id)
    if not config:
        return ([], [])
    mgr_id, asst_id = config[1], config[2]
    head_managers, assistants = [], []
    for member in team_role.members:
        r_ids = [r.id for r in member.roles]
        if mgr_id in r_ids:
            head_managers.append(member)
        elif asst_id in r_ids:
            assistants.append(member)
    return (head_managers, assistants)

async def cleanup_free_agent_async(guild, member):
    await delete_free_agent_async(member.id)
    config = await get_global_config_async(guild.id)
    if config and config[4]:
        role = guild.get_role(config[4])
        if role and role in member.roles:
            try:
                await member.remove_roles(role)
            except:
                pass

def format_roster_list(members, mgr_id, asst_id):
    formatted_list = []
    for m in members:
        r_ids = [r.id for r in m.roles]
        name = m.mention
        if mgr_id in r_ids:
            name += " **(TM)**"
        elif asst_id in r_ids:
            name += " **(AM)**"
        formatted_list.append(name)
    return formatted_list

# --- MASTER CARD GENERATOR ---
async def generate_transaction_card(player, team_name, team_color, title_text="OFFICIAL SIGNING", custom_bg_url=None):
    W, H = 800, 400
    img = None

    if custom_bg_url:
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(custom_bg_url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        bg_img = Image.open(io.BytesIO(data)).convert("RGB")
                        img = bg_img.resize((W, H))
                        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                        draw_overlay = ImageDraw.Draw(overlay)
                        draw_overlay.rectangle([(0, 240), (W, H)], fill=(0, 0, 0, 160))
                        img.paste(overlay, (0, 0), mask=overlay)
        except (asyncio.TimeoutError, aiohttp.ClientError, Exception):
            img = None

    if img is None and os.path.exists(DEFAULT_BG_FILE):
        try:
            bg_img = Image.open(DEFAULT_BG_FILE).convert("RGB")
            img = bg_img.resize((W, H))
        except:
            pass

    if img is None:
        bg_color = team_color.to_rgb()
        if bg_color == (0, 0, 0):
            bg_color = (44, 47, 51)
        img = Image.new("RGB", (W, H), color=bg_color)

    draw = ImageDraw.Draw(img)

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(player.display_avatar.url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    avatar = Image.open(io.BytesIO(data)).convert("RGBA")
                    avatar = avatar.resize((200, 200))
                    mask = Image.new("L", (200, 200), 0)
                    draw_mask = ImageDraw.Draw(mask)
                    draw_mask.ellipse((0, 0, 200, 200), fill=255)
                    img.paste(avatar, (300, 50), mask=mask)
                    draw.ellipse((300, 50, 500, 250), outline="white", width=3)
    except (asyncio.TimeoutError, aiohttp.ClientError, Exception):
        pass

    try:
        font_large = ImageFont.truetype("font.ttf", 80)
        font_small = ImageFont.truetype("font.ttf", 50)
    except:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    draw.text((W / 2, 290), title_text, fill="white", font=font_small, anchor="mm")
    draw.text((W / 2, 360), player.name.upper(), fill="white", font=font_large, anchor="mm")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename="transaction.png")

# --- EMBED GENERATOR ---
def create_transaction_embed(guild, title, description, color, team_role, logo, coach, roster_count, limit):
    embed = discord.Embed(description=description, color=color, timestamp=datetime.datetime.now())
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    embed.title = title
    if logo and "http" in logo:
        embed.set_thumbnail(url=logo)
    if coach:
        embed.add_field(name="Coach:", value=f"👔 {coach.mention}", inline=False)
    roster_text = f"{roster_count}/{limit}" if limit > 0 else f"{roster_count} (No Limit)"
    embed.add_field(name="Roster:", value=f"👥 {roster_text}", inline=False)
    embed.set_footer(text="Official Transaction")
    return embed

async def send_to_channel(guild, embed, file=None):
    config = await get_global_config_async(guild.id)
    if config and config[3]:
        channel = guild.get_channel(config[3])
        if channel:
            await channel.send(embed=embed, file=file)
            return True
    return False

async def send_dm(user, content=None, embed=None, view=None):
    try:
        await user.send(content=content, embed=embed, view=view)
        return True
    except:
        return False

# --- VIEWS ---
class TransferView(discord.ui.View):
    def __init__(self, guild, player, from_team, to_team, to_manager, logo):
        super().__init__(timeout=86400)
        self.guild = guild
        self.player = player
        self.from_team = from_team
        self.to_team = to_team
        self.to_manager = to_manager
        self.logo = logo

    @discord.ui.button(label="Accept Transfer", style=discord.ButtonStyle.green, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_window_open_async(self.guild.id):
            return await interaction.response.send_message("❌ **Transfer Window is CLOSED.**", ephemeral=True)

        await interaction.response.defer()

        try:
            member = self.guild.get_member(self.player.id)
            if not member:
                return await interaction.followup.send("❌ Player missing.", ephemeral=True)

            await member.remove_roles(self.from_team)
            await member.add_roles(self.to_team)
            await cleanup_free_agent_async(self.guild, member)
            await update_stat_async(member.id, "transfer")

            desc = f"🚨 **TRANSFER NEWS** 🚨\n\n{member.mention} has been transferred\nFrom: {self.from_team.mention}\nTo: {self.to_team.mention}"

            data = await get_team_data_async(self.to_team.id)
            limit = data[2] if data else 0
            custom_bg = data[3] if data and len(data) > 3 else None

            embed = create_transaction_embed(self.guild, "Official Transfer", desc, discord.Color.purple(), self.to_team, self.logo, self.to_manager, len(self.to_team.members), limit)

            file = await generate_transaction_card(member, self.to_team.name, self.to_team.color, "OFFICIAL TRANSFER", custom_bg)
            embed.set_image(url="attachment://transaction.png")

            await send_to_channel(self.guild, embed, file)
            await send_dm(self.to_manager, f"✅ Transfer for **{member.name}** ACCEPTED!")

            self.stop()
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(content="✅ **Transfer Approved.**", view=self)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await send_dm(self.to_manager, f"❌ Transfer for **{self.player.name}** DECLINED.")
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(content="❌ **Transfer Declined.**", view=self)

class HelpView(discord.ui.View):
    def __init__(self, embeds):
        super().__init__(timeout=60)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.previous.disabled = self.current_page == 0
        self.next.disabled = self.current_page == len(self.embeds) - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

class ResetView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=30)
        self.guild_id = guild_id

    @discord.ui.button(label="⚠️ CONFIRM WIPE", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await run_db(lambda c: c.execute("DELETE FROM global_config WHERE guild_id = ?", (self.guild_id,)))()
        await interaction.response.edit_message(content="✅ **Configuration Wiped.** Please run `/setup_global` again.", view=None, embed=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ **Reset Cancelled.**", view=None, embed=None)

# --- BOT CLASS ---
class LeagueBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        await init_db_async()
        await self.tree.sync()
        print(f"✅ LOGGED IN AS: {self.user}")

client = LeagueBot()

# --- COMMANDS (with cooldowns) ---

def cooldown(rate=1, per=5):
    return app_commands.checks.cooldown(rate, per)

@client.tree.command(name="leave_other_servers", description="[OWNER ONLY] Makes the bot leave all other servers.")
async def leave_other_servers(interaction: discord.Interaction):
    OWNER_ID = 925817680848617486
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ **Access Denied:** You are not the bot owner.", ephemeral=True)
        return
    await interaction.response.send_message("🚨 **Initiating Server Cleansing...** Please wait.", ephemeral=True)
    left_count = 0
    error_count = 0
    for guild in client.guilds:
        if guild.id == interaction.guild_id:
            continue
        try:
            await guild.leave()
            left_count += 1
            print(f"System: Successfully left '{guild.name}'")
        except Exception as e:
            error_count += 1
            print(f"System: Failed to leave '{guild.name}'. Error: {e}")
    await interaction.followup.send(f"✅ **Done!** I have successfully left **{left_count}** servers. (Errors: {error_count})\nI am now only active in this server.", ephemeral=True)

@client.tree.command(name="help", description="Show bot commands")
@cooldown(1, 5)
async def help_command(interaction: discord.Interaction):
    embed1 = discord.Embed(title="Help - General Commands (Page 1/3)", color=discord.Color.blue())
    embed1.add_field(name="/looking_for_team", value="Post yourself as a Free Agent", inline=False)
    embed1.add_field(name="/demand", value="Leave your current team (Uses Demand Limit)", inline=False)
    embed1.add_field(name="/team_view [role]", value="View a team's roster", inline=False)
    embed1.add_field(name="/free_agents", value="View available players", inline=False)

    embed2 = discord.Embed(title="Help - Manager Commands (Page 2/3)", color=discord.Color.green())
    embed2.add_field(name="/sign [player]", value="Sign a player to your team", inline=False)
    embed2.add_field(name="/release [player]", value="Release a player", inline=False)
    embed2.add_field(name="/transfer [player]", value="Request to buy a player", inline=False)
    embed2.add_field(name="/promote [player]", value="Promote player to Assistant Manager", inline=False)
    embed2.add_field(name="/tm_transfer [player]", value="Transfer Team Ownership to a player", inline=False)
    embed2.add_field(name="/decorate_transactions", value="Set custom transaction card background", inline=False)

    embed3 = discord.Embed(title="Help - Admin Commands (Page 3/3)", color=discord.Color.red())
    embed3.add_field(name="/setup_global", value="Configure bot roles/channels", inline=False)
    embed3.add_field(name="/setup_team", value="Register a new team", inline=False)
    embed3.add_field(name="/team_delete", value="Delete a team", inline=False)
    embed3.add_field(name="/window", value="Open/Close transfer window", inline=False)
    embed3.add_field(name="/reset_config", value="Wipe server configuration", inline=False)
    embed3.add_field(name="/transfer_list", value="View top transfers leaderboard", inline=False)

    view = HelpView([embed1, embed2, embed3])
    await interaction.response.send_message(embed=embed1, view=view, ephemeral=True)

@client.tree.command(name="tm_transfer", description="Transfer Team Ownership to another player")
@cooldown(1, 5)
async def tm_transfer(interaction: discord.Interaction, player: discord.Member):
    g_config = await get_global_config_async(interaction.guild.id)
    if not g_config:
        return await interaction.response.send_message("❌ Config not set.", ephemeral=True)
    mgr_role_id = g_config[1]
    mgr_role = interaction.guild.get_role(mgr_role_id)
    if not mgr_role:
        return await interaction.response.send_message("❌ Manager role missing from config.", ephemeral=True)
    if mgr_role not in interaction.user.roles:
        return await interaction.response.send_message("❌ You are not a Team Manager.", ephemeral=True)
    team_info = await find_user_team_async(interaction.user)
    if not team_info:
        return await interaction.response.send_message("❌ You don't have a team.", ephemeral=True)
    team_role = team_info[0]
    if team_role not in player.roles:
        return await interaction.response.send_message("❌ That player is not on your team.", ephemeral=True)
    try:
        await interaction.user.remove_roles(mgr_role)
        await player.add_roles(mgr_role)
        await interaction.response.send_message(f"✅ **Ownership Transferred!**\n{interaction.user.mention} ➝ {player.mention}\n{player.mention} is now the Manager of **{team_role.name}**.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Role Error: {e}", ephemeral=True)

@client.tree.command(name="reset_config", description="⚠️ WIPE SERVER DATA (Admin Only)")
@cooldown(1, 5)
async def reset_config(interaction: discord.Interaction):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Admin Only", ephemeral=True)
    view = ResetView(interaction.guild.id)
    embed = discord.Embed(title="⚠️ DANGER ZONE", description="Are you sure you want to **RESET** the bot configuration for this server?\n\nThis will delete:\n- Global Config (Roles/Channels)\n- Demand Limits\n\n(It will NOT delete Teams or Player Stats)", color=discord.Color.dark_red())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@client.tree.command(name="setup_global", description="Set roles, channels, and limits.")
@cooldown(1, 5)
async def setup_global(interaction: discord.Interaction, manager_role: discord.Role, asst_role: discord.Role, free_agent_role: discord.Role, channel: discord.TextChannel, demand_limit: int = 3):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Admin Only", ephemeral=True)
    current_config = await get_global_config_async(interaction.guild.id)
    window_state = 1
    if current_config and len(current_config) > 5:
        window_state = current_config[5]
    await set_global_config_async(interaction.guild.id, manager_role.id, asst_role.id, channel.id, free_agent_role.id, window_state, demand_limit)
    await interaction.response.send_message(f"✅ **Config Saved!** (Demand Limit: {demand_limit})", ephemeral=True)

@client.tree.command(name="setup_team", description="Register a Team Role")
@cooldown(1, 5)
async def setup_team(interaction: discord.Interaction, team_role: discord.Role, logo: str, roster_limit: int = 20):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Admin Only", ephemeral=True)
    existing = await get_team_data_async(team_role.id)
    trans_img = existing[3] if existing and len(existing) > 3 else None
    await insert_team_async(team_role.id, logo, roster_limit, trans_img)
    await interaction.response.send_message(f"✅ **{team_role.name}** registered!", ephemeral=True)

@client.tree.command(name="team_delete", description="Unregister a team")
@cooldown(1, 5)
async def team_delete(interaction: discord.Interaction, team_role: discord.Role):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Admin Only", ephemeral=True)
    await delete_team_async(team_role.id)
    await interaction.response.send_message(f"🗑️ **{team_role.name}** removed.", ephemeral=True)

@client.tree.command(name="window", description="Open/Close Window")
@app_commands.choices(status=[app_commands.Choice(name="Open ✅", value=1), app_commands.Choice(name="Closed ❌", value=0)])
@cooldown(1, 5)
async def window(interaction: discord.Interaction, status: int):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Admin Only", ephemeral=True)
    await update_window_async(interaction.guild.id, status)
    msg = "✅ **Transfer Window OPEN!**" if status == 1 else "❌ **Transfer Window CLOSED!**"
    await interaction.response.send_message(msg)
    conf = await get_global_config_async(interaction.guild.id)
    if conf and conf[3]:
        chan = interaction.guild.get_channel(conf[3])
        if chan:
            await chan.send(msg)

@client.tree.command(name="decorate_transactions", description="Set custom contract background (Upload Image OR Link)")
@cooldown(1, 5)
async def decorate_transactions(interaction: discord.Interaction, image_file: discord.Attachment = None, url: str = None):
    g_config = await get_global_config_async(interaction.guild.id)
    user_roles = [r.id for r in interaction.user.roles]
    if (g_config[1] not in user_roles) and (g_config[2] not in user_roles) and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Managers or Admins only.", ephemeral=True)
    team_info = await find_user_team_async(interaction.user)
    if not team_info:
        return await interaction.response.send_message("❌ You aren't managing a team.", ephemeral=True)
    team_role, _, _, _ = team_info
    final_url = None
    if url and url.lower() in ["reset", "none", "remove"]:
        await update_team_transaction_image_async(team_role.id, None)
        return await interaction.response.send_message(f"✅ **{team_role.name}** reverted to Proxima Default.")
    if image_file:
        if not image_file.content_type.startswith("image/"):
            return await interaction.response.send_message("❌ File must be an image.", ephemeral=True)
        final_url = image_file.url
    elif url:
        if not url.startswith("http"):
            return await interaction.response.send_message("❌ Invalid Link.", ephemeral=True)
        final_url = url
    else:
        return await interaction.response.send_message("❌ Provide an **Image File** OR a **URL**.", ephemeral=True)
    await update_team_transaction_image_async(team_role.id, final_url)
    embed = discord.Embed(title="Background Updated", description="Your future signings will look like this:", color=discord.Color.green())
    embed.set_image(url=final_url)
    await interaction.response.send_message(f"✅ **{team_role.name}** custom background set!", embed=embed, ephemeral=True)

@client.tree.command(name="sign", description="Sign a player to YOUR team")
@cooldown(1, 5)
async def sign(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer()
    if not await is_window_open_async(interaction.guild.id):
        return await interaction.followup.send("❌ **Window Closed.**")
    g_config = await get_global_config_async(interaction.guild.id)
    user_roles = [r.id for r in interaction.user.roles]
    if (g_config[1] not in user_roles) and (g_config[2] not in user_roles):
        return await interaction.followup.send("❌ Not Authorized.")
    team_info = await find_user_team_async(interaction.user)
    if not team_info:
        return await interaction.followup.send("❌ No team role.")
    team_role, logo, limit, custom_bg = team_info
    if team_role in player.roles:
        return await interaction.followup.send("⚠️ Already on team.")
    if await find_user_team_async(player):
        return await interaction.followup.send("🚫 Player on another team. Use `/transfer`.")
    if len(team_role.members) >= limit:
        return await interaction.followup.send("❌ Roster Full!")
    await player.add_roles(team_role)
    await cleanup_free_agent_async(interaction.guild, player)
    await update_stat_async(player.id, "transfer")
    desc = f"The {team_role.mention} have **signed** {player.mention}"
    embed = create_transaction_embed(interaction.guild, f"{team_role.name} Transaction", desc, discord.Color.blue(), team_role, logo, interaction.user, len(team_role.members), limit)
    try:
        file = await generate_transaction_card(player, team_role.name, team_role.color, "OFFICIAL SIGNING", custom_bg)
        embed.set_image(url="attachment://transaction.png")
        await send_to_channel(interaction.guild, embed, file)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Signed, but image error: {e}")
        await send_to_channel(interaction.guild, embed)
    await send_dm(player, content=f"✅ You have been signed to **{team_role.name}**!", embed=embed)
    await interaction.followup.send("✅ Player Signed!")

@client.tree.command(name="release", description="Release a player")
@cooldown(1, 5)
async def release(interaction: discord.Interaction, player: discord.Member):
    if not await is_window_open_async(interaction.guild.id):
        return await interaction.response.send_message("❌ Window Closed.", ephemeral=True)
    team_info = await find_user_team_async(interaction.user)
    if not team_info:
        return await interaction.response.send_message("❌ No team.", ephemeral=True)
    team_role, logo, limit, custom_bg = team_info
    if team_role not in player.roles:
        return await interaction.response.send_message("⚠️ Player not on team.", ephemeral=True)
    await player.remove_roles(team_role)
    desc = f"The **{team_role.name}** have **released** {player.mention}"
    embed = create_transaction_embed(interaction.guild, f"{team_role.name} Transaction", desc, discord.Color.red(), team_role, logo, interaction.user, len(team_role.members), limit)
    try:
        file = await generate_transaction_card(player, team_role.name, team_role.color, "OFFICIAL RELEASE", custom_bg)
        embed.set_image(url="attachment://transaction.png")
        await send_to_channel(interaction.guild, embed, file)
    except:
        await send_to_channel(interaction.guild, embed)
    await send_dm(player, content=f"⚠️ Released from **{team_role.name}**.", embed=embed)
    await interaction.response.send_message("✅ Released!", ephemeral=True)

@client.tree.command(name="demand", description="Leave your current team (Uses Demand Limit)")
@cooldown(1, 5)
async def demand(interaction: discord.Interaction):
    team_info = await find_user_team_async(interaction.user)
    if not team_info:
        return await interaction.response.send_message("❌ Not in a team.", ephemeral=True)
    team_role, logo, limit, _ = team_info
    g_conf = await get_global_config_async(interaction.guild.id)
    demand_limit = g_conf[6] if g_conf and len(g_conf) > 6 else 3
    stats = await get_player_stats_async(interaction.user.id)
    demands_used = stats[2]
    if demands_used >= demand_limit:
        return await interaction.response.send_message(f"🚫 **Demand Limit Reached!** ({demands_used}/{demand_limit})\nYou cannot leave your team.", ephemeral=True)
    await interaction.user.remove_roles(team_role)
    await update_stat_async(interaction.user.id, "demand")
    demands_left = demand_limit - (demands_used + 1)
    config = await get_global_config_async(interaction.guild.id)
    if config and config[4]:
        fa_role = interaction.guild.get_role(config[4])
        if fa_role:
            await interaction.user.add_roles(fa_role)
    desc = f"{interaction.user.mention} has **Demanded Release** from the team.\n\n⚠️ **Demands Left:** {demands_left}"
    embed = create_transaction_embed(interaction.guild, "Transfer Demand", desc, discord.Color.dark_grey(), team_role, logo, None, len(team_role.members), limit)
    await send_to_channel(interaction.guild, embed)
    heads, assts = await get_managers_of_team_async(interaction.guild, team_role)
    for mgr in heads + assts:
        await send_dm(mgr, content=f"📢 {interaction.user.name} has left your team.")
    await interaction.response.send_message(f"👋 Left **{team_role.name}**.\nDemands remaining: {demands_left}", ephemeral=True)

@client.tree.command(name="promote", description="Promote a player to Assistant Manager")
@cooldown(1, 5)
async def promote(interaction: discord.Interaction, player: discord.Member):
    g_config = await get_global_config_async(interaction.guild.id)
    user_roles = [r.id for r in interaction.user.roles]
    if g_config[1] not in user_roles and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Head Managers only.", ephemeral=True)
    team_info = await find_user_team_async(interaction.user)
    if not team_info:
        return await interaction.response.send_message("❌ You aren't managing a team.", ephemeral=True)
    team_role = team_info[0]
    if team_role not in player.roles:
        return await interaction.response.send_message("❌ Player is not on your team.", ephemeral=True)
    asst_role_id = g_config[2]
    asst_role = interaction.guild.get_role(asst_role_id)
    if not asst_role:
        return await interaction.response.send_message("❌ Assistant Role not configured.", ephemeral=True)
    await player.add_roles(asst_role)
    await interaction.response.send_message(f"✅ Promoted {player.mention} to **Assistant Manager** of {team_role.name}!")

@client.tree.command(name="transfer_list", description="Show top players by transfer count")
@cooldown(1, 5)
async def transfer_list(interaction: discord.Interaction):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Admin Only", ephemeral=True)
    data = await get_top_transfers_async()
    if not data:
        return await interaction.response.send_message("No transfer history found.", ephemeral=True)
    embed = discord.Embed(title="📊 Most Transfers", color=discord.Color.gold())
    desc = ""
    for idx, (uid, count) in enumerate(data, 1):
        user = interaction.guild.get_member(uid)
        name = user.name if user else f"Unknown ({uid})"
        desc += f"**{idx}.** {name} — {count} Transfers\n"
    embed.description = desc
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="looking_for_team", description="Post yourself as a Free Agent")
@app_commands.choices(region=[app_commands.Choice(name="Asia", value="ASIA"), app_commands.Choice(name="Europe", value="EU"), app_commands.Choice(name="NA", value="NA"), app_commands.Choice(name="SA", value="SA")],
                      position=[app_commands.Choice(name="ST", value="ST"), app_commands.Choice(name="MF", value="MF"), app_commands.Choice(name="DF", value="DF"), app_commands.Choice(name="GK", value="GK")])
@cooldown(1, 5)
async def looking_for_team(interaction: discord.Interaction, region: str, position: str, description: str):
    await insert_free_agent_async(interaction.user.id, region, position, description)
    config = await get_global_config_async(interaction.guild.id)
    if config and config[4]:
        role = interaction.guild.get_role(config[4])
        if role:
            await interaction.user.add_roles(role)
    await interaction.response.send_message(f"✅ Listed as **Free Agent** ({region} - {position})!", ephemeral=True)

@client.tree.command(name="free_agents", description="View available players")
@cooldown(1, 5)
async def free_agents(interaction: discord.Interaction):
    await interaction.response.defer()
    agents = await get_free_agents_async()
    if not agents:
        return await interaction.followup.send("🤷‍♂️ No Free Agents currently listed.")
    embed = discord.Embed(title="📄 Free Agency Market", color=discord.Color.teal())
    count = 0
    for agent in agents:
        uid, reg, pos, desc, _ = agent
        member = interaction.guild.get_member(uid)
        if member:
            embed.add_field(name=f"{pos} | {member.name} ({reg})", value=f"📝 {desc}", inline=False)
            count += 1
            if count >= 20:
                embed.set_footer(text="Showing first 20 agents...")
                break
    await interaction.followup.send(embed=embed)

@client.tree.command(name="team_list", description="List teams (Admin)")
@cooldown(1, 5)
async def team_list(interaction: discord.Interaction):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Admin Only", ephemeral=True)
    await interaction.response.defer()
    g_conf = await get_global_config_async(interaction.guild.id)
    mgr_id = g_conf[1] if g_conf else 0
    asst_id = g_conf[2] if g_conf else 0
    all_teams = await get_all_teams_async()
    if not all_teams:
        return await interaction.followup.send("❌ No teams.")
    embed = discord.Embed(title="🏆 Registered Teams List", color=discord.Color.gold())
    for t_data in all_teams:
        role_id = t_data[0]
        logo = t_data[1]
        team_role = interaction.guild.get_role(role_id)
        if not team_role:
            continue
        header_emoji = logo if (logo and "http" not in logo) else "🛡️"
        members_formatted = format_roster_list(team_role.members, mgr_id, asst_id)
        player_str = "\n".join(members_formatted) if members_formatted else "*No players.*"
        embed.add_field(name=f"{header_emoji} {team_role.name} ({len(team_role.members)})", value=player_str, inline=False)
    await interaction.followup.send(embed=embed)

@client.tree.command(name="team_view", description="View a specific team's roster")
@cooldown(1, 5)
async def team_view(interaction: discord.Interaction, team: discord.Role):
    data = await get_team_data_async(team.id)
    if not data:
        return await interaction.response.send_message("❌ Not a registered team.", ephemeral=True)
    g_conf = await get_global_config_async(interaction.guild.id)
    mgr_id = g_conf[1] if g_conf else 0
    asst_id = g_conf[2] if g_conf else 0
    logo = data[1]
    header_emoji = logo if (logo and "http" not in logo) else "🛡️"
    members_formatted = format_roster_list(team.members, mgr_id, asst_id)
    player_str = "\n".join(members_formatted) if members_formatted else "*No players.*"
    embed = discord.Embed(title=f"{header_emoji} {team.name} Roster", color=team.color)
    if logo and "http" in logo:
        embed.set_thumbnail(url=logo)
    embed.description = player_str
    embed.set_footer(text=f"Total: {len(team.members)}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@client.tree.command(name="transfer", description="Request to sign a player")
@cooldown(1, 5)
async def transfer(interaction: discord.Interaction, player: discord.Member):
    if not await is_window_open_async(interaction.guild.id):
        return await interaction.response.send_message("❌ **Window CLOSED.**", ephemeral=True)
    my_team_info = await find_user_team_async(interaction.user)
    if not my_team_info:
        return await interaction.response.send_message("❌ Not a manager.", ephemeral=True)
    my_team_role, my_logo, _, _ = my_team_info
    target_team_info = await find_user_team_async(player)
    if not target_team_info:
        return await interaction.response.send_message("⚠️ Player not on a team.", ephemeral=True)
    target_team_role, _, _, _ = target_team_info
    if my_team_role.id == target_team_role.id:
        return await interaction.response.send_message("⚠️ Already on your team!", ephemeral=True)
    heads, assts = await get_managers_of_team_async(interaction.guild, target_team_role)
    target_manager = heads[0] if heads else (assts[0] if assts else None)
    if not target_manager:
        return await interaction.response.send_message(f"❌ **{target_team_role.name}** has no active Manager.", ephemeral=True)
    view = TransferView(interaction.guild, player, target_team_role, my_team_role, interaction.user, my_logo)
    dm_embed = discord.Embed(title="Transfer Offer 📝", color=discord.Color.gold())
    dm_embed.description = f"**{interaction.user.mention}** wants to buy **{player.name}**.\nDo you accept?"
    if await send_dm(target_manager, embed=dm_embed, view=view):
        await interaction.response.send_message(f"✅ **Offer Sent!** Waiting for {target_manager.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Could not DM manager.", ephemeral=True)

@client.tree.command(name="test_card", description="TEST: Generates a sample signing card")
@cooldown(1, 5)
async def test_card(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        color = interaction.user.top_role.color
        if color == discord.Color.default():
            color = discord.Color.dark_grey()
        file = await generate_transaction_card(interaction.user, "Test Team", color, "TEST CARD")
        await interaction.followup.send("🖼️ **Test Image Generation:**", file=file)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}")

# --- ERROR HANDLER ---
@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"⏳ **Take a breather!** Try again in {int(error.retry_after)}s.", ephemeral=True)
    elif isinstance(error, app_commands.BotMissingPermissions):
        await interaction.response.send_message("❌ I don't have permission to do that here.", ephemeral=True)
    else:
        print(f"⚠️ ERROR: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ **System Busy:** Please wait a moment and try again.", ephemeral=True)
        except:
            pass

# --- STARTUP ---
print("System: Loading Proxima V17 (Non-blocking DB)...")
if TOKEN:
    try:
        keep_alive()
        client.run(TOKEN)
    except Exception as e:
        print(f"❌ Error: {e}")
