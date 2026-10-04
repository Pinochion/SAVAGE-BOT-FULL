from datetime import datetime, timezone
import discord
from discord.ext import commands
from discord import app_commands
from utils.config_db import get_connection, get_config, parse_ids, user_priority
from utils.permissions import can_start_reaction

def csv_ids(v): return [int(x) for x in str(v or '').split(',') if x.strip().isdigit()]
def save_participants(eid,ids):
    c=get_connection(); c.execute('UPDATE reaction_events SET participants=? WHERE id=?',(','.join(map(str,ids)),eid)); c.commit(); c.close()
def get_event(eid):
    c=get_connection(); r=c.execute('SELECT * FROM reaction_events WHERE id=?',(eid,)).fetchone(); c.close(); return dict(r) if r else None
def create_event(guild_id,channel_id,creator_id,title,event_time,slots):
    c=get_connection(); cur=c.execute('INSERT INTO reaction_events(guild_id,channel_id,message_id,creator_id,title,event_time,slots,participants,active) VALUES(?,?,?,?,?,?,?,?,1)',(guild_id,channel_id,0,creator_id,title,event_time,slots,'')); eid=cur.lastrowid; c.commit(); c.close(); return eid

def set_message_id(eid,mid):
    c=get_connection(); c.execute('UPDATE reaction_events SET message_id=? WHERE id=?',(mid,eid)); c.commit(); c.close()

class ReactionModal(discord.ui.Modal,title='Набор на контент'):
    name=discord.ui.TextInput(label='Название',max_length=100,placeholder='Название контента')
    time=discord.ui.TextInput(label='Время',max_length=50,placeholder='21:00')
    slots=discord.ui.TextInput(label='Количество человек',max_length=3,placeholder='5')
    def __init__(self,cog): super().__init__(); self.cog=cog
    async def on_submit(self,interaction):
        try: slots=int(self.slots.value); assert 1<=slots<=100
        except: return await interaction.response.send_message('❌ Количество мест должно быть от 1 до 100.',ephemeral=True)
        cfg=get_config(interaction.guild.id); channel=interaction.guild.get_channel(cfg.get('reaction_channel_id')) if cfg.get('reaction_channel_id') else None
        if not isinstance(channel,discord.TextChannel): return await interaction.response.send_message('❌ Канал реакций не настроен.',ephemeral=True)
        if interaction.channel.id!=channel.id: return await interaction.response.send_message(f'❌ Команду можно использовать только в {channel.mention}.',ephemeral=True)
        eid=create_event(interaction.guild.id,channel.id,interaction.user.id,self.name.value.strip(),self.time.value.strip(),slots)
        embed=build_embed(interaction.guild,get_event(eid))
        await interaction.response.send_message(embed=embed,view=ReactionView(self.cog,eid))
        msg=await interaction.original_response(); set_message_id(eid,msg.id)


def build_embed(guild,e):
    ids=csv_ids(e['participants']); lines=[]; cfg=get_config(guild.id)
    for n,uid in enumerate(ids,1):
        m=guild.get_member(uid); lines.append(f'**{n}.** {m.mention if m else f"<@{uid}>"}')
    return discord.Embed(title=f'🎬 {e["title"]}',description=f'**Время:** {e["event_time"]}\n**Мест:** {len(ids)}/{e["slots"]}\n\n'+'\n'.join(lines or ['Пока никто не записался.'])+'\n\n**Приоритет:** MAIN → DEFAULT → ACADEMY',color=discord.Color.blurple())

class ReactionView(discord.ui.View):
    def __init__(self,cog,eid):
        super().__init__(timeout=None); self.cog=cog; self.eid=eid
        self.children[0].custom_id=f'reaction:join:{eid}'
        self.children[1].custom_id=f'reaction:leave:{eid}'
        self.children[2].custom_id=f'reaction:time:{eid}'
    @discord.ui.button(label='🎬 Поставить реакцию',style=discord.ButtonStyle.success,custom_id='reaction:join')
    async def join(self,i,b): await self.cog.join(i,self.eid)
    @discord.ui.button(label='❌ Убрать реакцию',style=discord.ButtonStyle.danger,custom_id='reaction:leave')
    async def leave(self,i,b): await self.cog.leave(i,self.eid)
    @discord.ui.button(label='🕒 Изменить время',style=discord.ButtonStyle.secondary,custom_id='reaction:time')
    async def time(self,i,b): await self.cog.change_time(i,self.eid)

