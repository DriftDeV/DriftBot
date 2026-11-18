"""Oggetti finti condivisi (voice client, interazione, canale vocale)."""

from types import SimpleNamespace

import discord


class FakeSource(discord.AudioSource):
    def __init__(self, url, **kwargs):
        self.url = url

    def read(self):
        return b""


class FakeVC:
    def __init__(self, channel):
        self.channel = channel
        self.playing = False
        self.paused = False
        self.connected = True
        self.after = None
        self.source = None
        self.played = []

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.playing and not self.paused

    def is_paused(self):
        return self.paused

    def play(self, source, after=None):
        self.playing, self.paused, self.after, self.source = True, False, after, source
        self.played.append(source)

    def stop(self):
        was_playing = self.playing
        self.playing = self.paused = False
        self.source = None
        if was_playing and self.after:
            self.after(None)

    async def disconnect(self):
        self.connected = False

    async def move_to(self, channel):
        self.channel = channel


class FakeGuild:
    def __init__(self, guild_id=1):
        self.id = guild_id
        self.voice_client = None


def make_channel(guild, name="vc", fail_connect=False):
    channel = SimpleNamespace(name=name, id=hash(name) % 10_000, members=[])

    async def connect(cls=None):
        if fail_connect:
            raise RuntimeError("connessione rifiutata")
        guild.voice_client = FakeVC(channel)
        return guild.voice_client

    channel.connect = connect
    return channel


class FakeInteraction:
    """Interazione finta: registra ogni messaggio inviato in `sent` (testo, kwargs)."""

    def __init__(self, guild, channel=None, user_id=42, name="alice"):
        self.guild = guild
        self.guild_id = guild.id
        self.channel = SimpleNamespace(sent=[])

        async def channel_send(content=None, **kwargs):
            self.channel.sent.append((content, kwargs))

        self.channel.send = channel_send
        self.user = SimpleNamespace(
            id=user_id,
            name=name,
            display_name=name,
            mention=f"<@{user_id}>",
            voice=SimpleNamespace(channel=channel) if channel else None,
        )
        if channel is not None:
            channel.members.append(self.user)
        self.sent = []
        self._done = False
        self.deferred = False       # defer() chiamato (dopo un defer pubblico `ephemeral` viene ignorato da Discord)
        self.command = None
        self.response = SimpleNamespace(
            send_message=self._send_first,
            defer=self._defer,
            edit_message=self._edit,
            is_done=lambda: self._done,
        )
        self.followup = SimpleNamespace(send=self._send)
        self.followup_error = None  # se impostato, followup.send solleva questa eccezione
        self.edits = []             # chiamate a edit_original_response
        self.message_edits = []     # chiamate a response.edit_message (click su un pulsante)
        self.edit_error = None      # se impostato, edit_original_response solleva questa eccezione

    async def edit_original_response(self, **kwargs):
        if self.edit_error is not None:
            raise self.edit_error
        self.edits.append(kwargs)

    async def _send_first(self, content=None, **kwargs):
        self._done = True
        self.sent.append((content, kwargs))

    async def _defer(self, **kwargs):
        self._done = True
        self.deferred = True

    async def _edit(self, **kwargs):
        self._done = True
        self.message_edits.append(kwargs)

    async def _send(self, content=None, **kwargs):
        if self.followup_error is not None:
            raise self.followup_error
        self.sent.append((content, kwargs))

    @property
    def last(self):
        content, kwargs = self.sent[-1]
        return content if content is not None else kwargs.get("embed")

    def texts(self):
        return [c for c, _ in self.sent if isinstance(c, str)]
