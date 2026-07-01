"""
====================================================================
  LANAX.4 — Highrise All-in-One Bot  (MULTI-ROOM + FLOOR-TELEPORT)
====================================================================
Ye bot ab EK SAATH 2 rooms mein chal sakta hai (same bot account,
alag-alag rooms), aur owner "floors" set/teleport kar sakta hai
(jaise: first floor, second floor, top floor — jo bhi naam do).

--------------------------------------------------------------------
IMPORTANT FIX (pehle wali "Room not found" error):
--------------------------------------------------------------------
Pehle ROOM_ID = "6894bd39e3e4a405517cb530" set tha — lekin ye
aapka BOT ka apna ID hai, koi room ID nahi. Isiliye Highrise
"Room not found" error deta raha.

Aapke diye hue links:
6894bd39e3e4a405517cb530&ownedRoomId=64dc75dbf71c6ae119bffa47&...
6894bd39e3e4a405517cb530&ownedRoomId=63fcc70dfb16e9c663269160&...

  -> "id="        = bot/world ka ID   (64dc75dbf71c6ae119bffa47)
  -> "ownedRoomId="  = ASLI ROOM ID (63fcc70dfb16e9c663269160)

--------------------------------------------------------------------
RENDER PAR DEPLOY KARNE KA TAREEKA:
--------------------------------------------------------------------
1) requirements.txt mein sirf yeh rakho (neeche wali file dekho):
       highrise-bot-sdk==25.1.0

2) Render Dashboard -> Environment -> Environment Variables mein add karo:
       PYTHON_VERSION = 3.11.9
   (pendulum/wheel build fail isi wajah se ho raha tha — naya Python
   version SDK ki dependencies ke saath match nahi kar raha tha)

3) Render "Start Command" ko is se badal do:
       python bot.py
   (highrise CLI command ab NAHI chalega kyunki ab hum 2 rooms ek
   saath ek hi Python process mein khud start kar rahe hain)

--------------------------------------------------------------------
PUBLIC (koi bhi room mein use kar sakta hai):
  - Chat mein sirf NUMBER bhejo (1 se 300 tak) -> apna emote chalega
  - "0" ya "!stop"       -> apna chal raha emote turant ROK do
  - "!emotes"            -> kitne emotes active hain, batata hai
  - "!emotes <page>"     -> emote list page-wise dikhata hai (10 per page)

OWNER-ONLY COMMANDS (sirf LANAX4 / OWNER_USER_ID use kar sakta hai)
  Poori list "!owner" chat karke bhi mil jaayegi in-game.

  MOVEMENT / FLOOR TELEPORT (NAYA):
    !come                 -> Bot khud tumhare paas teleport ho jaata hai
    !setfloor <naam>       -> Tumhari abhi ki position ko "<naam>" floor
                               ke naam se save kar deta hai
                               (e.g. !setfloor first, !setfloor second,
                                !setfloor top)
    !floor <naam>          -> Tum us saved floor par turant teleport ho jaate ho
    !floors                -> Saare saved floor naam dikhata hai
    !delfloor <naam>        -> Ek saved floor delete karta hai
    !tp x y z              -> Raw coordinates par teleport
    !tpto <user>           -> Kisi user ke paas teleport
    !bring <user>           -> Kisi user ko apne paas la do
    !goto <user>            -> Bot khud kisi user ke paas walk karta hai
    !follow / !unfollow    -> Bot tumhe follow karna start/stop kare
====================================================================
"""

import asyncio
import json
import os
import time
from datetime import datetime

from highrise import BaseBot, User, __main__
from highrise.__main__ import BotDefinition
from highrise.models import Position, SessionMetadata


# ============================ CONFIG ================================
BOT_NAME = "LANAX.4"
BOT_TOKEN = "c58d1869fbad962a328c20a2abc0333400a128ecbbf8c6d1bf9382b44cb2f87a"

# Do rooms — same bot token, alag room IDs (ownedRoomId waale)
ROOMS = [
    {"label": "Room-1", "room_id": "64dc75dbf71c6ae119bffa47"},
    {"label": "Room-2", "room_id": "63fcc70dfb16e9c663269160"},
]

