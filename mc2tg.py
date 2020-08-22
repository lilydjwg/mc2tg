#!/usr/bin/python3

import asyncio
import os
import sys
import json
import regex as re
import logging

from aiogram import Bot, Dispatcher, types

__version__ = '0.1'

def load_messages(lang):
  file = f'{lang}.json'
  dir = os.path.dirname(__file__)
  datafile = os.path.join(dir, 'data', file)
  with open(datafile) as f:
    return json.load(f)

def msgs2re(msgs, names):
  retext = '|'.join(msg2re(msg, names) for msg in msgs)
  return re.compile(retext)

def msg2re(msg, names):
  return ''.join(_msg2re(msg, names))

def _msg2re(msg, names):
  placeholder_re = re.compile(r'(%s|%(\d+)\$s)')
  it = placeholder_re.splititer(msg)
  idx = 0
  while True:
    try:
      a = next(it)
      if a == '%s':
        next(it)
        name = names[idx]
        yield f'(?P<{name}>.*?)'
        idx += 1
      elif re.fullmatch(r'%\d+\$s', a):
        name = names[int(next(it))-1]
        yield f'(?P<{name}>.*?)'
      else:
        yield re.escape(a)
    except StopIteration:
      return

class _Replacer:
  def __init__(self, items):
    self.items = items
    self.count = 0

  def __call__(self, match):
    if x := match.group(1):
      idx = int(x) - 1
    else:
      idx = self.count
      self.count += 1

    return self.items[idx]

def msg_format(msg, items):
  return re.sub(r'%s|%(\d+)\$s', _Replacer(items), msg)

class McBot:
  msg_re = re.compile(r'^\[.*\]\ \[Server\ thread/INFO\]:\ (.*)$')
  chat_msg_re = re.compile(r'<([^>]+)> (.*)')
  player_re = re.compile(r'(\S+) (joined|left) the game')
  online_re = re.compile(r'There are (\d+) of a max of \d+ players online: (.*)')
  advancement_re = re.compile(r'(?P<who>.*?) has (?:completed|reached|made) the (?P<type>challenge|goal|advancements) \[(?P<what>.*?)\]')
  death_re = None

  advancement_action_map = {
    'challenge': '完成了挑战',
    'goal': '达成了目标',
    'advancement': '取得了进度',
  }

  def __init__(self, mc_q, tg_q):
    self.mc_q = mc_q
    self.tg_q = tg_q

    en_msgs = load_messages('en_us')
    zh_msgs = load_messages('zh_cn')

    advancements = {}
    death_msgs = []
    death_msg_map = {}
    for k, v in en_msgs.items():
      if k.startswith('advancements.'):
        advancements[v] = zh_msgs[k]
      elif k.startswith('death.'):
        death_msgs.append(v)
        death_msg_map[
          re.sub(r'%\d+\$s', '%s', v)] = zh_msgs[k]

    self.death_re = msgs2re(death_msgs, ['player', 'killer', 'tool'])
    self.advancements = advancements
    self.death_msg_map = death_msg_map

  async def run(self):
    mc2tg_task = asyncio.create_task(self.mc2tg())
    tg2mc_task = asyncio.create_task(self.tg2mc())
    await asyncio.wait(
      [mc2tg_task, tg2mc_task],
      return_when = asyncio.FIRST_COMPLETED,
    )

  async def tg2mc(self):
    while True:
      msg = await self.mc_q.get()
      if msg == 'online':
        print('\x15list')
      else:
        print('\x15tellraw @a', json.dumps({'text': msg}, ensure_ascii=False))

  async def mc2tg(self):
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    read_protocol = asyncio.StreamReaderProtocol(reader)
    _, _ = await loop.connect_read_pipe(
      lambda: read_protocol, sys.stdin.buffer)
    sys.stdout = os.fdopen(1, mode='w', buffering=1)

    while not reader.at_eof():
      line = await reader.readline()
      line = line.decode('utf-8', errors='replace').rstrip()
      if m := self.msg_re.match(line):
        logging.info('MC msg: %s', line)
        try:
          self.process_msg(m.group(1))
        except Exception:
          logging.exception('error processing minecraft message %s', line)

  def process_msg(self, msg):
    if m := self.chat_msg_re.fullmatch(msg):
      if m.group(2) == 'ping':
        self.mc_q.put_nowait('pong')
        return
      reply = msg
    elif m := self.online_re.fullmatch(msg):
      n = int(m.group(1))
      if n > 0:
        people = m.group(2)
        reply = f'当前 {n} 人在线：{people}'
      else:
        reply = '当前无人在线 :-('
    elif m := self.player_re.fullmatch(msg):
      who = m.group(1)
      action = '加入' if m.group(2) == 'joined' else '退出'
      reply = f'{who} {action}了游戏'
    elif m := self.advancement_re.fullmatch(msg):
      who = m.group('who')
      type = m.group('type')
      action = self.advancement_action_map[type]
      what = self.advancements[m.group('what')]
      reply = f'{who} {action}：{what}'
    elif m := self.death_re.fullmatch(msg):
      items = [m.group('player')]
      if x:= m.group('killer'):
        items.append(x)
        if x:= m.group('tool'):
          items.append(x)

      for g in range(len(items), 0, -1):
        s, e = m.span(g)
        msg = msg[:s] + '%s' + msg[e:]
      zhmsg = self.death_msg_map[msg]
      reply = msg_format(zhmsg, items)
    else:
      return

    self.tg_q.put_nowait(reply)