class TimeModal(discord.ui.Modal,title='Изменить время'):
    time=discord.ui.TextInput(label='Новое время',max_length=50)
    def __init__(self,cog,eid): super().__init__(); self.cog=cog; self.eid=eid
    async def on_submit(self,i):
        e=get_event(self.eid); cfg=get_config(i.guild.id)
        if not can_start_reaction(i.user): return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        c=get_connection(); c.execute('UPDATE reaction_events SET event_time=? WHERE id=?',(self.time.value.strip(),self.eid)); c.commit(); c.close(); e=get_event(self.eid)
        await i.response.edit_message(embed=build_embed(i.guild,e),view=ReactionView(self.cog,self.eid))

class Reactions(commands.Cog):
    def __init__(self,bot): self.bot=bot
    async def cog_load(self):
        pass

    async def restore_views(self):
        c=get_connection(); rows=c.execute('SELECT id FROM reaction_events WHERE active=1').fetchall(); c.close()
        for r in rows: self.bot.add_view(ReactionView(self,r['id']))
    async def refresh(self,i,eid):
        e=get_event(eid)
        try: await i.message.edit(embed=build_embed(i.guild,e),view=ReactionView(self,eid))
        except discord.HTTPException: pass
    async def join(self,i,eid):
        e=get_event(eid)
        if not e or not e['active']: return await i.response.send_message('❌ Набор уже закрыт.',ephemeral=True)
        cfg=get_config(i.guild.id); p=user_priority(cfg,i.user)
        if p<=0: return await i.response.send_message('❌ Для участия нужна роль MAIN, DEFAULT или ACADEMY.',ephemeral=True)
        ids=csv_ids(e['participants'])
        if i.user.id in ids: return await i.response.send_message('ℹ️ Вы уже записаны.',ephemeral=True)
        if len(ids)<e['slots']: ids.append(i.user.id)
        else:
            priorities={uid:user_priority(cfg,i.guild.get_member(uid)) if i.guild.get_member(uid) else 0 for uid in ids}
            lower=[uid for uid,pr in priorities.items() if pr<p]
            if not lower: return await i.response.send_message('❌ Все места заняты участниками с равным или более высоким приоритетом.',ephemeral=True)
            victim=min(lower,key=lambda uid:priorities[uid]); ids[ids.index(victim)]=i.user.id
            await i.response.send_message(f'✅ Вы заняли место с учётом приоритета. Вытеснен <@{victim}>.',ephemeral=True); save_participants(eid,ids); return await self.refresh(i,eid)
        save_participants(eid,ids); await i.response.send_message('✅ Реакция поставлена.',ephemeral=True); await self.refresh(i,eid)
    async def leave(self,i,eid):
        e=get_event(eid); ids=[x for x in csv_ids(e['participants']) if x!=i.user.id]; save_participants(eid,ids); await i.response.send_message('✅ Реакция убрана.',ephemeral=True); await self.refresh(i,eid)
    async def change_time(self,i,eid):
        if not can_start_reaction(i.user): return await i.response.send_message('❌ Только роли, которым разрешён запуск набора, могут менять время.',ephemeral=True)
        await i.response.send_modal(TimeModal(self,eid))
    @app_commands.command(name='reactions',description='Система наборов на контент')
    @app_commands.describe(action='start')
    async def reactions(self,interaction,action:str):
        if action.lower()!='start': return await interaction.response.send_message('Используйте `/reactions start`.',ephemeral=True)
        if not can_start_reaction(interaction.user): return await interaction.response.send_message('❌ У вас нет права запускать набор.',ephemeral=True)
        await interaction.response.send_modal(ReactionModal(self))

async def setup(bot): await bot.add_cog(Reactions(bot))