OWNER_USERNAME = "LANAX4"
OWNER_USER_ID = ""   # agar exact User ID pata ho toh yahan daal do (zyada reliable)

# Owner apne aur logon ko bhi "trusted helper" bana sakta hai jinke paas
# limited owner-jaisi command access ho (emote-moderation jaisi cheezein
# nahi, sirf halke commands). Yahan unke usernames daalo (lowercase).
TRUSTED_HELPERS = set()   # example: {"myfriend123", "secondaccount"}

# Public emote command ke liye cooldown (seconds) — spam rokne ke liye
EMOTE_COOLDOWN_SECONDS = 2.0

# Naye user ko welcome message bhejna hai ya nahi
WELCOME_MESSAGE_ENABLED = True

# "!stop" / "0" command jab koi apna chalta hua (looping) emote rokna chahe,
# Highrise API mein "cancel emote" jaisa koi direct function nahi hota —
# isliye trick yeh hai ki ek chhota, non-looping emote turant chala do,
# jo purane looping emote ko turant cancel karke user ko wapas normal
# khada (idle) kar deta hai. Neeche wala ID change kiya ja sakta hai.
STOP_EMOTE_ID = "emote-wave"

# Floor positions ab har room ke liye alag JSON file mein save hongi
# (taaki restart hone par bhi floors yaad rahein)
FLOORS_DIR = "./floor_data"


# ============================ EMOTES (1-200) =========================
EMOTES = {
    "1": "emote-hello",
    "2": "emote-wave",
    "3": "emoji-thumbsup",
    "4": "emoji-angry",
    "5": "emote-kiss",
    "6": "emote-tired",
    "7": "dance-macarena",
    "8": "dance-tiktok2",
    "9": "dance-shoppingcart",
    "10": "dance-russian",
    "11": "dance-pinguin",
    "12": "emote-laughing",
    "13": "emote-cry",
    "14": "emote-yes",
    "15": "emote-no",
    "16": "emote-heartfingers",
    "17": "emote-model-walk",
    "18": "emote-snowball-fight",
    "19": "emote-teleport",
    "20": "dance-blackpink",
    "21": "dance-tiktok8",
    "22": "dance-tiktok9",
    "23": "dance-weird",
    "24": "dance-anime",
    "25": "dance-jinglebells",
    "26": "emote-hero",
    "27": "emote-maniac",
    "28": "emote-cutesalute",
    "29": "emote-sad",
    "30": "emote-shy",
    "31": "emote-timejump",
    "32": "emote-model-poses",
    "33": "idle-loop-sitfloor",
    "34": "idle-enthusiastic",
    "35": "idle-layingdown",
    "36": "emote-zombierun",
    "37": "emote-superpose",
    "38": "emote-frog",
    "39": "emote-creepycute",
    "40": "emote-elbowbump",
    "41": "emote-snake",
    "42": "emote-snowangel",
    "43": "emote-secrethandshake",
    "44": "emote-cutey",
    "45": "emote-teleporting",
    "46": "emote-float",
    "47": "emote-bow",
    "48": "emote-curtsy",
    "49": "emote-clap",
    "50": "emote-facepalm",
}

# Auto-fill 51-300 with placeholders so the dict already has 300 slots
for _n in range(51, 301):
    EMOTES[str(_n)] = f"REPLACE_ME_{_n}"


