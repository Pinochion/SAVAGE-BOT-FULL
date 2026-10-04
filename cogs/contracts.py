import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands, tasks
from utils.config_db import get_connection, get_config, parse_ids
from utils.permissions import can_start_contract, can_join_contract

DURATION_MINUTES = 15

def now(): return datetime.now(timezone.utc)
def iso(dt): return dt.isoformat()
def from_iso(v): return datetime.fromisoformat(v)
def csv_ids(v): return [int(x) for x in str(v or '').split(',') if x.strip().isdigit()]
def save_participants(cid, ids):
    conn=get_connection(); conn.execute('UPDATE contracts SET participants=? WHERE id=?',(','.join(map(str,ids)),cid)); conn.commit(); conn.close()

def create_contract(guild_id, starter_id, ends_at):
    conn=get_connection(); cur=conn.execute('INSERT INTO contracts(guild_id,starter_id,started_at,ends_at,active,participants) VALUES(?,?,?,?,1,?)',(guild_id,starter_id,iso(now()),iso(ends_at),'')); cid=cur.lastrowid; conn.commit(); conn.close(); return cid

def get_contract(cid):
    conn=get_connection(); r=conn.execute('SELECT * FROM contracts WHERE id=?',(cid,)).fetchone(); conn.close(); return dict(r) if r else None

def get_active(guild_id):
    conn=get_connection(); r=conn.execute('SELECT * FROM contracts WHERE guild_id=? AND active=1 ORDER BY id DESC LIMIT 1',(guild_id,)).fetchone(); conn.close(); return dict(r) if r else None

def close_contract(cid):
    conn=get_connection(); conn.execute('UPDATE contracts SET active=0 WHERE id=?',(cid,)); conn.commit(); conn.close()

class ContractView(discord.ui.View):
    def __init__(self,cog,cid):
        super().__init__(timeout=None); self.cog=cog; self.cid=cid
        self.children[0].custom_id=f'contract:join:{cid}'
        self.children[1].custom_id=f'contract:leave:{cid}'
    @discord.ui.button(label='🚀 Записаться',style=discord.ButtonStyle.success,custom_id='contract:join')
    async def join(self,interaction,button): await self.cog.join(interaction,self.cid)
    @discord.ui.button(label='❌ Выписаться',style=discord.ButtonStyle.danger,custom_id='contract:leave')
    async def leave(self,interaction,button): await self.cog.leave(interaction,self.cid)

class ContractPanelView(discord.ui.View):
    def __init__(self,cog): super().__init__(timeout=None); self.cog=cog
    @discord.ui.button(label='🚀 Запустить контракт',style=discord.ButtonStyle.primary,custom_id='contract:start')
    async def start(self,interaction,button): await self.cog.start_contract(interaction)