class TgBot:
  group_id = None

  def __init__(self, token, group, proxy, tg_q, mc_q):
    self.tg_q = tg_q
    self.mc_q = mc_q

    if group is not None:
      try:
        self.group_id = int(group)
      except ValueError:
        self.group_id = group

    bot = Bot(token=token, proxy=proxy)
    dp = Dispatcher(bot)

    dp.register_message_handler(
      self.on_about,
      commands=['about'],
    )

    dp.register_message_handler(
      self.on_ping,
      commands=['ping'],
    )

    dp.register_message_handler(
      self.on_online,
      commands=['online'],
    )

    dp.register_message_handler(
      self.on_message,
      content_types = types.ContentTypes.ANY,
    )

    dp.register_edited_message_handler(
      self.on_message,
      content_types = types.ContentTypes.ANY,
    )

    self.dp = dp
    self.bot = bot

  def _check_group(self, message):
    if message.chat.id == self.group_id:
      return True

    if message.chat.username == self.group_id:
      return True

    return False

  async def on_message(self, message):
    logging.info('TG msg: %s', message)
    if not self._check_group(message):
      return

    who = message.from_user.full_name
    if text := message.text:
      if m := message.reply_to_message:
        repliee = m.from_user.full_name
        if m.from_user.id == (await self.bot.me).id:
          if u := re.match('<([^>]+)> ', m.text):
            repliee = u.group(1)
        reply = f'[t] {who} 回复 {repliee}: {text}'
      else:
        reply = f'[t] {who}: {text}'
      if message.edit_date:
        reply += ' (已编辑)'
    elif message.photo:
      reply = f'[t] {who} 发送了一张图片'
    elif message.sticker:
      reply = f'[t] {who} 发送了一张贴纸'
    else:
      reply = f'[t] {who} 发送了一些其它的东西'

    self.mc_q.put_nowait(reply)

  async def on_ping(self, message):
    await message.reply('pong')

  async def on_about(self, message):
    await message.reply(f'mc2tg {__version__}')

  async def on_online(self, message):
    if not self._check_group(message):
      return

    self.mc_q.put_nowait('online')

  async def run(self):
    mc2tg_task = asyncio.create_task(self.mc2tg())
    tg2mc_task = asyncio.create_task(self.tg2mc())
    await asyncio.wait(
      [mc2tg_task, tg2mc_task],
      return_when = asyncio.FIRST_COMPLETED,
    )

  async def tg2mc(self):
    await self.dp.skip_updates()
    await self.dp.start_polling()

  async def mc2tg(self):
    while True:
      msg = await self.tg_q.get()
      if not self.group_id:
        continue
      await self.bot.send_message(
        self.group_id, msg)

async def main(token, group, proxy):
  tg_q = asyncio.Queue()
  mc_q = asyncio.Queue()
  tgbot = TgBot(token, group, proxy, tg_q, mc_q)
  mcbot = McBot(mc_q, tg_q)
  tgtask = asyncio.create_task(tgbot.run())
  mctask = asyncio.create_task(mcbot.run())
  await asyncio.wait(
    [tgtask, mctask],
    return_when = asyncio.FIRST_COMPLETED,
  )

if __name__ == '__main__':
  import argparse
  from nicelogger import enable_pretty_logging

  parser = argparse.ArgumentParser(
    description='A bot bridging minecraft and telegram group')
  parser.add_argument('--proxy',
                      help='The proxy to use')
  parser.add_argument('--group', required=True,
                      help='The group to sync with')
  parser.add_argument('--logfile',
                      help='log file (may be a named pipe)')
  parser.add_argument('--loglevel', default='info',
                      choices=['debug', 'info', 'warn', 'error'],
                      help='log level')
  args = parser.parse_args()

  if args.logfile:
    fd = os.open(args.logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(fd, 2)
    os.close(fd)
    sys.stderr = os.fdopen(2, mode='w', buffering=1)

  token = os.environ.pop('TOKEN', None)
  if not token:
    sys.exit('Please pass bot token in environment variable TOKEN.')

  enable_pretty_logging(args.loglevel.upper())

  try:
    asyncio.run(main(token, args.group, args.proxy))
  except KeyboardInterrupt:
    pass