# ============================ BOT LOGIC ==============================
class Bot(BaseBot):
    def __init__(self, room_label: str = "Room"):
        super().__init__()
        self.room_label = room_label
        self.room_id = None
        self.bot_user_id = None
        self._last_emote_time = {}      # user_id -> timestamp (cooldown)
        self._last_emote_used = {}      # user_id -> emote_id (last emote they played)
        self._join_times = {}           # user_id -> datetime jab woh room mein aaya
        self._follow_target_username = None
        self._follow_task = None
        self._floors = {}               # floor_name -> {x,y,z,facing}
        self._floor_file = None

    # ------------------------- floor persistence -----------------------
    def _load_floors(self):
        if not self._floor_file:
            return
        try:
            if os.path.exists(self._floor_file):
                with open(self._floor_file, "r") as f:
                    self._floors = json.load(f)
        except Exception as e:
            print("Floor load error:", e)
            self._floors = {}

    def _save_floors(self):
        if not self._floor_file:
            return
        try:
            os.makedirs(os.path.dirname(self._floor_file), exist_ok=True)
            with open(self._floor_file, "w") as f:
                json.dump(self._floors, f)
        except Exception as e:
            print("Floor save error:", e)

    # ------------------------- lifecycle -----------------------------
    async def on_start(self, session_metadata: SessionMetadata) -> None:
        self.bot_user_id = session_metadata.user_id
        try:
            self.room_id = session_metadata.room_info.room_id
        except Exception:
            self.room_id = None
        os.makedirs(FLOORS_DIR, exist_ok=True)
        self._floor_file = os.path.join(FLOORS_DIR, f"{self.room_label}.json")
        self._load_floors()
        print(f"✅ {BOT_NAME} [{self.room_label}] connect ho gaya! bot_user_id = {self.bot_user_id}")
        try:
            await self.highrise.chat(
                f"🤖 {BOT_NAME} online hai! Chat mein number bhejo (1-{len(EMOTES)}) "
                f"apna emote chalane ke liye. Rokne ke liye '0' ya '!stop' bhejo. "
                f"Owner commands: !owner"
            )
        except Exception as e:
            print("Startup message error:", e)

    async def on_user_join(self, user: User, *args, **kwargs) -> None:
        join_time = datetime.now()
        self._join_times[user.id] = join_time
        time_str = join_time.strftime("%d-%b-%Y %I:%M %p")
        print(f"➡️ [{self.room_label}] {user.username} room mein aaya: {time_str}")
        if not WELCOME_MESSAGE_ENABLED:
            return
        try:
            await self.highrise.chat(f"👋 Welcome, {user.username}! (Aaye: {time_str})")
        except Exception as e:
            print("Welcome message error:", e)

    async def on_moderate(self, moderator_id: str, target_user_id: str, moderate_type, action_length=None) -> None:
        print(f"[{self.room_label}] Room moderated: mod={moderator_id} target={target_user_id} action={moderate_type} len={action_length}")

    async def on_message(self, user_id: str, conversation_id: str, is_new_conversation: bool) -> None:
        print(f"[{self.room_label}] DM received from {user_id} in conversation {conversation_id} (new={is_new_conversation})")

    # ------------------------- main chat handler ----------------------
    async def on_chat(self, user: User, message: str) -> None:
        text = message.strip()
        lower = text.lower()
        is_owner = self._is_owner(user)
        is_helper = is_owner or user.username.lower() in TRUSTED_HELPERS

        # ---------- Owner-only commands ----------
        if is_owner:
            handled = await self._handle_owner_command(user, text, lower)
            if handled:
                return

        # ---------- Trusted-helper (lighter) commands ----------
        if is_helper and not is_owner:
            handled = await self._handle_helper_command(user, text, lower)
            if handled:
                return

        # ---------- Public: apna chalta hua emote ROK do ----------
        if text == "0" or lower in ("!stop", "stop"):
            await self._stop_emote(user)
            return

        # ---------- Public numbered emotes (sabke liye free) ----------
        if text in EMOTES:
            emote_id = EMOTES[text]
            if emote_id.startswith("REPLACE_ME_"):
                return  # Owner ne abhi tak yeh number fill nahi kiya
            if not self._check_cooldown(user.id):
                return
            await self._try_emote(user.id, emote_id)
            self._last_emote_used[user.id] = emote_id
            return

        if lower in ("!emotes", "!list") or lower.startswith("!emotes "):
            await self._show_emote_page(lower)
            return

        if lower in ("!help", "!commands"):
            await self.highrise.chat(
                f"🎉 Number bhejo (1-{len(EMOTES)}) emote chalane ke liye. "
                "Rokne ke liye '0' ya '!stop' bhejo. "
                "'!emotes <page>' se list dekho. Owner hai toh '!owner' try karo."
            )
            return

    # ============================ OWNER COMMAND DISPATCH ==============
    async def _handle_owner_command(self, user: User, text: str, lower: str) -> bool:
        """Returns True if the message matched and was handled."""

        # ---- info / help ----
        if lower in ("!help", "!owner"):
            await self._send_owner_help()
            return True

        # ---- emote testing / management ----
        if lower.startswith("!test "):
            emote_id = text[6:].strip()
            await self._try_emote(user.id, emote_id, notify=user)
            return True

        if lower.startswith("!addemote "):
            parts = text[10:].strip().split(maxsplit=1)
            if len(parts) == 2 and parts[0].isdigit():
                EMOTES[parts[0]] = parts[1]
                await self.highrise.chat(f"✅ Emote #{parts[0]} = '{parts[1]}' add ho gaya.")
            else:
                await self.highrise.chat("⚠️ Format: !addemote <number> <emote_id>")
            return True

        if lower.startswith("!removeemote "):
            n = text[13:].strip()
            if n in EMOTES:
                EMOTES[n] = f"REPLACE_ME_{n}"
                await self.highrise.chat(f"🗑️ Emote #{n} remove ho gaya.")
            else:
                await self.highrise.chat("⚠️ Yeh number list mein nahi hai.")
            return True

        # ---- movement ----
        if lower == "!come":
            await self._bot_come_to_owner(user)
            return True

        if lower.startswith("!tp "):
            await self._teleport_owner_to_coords(user, text[4:].strip())
            return True

        if lower.startswith("!tpto "):
            await self._teleport_owner_to_user(user, text[6:].strip())
            return True

        if lower.startswith("!bring "):
            await self._bring_user_to_owner(user, text[7:].strip())
            return True

        if lower.startswith("!goto "):
            target_name = text[6:].strip()
            _, pos = await self._get_position(target_name)
            if pos is None:
                await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            else:
                await self.highrise.walk_to(pos)
                await self.highrise.chat(f"🚶 {target_name} ki taraf ja raha hoon...")
            return True

        if lower == "!follow":
            await self._start_follow(user.username)
            return True

        if lower == "!unfollow":
            await self._stop_follow()
            return True

        # ---- FLOOR TELEPORT (NAYA) ----
        if lower.startswith("!setfloor "):
            name = text[10:].strip()
            await self._set_floor(user, name)
            return True

        if lower.startswith("!floor "):
            name = text[7:].strip()
            await self._goto_floor(user, name)
            return True

        if lower in ("!floors", "!floorlist"):
            await self._list_floors()
            return True

        if lower.startswith("!delfloor "):
            name = text[10:].strip()
            await self._del_floor(name)
            return True

        # ---- messaging ----
        if lower.startswith("!announce "):
            msg = text[10:].strip()
            await self.highrise.chat(f"📢 {msg}")
            return True

        if lower.startswith("!whisper "):
            parts = text[9:].strip().split(maxsplit=1)
            if len(parts) == 2:
                target_name, msg = parts
                target_user, _ = await self._get_position(target_name)
                if target_user is None:
                    await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
                else:
                    try:
                        await self.highrise.send_whisper(target_user.id, msg)
                        await self.highrise.chat(f"✉️ Whisper bhej diya {target_name} ko.")
                    except Exception as e:
                        print("Whisper error:", e)
                        await self.highrise.chat("⚠️ Whisper fail ho gaya.")
            else:
                await self.highrise.chat("⚠️ Format: !whisper <username> <message>")
            return True

        if lower.startswith("!react "):
            parts = text[7:].strip().split(maxsplit=1)
            if len(parts) == 2:
                target_name, reaction = parts
                target_user, _ = await self._get_position(target_name)
                if target_user is None:
                    await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
                else:
                    try:
                        await self.highrise.react(reaction, target_user.id)
                    except Exception as e:
                        print("React error:", e)
                        await self.highrise.chat("⚠️ Reaction fail ho gaya (valid options jaise: heart, clap, wave, thumbs, wink, laugh).")
            else:
                await self.highrise.chat("⚠️ Format: !react <username> <reaction>")
            return True

        # ---- room moderation (apne hi room mein use karo) ----
        if lower.startswith("!kick "):
            await self._moderate(text[6:].strip(), "kick")
            return True

        if lower.startswith("!mute "):
            parts = text[6:].strip().split()
            target_name = parts[0] if parts else ""
            minutes = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            await self._moderate(target_name, "mute", minutes)
            return True

        if lower.startswith("!unmute "):
            await self._moderate(text[8:].strip(), "unmute")
            return True

        if lower.startswith("!ban "):
            await self._moderate(text[5:].strip(), "ban")
            return True

        if lower.startswith("!unban "):
            await self._moderate(text[7:].strip(), "unban")
            return True

        if lower.startswith("!mod "):
            await self._set_privilege(text[5:].strip(), "moderator")
            return True

        if lower.startswith("!unmod "):
            await self._set_privilege(text[7:].strip(), "resident")
            return True

        if lower.startswith("!designer "):
            await self._set_privilege(text[10:].strip(), "designer")
            return True

        # ---- trusted helper management ----
        if lower.startswith("!addhelper "):
            name = text[11:].strip().lower()
            TRUSTED_HELPERS.add(name)
            await self.highrise.chat(f"✅ {name} ab trusted helper hai.")
            return True

        if lower.startswith("!removehelper "):
            name = text[14:].strip().lower()
            TRUSTED_HELPERS.discard(name)
            await self.highrise.chat(f"🗑️ {name} ab helper nahi hai.")
            return True

        # ---- voice chat ----
        if lower.startswith("!voiceadd "):
            target_name = text[10:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            else:
                try:
                    await self.highrise.add_user_to_voice(target_user.id)
                    await self.highrise.chat(f"🎤 {target_name} ko voice chat mein add kar diya.")
                except Exception as e:
                    print("Voice add error:", e)
                    await self.highrise.chat("⚠️ Voice add fail ho gaya.")
            return True

        if lower.startswith("!voiceremove "):
            target_name = text[13:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            else:
                try:
                    await self.highrise.remove_user_from_voice(target_user.id)
                    await self.highrise.chat(f"🔇 {target_name} ko voice chat se remove kar diya.")
                except Exception as e:
                    print("Voice remove error:", e)
                    await self.highrise.chat("⚠️ Voice remove fail ho gaya.")
            return True

        # ---- economy ----
        if lower.startswith("!tip "):
            parts = text[5:].strip().split()
            if len(parts) == 2:
                target_name, amount = parts
                target_user, _ = await self._get_position(target_name)
                if target_user is None:
                    await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
                else:
                    try:
                        await self.highrise.tip_user(target_user.id, amount)
                        await self.highrise.chat(f"💰 {target_name} ko {amount} tip bhej diya.")
                    except Exception as e:
                        print("Tip error:", e)
                        await self.highrise.chat(
                            "⚠️ Tip fail ho gaya. Valid amounts: gold_bar_1, gold_bar_5, "
                            "gold_bar_10, gold_bar_50, gold_bar_100, gold_bar_500, gold_bar_1k, "
                            "gold_bar_5000, gold_bar_10k"
                        )
            else:
                await self.highrise.chat("⚠️ Format: !tip <username> <gold_bar_amount>")
            return True

        if lower == "!wallet":
            try:
                wallet = await self.highrise.get_wallet()
                await self.highrise.chat(f"💼 Bot wallet: {wallet.content}")
            except Exception as e:
                print("Wallet error:", e)
                await self.highrise.chat("⚠️ Wallet fetch nahi ho paya.")
            return True

        # ---- room control ----
        if lower.startswith("!sendto "):
            parts = text[8:].strip().split()
            if len(parts) == 2:
                target_name, dest_room_id = parts
                target_user, _ = await self._get_position(target_name)
                if target_user is None:
                    await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
                else:
                    try:
                        await self.highrise.move_user_to_room(target_user.id, dest_room_id)
                        await self.highrise.chat(f"🚪 {target_name} ko doosre room mein bhej diya.")
                    except Exception as e:
                        print("Move room error:", e)
                        await self.highrise.chat("⚠️ Move fail ho gaya.")
            else:
                await self.highrise.chat("⚠️ Format: !sendto <username> <room_id>")
            return True

        if lower == "!who":
            try:
                room_users = (await self.highrise.get_room_users()).content
                names = ", ".join(ru.username for ru, _ in room_users)
                await self.highrise.chat(f"👥 Room mein: {names}" if names else "Room khaali hai.")
            except Exception as e:
                print("Who error:", e)
            return True

        if lower.startswith("!joined "):
            target_name = text[8:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            elif target_user.id in self._join_times:
                jt = self._join_times[target_user.id]
                await self.highrise.chat(f"🕒 {target_name} is baar room mein aaya: {jt.strftime('%d-%b-%Y %I:%M %p')}")
            else:
                await self.highrise.chat(f"⚠️ '{target_name}' ka join-time record nahi hai (shayad bot start hone se pehle aaya tha).")
            return True

        return False

    # ============================ HELPER (LIGHT) COMMANDS ==============
    async def _handle_helper_command(self, user: User, text: str, lower: str) -> bool:
        """Trusted helpers ke liye limited command set (no moderation/economy)."""
        if lower in ("!hhelp", "!helperhelp"):
            await self.highrise.chat("🙋 Helper commands: !come | !announce <msg> | !test <emote_id> | !floor <naam>")
            return True

        if lower == "!come":
            await self._bot_come_to_owner(user)
            return True

        if lower.startswith("!announce "):
            msg = text[10:].strip()
            await self.highrise.chat(f"📢 {msg}")
            return True

        if lower.startswith("!test "):
            emote_id = text[6:].strip()
            await self._try_emote(user.id, emote_id, notify=user)
            return True

        if lower.startswith("!floor "):
            name = text[7:].strip()
            await self._goto_floor(user, name)
            return True

        return False

    async def _send_owner_help(self):
        await self.highrise.chat(f"👑 Public: numbers (1-{len(EMOTES)}) chalao, '0' ya '!stop' se roko, '!emotes <page>' se list dekho.")
        await self.highrise.chat("👑 Owner (1/4): !come | !follow | !unfollow | !goto <user> | !tp x y z | !tpto <user> | !bring <user>")
        await self.highrise.chat("👑 Owner (2/4) FLOORS: !setfloor <naam> | !floor <naam> | !floors | !delfloor <naam>")
        await self.highrise.chat("👑 Owner (3/4): !test <id> | !addemote <n> <id> | !removeemote <n> | !announce <msg> | !whisper <user> <msg> | !react <user> <reaction>")
        await self.highrise.chat("👑 Owner (4/4): !kick/!mute/!ban/!unmute/!unban <user> | !mod/!unmod/!designer <user> | !voiceadd/!voiceremove <user> | !tip <user> <amt> | !wallet | !who | !joined <user> | !sendto <user> <room_id> | !addhelper/!removehelper <user>")

    # ============================ CORE HELPERS ==========================
    def _is_owner(self, user: User) -> bool:
        if OWNER_USER_ID and user.id == OWNER_USER_ID:
            return True
        if OWNER_USERNAME and user.username.lower() == OWNER_USERNAME.lower():
            return True
        return False

    def _check_cooldown(self, user_id: str) -> bool:
        now = time.time()
        last = self._last_emote_time.get(user_id, 0)
        if now - last < EMOTE_COOLDOWN_SECONDS:
            return False
        self._last_emote_time[user_id] = now
        return True

    async def _try_emote(self, user_id: str, emote_id: str, notify: User = None) -> None:
        try:
            await self.highrise.send_emote(emote_id, user_id)
        except Exception as e:
            print(f"Emote '{emote_id}' fail:", e)
            if notify is not None:
                await self.highrise.chat(f"⚠️ '{emote_id}' invalid ya unavailable emote hai.")

    async def _stop_emote(self, user: User) -> None:
        try:
            await self.highrise.send_emote(STOP_EMOTE_ID, user.id)
            self._last_emote_used.pop(user.id, None)
        except Exception as e:
            print("Stop emote error:", e)
            await self.highrise.chat("⚠️ Emote rokne mein error aaya, dobara try karo.")

    async def _get_position(self, username: str):
        room_users = (await self.highrise.get_room_users()).content
        for room_user, pos in room_users:
            if room_user.username.lower() == username.lower():
                return room_user, pos
        return None, None

    async def _show_emote_page(self, lower: str):
        filled = [(n, e) for n, e in EMOTES.items() if not e.startswith("REPLACE_ME_")]
        filled.sort(key=lambda t: int(t[0]))
        if not filled:
            await self.highrise.chat("Abhi koi emote active nahi hai.")
            return
        parts = lower.split()
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        per_page = 10
        start = (page - 1) * per_page
        chunk = filled[start:start + per_page]
        if not chunk:
            await self.highrise.chat(f"Page {page} khaali hai. Total emotes: {len(filled)}")
            return
        listing = ", ".join(f"{n}" for n, _ in chunk)
        total_pages = (len(filled) + per_page - 1) // per_page
        await self.highrise.chat(f"🕺 Emotes page {page}/{total_pages}: {listing}")

    # ---- movement helpers ----
    async def _bot_come_to_owner(self, owner: User) -> None:
        """Bot khud owner ke paas teleport ho jaata hai."""
        _, owner_pos = await self._get_position(owner.username)
        if owner_pos is None:
            await self.highrise.chat("⚠️ Owner ki position nahi mil payi.")
            return
        try:
            if self.bot_user_id:
                await self.highrise.teleport(self.bot_user_id, owner_pos)
            else:
                await self.highrise.walk_to(owner_pos)
            await self.highrise.chat(f"🛰️ Aa gaya, {owner.username}!")
        except Exception as e:
            print("Come-here error:", e)
            await self.highrise.chat("⚠️ Aane mein error aaya, dobara try karo.")

    async def _teleport_owner_to_coords(self, owner: User, coords_str: str) -> None:
        try:
            parts = coords_str.split()
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            dest = Position(x, y, z, facing="FrontRight")
            await self.highrise.teleport(owner.id, dest)
            await self.highrise.chat(f"🚀 {owner.username}, teleport ho gaye {x},{y},{z} par!")
        except Exception as e:
            print("TP error:", e)
            await self.highrise.chat("⚠️ Format: !tp <x> <y> <z>")

    async def _teleport_owner_to_user(self, owner: User, target_name: str) -> None:
        _, target_pos = await self._get_position(target_name)
        if target_pos is None:
            await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            return
        try:
            await self.highrise.teleport(owner.id, target_pos)
            await self.highrise.chat(f"🚀 {owner.username}, {target_name} ke paas teleport ho gaye!")
        except Exception as e:
            print("TPTO error:", e)
            await self.highrise.chat("⚠️ Teleport fail ho gaya.")

    async def _bring_user_to_owner(self, owner: User, target_name: str) -> None:
        _, owner_pos = await self._get_position(owner.username)
        target_user, _ = await self._get_position(target_name)
        if owner_pos is None or target_user is None:
            await self.highrise.chat(f"⚠️ '{target_name}' ya owner room mein nahi mile.")
            return
        try:
            await self.highrise.teleport(target_user.id, owner_pos)
            await self.highrise.chat(f"🚀 {target_name} ko {owner.username} ke paas la diya!")
        except Exception as e:
            print("Bring error:", e)
            await self.highrise.chat("⚠️ Bring fail ho gaya.")

    async def _start_follow(self, owner_username: str) -> None:
        await self._stop_follow()
        self._follow_target_username = owner_username

        async def _loop():
            while self._follow_target_username == owner_username:
                try:
                    _, pos = await self._get_position(owner_username)
                    if pos is not None and self.bot_user_id:
                        await self.highrise.teleport(self.bot_user_id, pos)
                except Exception as e:
                    print("Follow loop error:", e)
                await asyncio.sleep(3)

        self._follow_task = asyncio.create_task(_loop())
        await self.highrise.chat(f"🐾 Ab main {owner_username} ko follow karunga. Rokne ke liye '!unfollow' bhejo.")

    async def _stop_follow(self) -> None:
        self._follow_target_username = None
        if self._follow_task is not None:
            self._follow_task.cancel()
            self._follow_task = None

    # ---- FLOOR TELEPORT HELPERS (NAYA) ----
    async def _set_floor(self, owner: User, name: str) -> None:
        if not name:
            await self.highrise.chat("⚠️ Format: !setfloor <naam> (e.g. !setfloor first)")
            return
        _, owner_pos = await self._get_position(owner.username)
        if owner_pos is None:
            await self.highrise.chat("⚠️ Tumhari position nahi mil payi.")
            return
        self._floors[name.lower()] = {
            "x": owner_pos.x, "y": owner_pos.y, "z": owner_pos.z,
            "facing": getattr(owner_pos, "facing", "FrontRight"),
        }
        self._save_floors()
        await self.highrise.chat(f"📍 Floor '{name}' save ho gaya isi position par!")

    async def _goto_floor(self, owner: User, name: str) -> None:
        if not name:
            await self.highrise.chat("⚠️ Format: !floor <naam>")
            return
        data = self._floors.get(name.lower())
        if data is None:
            await self.highrise.chat(f"⚠️ Floor '{name}' abhi tak set nahi hai. Pehle '!setfloor {name}' se save karo.")
            return
        try:
            dest = Position(data["x"], data["y"], data["z"], facing=data.get("facing", "FrontRight"))
            await self.highrise.teleport(owner.id, dest)
            await self.highrise.chat(f"🚀 {owner.username}, '{name}' floor par teleport ho gaye!")
        except Exception as e:
            print("Floor TP error:", e)
            await self.highrise.chat("⚠️ Floor teleport fail ho gaya.")

    async def _list_floors(self) -> None:
        if not self._floors:
            await self.highrise.chat("Abhi koi floor set nahi hai. '!setfloor <naam>' se banao.")
            return
        names = ", ".join(sorted(self._floors.keys()))
        await self.highrise.chat(f"🏢 Saved floors: {names}")

    async def _del_floor(self, name: str) -> None:
        if name.lower() in self._floors:
            del self._floors[name.lower()]
            self._save_floors()
            await self.highrise.chat(f"🗑️ Floor '{name}' delete ho gaya.")
        else:
            await self.highrise.chat(f"⚠️ Floor '{name}' milaa nahi.")

    # ---- moderation / privilege helpers ----
    async def _moderate(self, target_name: str, action: str, minutes: int = None) -> None:
        target_user, _ = await self._get_position(target_name)
        if target_user is None:
            await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            return
        try:
            if minutes is not None:
                await self.highrise.moderate_room(target_user.id, action, minutes)
            else:
                await self.highrise.moderate_room(target_user.id, action)
            await self.highrise.chat(f"🛡️ {target_name}: {action} kar diya.")
        except Exception as e:
            print(f"Moderate '{action}' error:", e)
            await self.highrise.chat(
                f"⚠️ '{action}' fail ho gaya — is action ke liye bot ke paas "
                f"Moderator/Owner rights room mein hone chahiye, aur SDK version check kar lo."
            )

    async def _set_privilege(self, target_name: str, privilege: str) -> None:
        target_user, _ = await self._get_position(target_name)
        if target_user is None:
            await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            return
        try:
            await self.highrise.set_room_privilege(target_user.id, privilege)
            await self.highrise.chat(f"🎖️ {target_name} ab '{privilege}' ban gaya/gayi.")
        except Exception as e:
            print(f"Set privilege '{privilege}' error:", e)
            await self.highrise.chat(
                "⚠️ Privilege set nahi ho paya — bot ke paas Owner rights chahiye is action ke liye."
            )


# ============================ MULTI-ROOM RUNNER ========================
async def main():
    """Dono rooms ko ek hi process mein, ek saath start karta hai."""
    definitions = [
        BotDefinition(Bot(room_label=room["label"]), room["room_id"], BOT_TOKEN)
        for room in ROOMS
    ]
    await __main__.main(definitions)


if __name__ == "__main__":
    asyncio.run(main())