class Contracts(commands.Cog):
    def __init__(self,bot):
        self.bot=bot; self.expire_task.start()
    async def cog_load(self):
        self.bot.add_view(ContractPanelView(self))

    async def restore_views(self):
        for guild in self.bot.guilds:
            active=get_active(guild.id)
            if active:
                self.bot.add_view(ContractView(self,active['id']))
    def cog_unload(self): self.expire_task.cancel()
    async def publish_panel(self,guild):
        cfg=get_config(guild.id); cid=cfg.get('contract_channel_id')
        channel=guild.get_channel(cid) if cid else None
        if not isinstance(channel,discord.TextChannel): return False
        embed=discord.Embed(title='📄 Контракты',description='Если вы желаете запуститься в контракт, вы должны запустить набор в пик здесь.\n\nПосле запуска начнётся таймер **15 минут** и откроется набор в контракт.',color=discord.Color.blurple())
        await channel.send(embed=embed,view=ContractPanelView(self)); return True
    async def start_contract(self,interaction):
        if not can_start_contract(interaction.user): return await interaction.response.send_message('❌ У вас нет роли для запуска набора.',ephemeral=True)
        cfg=get_config(interaction.guild.id)
        if not cfg.get('contract_channel_id') or interaction.channel.id != cfg['contract_channel_id']:
            return await interaction.response.send_message('❌ Запускать контракт можно только в настроенном канале контрактов.',ephemeral=True)
        if get_active(interaction.guild.id): return await interaction.response.send_message('❌ Сейчас уже идёт набор в контракт.',ephemeral=True)
        end=now()+timedelta(minutes=DURATION_MINUTES); cid=create_contract(interaction.guild.id,interaction.user.id,end)
        role=interaction.guild.get_role(cfg.get('family_role_id')) if cfg.get('family_role_id') else None
        embed=discord.Embed(title='📄 Набор в контракт открыт',description=f'**Инициатор:** {interaction.user.mention}\n**Окончание:** <t:{int(end.timestamp())}:R>\n**Участников:** 0',color=discord.Color.green())
        await interaction.response.send_message(content=role.mention if role else None,embed=embed,view=ContractView(self,cid))
        msg=await interaction.original_response();
        # Save message id for potential future migrations; not required for operation.
        conn=get_connection(); conn.execute('UPDATE contracts SET participants=participants WHERE id=?',(cid,)); conn.commit(); conn.close()
    async def refresh(self,interaction,c):
        ids=csv_ids(c['participants']); mentions=', '.join(f'<@{x}>' for x in ids) or 'Нет участников.'
        embed=discord.Embed(title='📄 Набор в контракт открыт',description=f"**Инициатор:** <@{c['starter_id']}>\n**Окончание:** <t:{int(from_iso(c['ends_at']).timestamp())}:R>\n**Участников:** {len(ids)}\n\n{mentions}",color=discord.Color.green())
        try: await interaction.message.edit(embed=embed,view=ContractView(self,c['id']))
        except discord.HTTPException: pass
    async def join(self,interaction,cid):
        if not can_join_contract(interaction.user): return await interaction.response.send_message('❌ У вас нет роли для участия в контракте.',ephemeral=True)
        c=get_contract(cid)
        if not c or not c['active']: return await interaction.response.send_message('❌ Этот набор уже завершён.',ephemeral=True)
        if from_iso(c['ends_at'])<=now(): return await interaction.response.send_message('❌ Время набора уже закончилось.',ephemeral=True)
        ids=csv_ids(c['participants'])
        if interaction.user.id in ids: return await interaction.response.send_message('ℹ️ Вы уже записаны.',ephemeral=True)
        ids.append(interaction.user.id); save_participants(cid,ids); c=get_contract(cid)
        await interaction.response.send_message('✅ Вы записаны в контракт.',ephemeral=True); await self.refresh(interaction,c)
    async def leave(self,interaction,cid):
        c=get_contract(cid)
        if not c or not c['active']: return await interaction.response.send_message('❌ Этот набор уже завершён.',ephemeral=True)
        ids=[x for x in csv_ids(c['participants']) if x!=interaction.user.id]
        save_participants(cid,ids); c=get_contract(cid)
        await interaction.response.send_message('✅ Вы выписаны.',ephemeral=True); await self.refresh(interaction,c)
    @tasks.loop(seconds=15)
    async def expire_task(self):
        for guild in self.bot.guilds:
            c=get_active(guild.id)
            if not c or from_iso(c['ends_at'])>now(): continue
            close_contract(c['id']); cfg=get_config(guild.id); channel=guild.get_channel(cfg.get('contract_channel_id')) if cfg.get('contract_channel_id') else None
            if isinstance(channel,discord.TextChannel):
                ids=csv_ids(c['participants']); mentions=', '.join(f'<@{x}>' for x in ids) or 'Никто не записался.'
                embed=discord.Embed(title='📄 Набор закончен',description=f'Процесс пика закончен.\n\n**Участники:**\n{mentions}',color=discord.Color.red())
                await channel.send(embed=embed)
    @expire_task.before_loop
    async def before_expire(self): await self.bot.wait_until_ready()
    @app_commands.command(name='contracts-panel',description='Опубликовать панель контрактов')
    async def contracts_panel(self,interaction):
        if not can_start_contract(interaction.user): return await interaction.response.send_message('❌ Нет доступа.',ephemeral=True)
        ok=await self.publish_panel(interaction.guild); await interaction.response.send_message('✅ Панель опубликована.' if ok else '❌ Сначала настройте канал контрактов.',ephemeral=True)

async def setup(bot): await bot.add_cog(Contracts(bot))
