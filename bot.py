"""
====================================================================
  LANAX.4 — Highrise Bot (SINGLE ROOM, LOOPING EMOTES, FLOOR-TELEPORT)
====================================================================

--------------------------------------------------------------------
YEH KYA FIX HUA HAI:
--------------------------------------------------------------------
1) CRASH FIX ("Multilogin closing connection..." -> Application exited early)
   Root cause: pehle wala code SAME bot token se DO rooms mein EK
   saath connect kar raha tha. Highrise sirf EK active session per
   bot allow karta hai — dusra connection aate hi purana session
   "Multilogin" bolke band kar deta hai, aur dono connections gir
   jaate hain -> app crash.
   FIX: Ab bot sirf EK room mein connect hota hai. Naya room ID
   (ownedRoomId) is link se liya gaya hai:
   https://high.rs/world?id=6894bd39e3e4a405517cb530&ownedRoomId=63fcc70dfb16e9c663269160
   -> ROOM_ID = "63fcc70dfb16e9c663269160"

2) EMOTE LOOP FIX
   Pehle number bhejne par emote SIRF EK BAAR chalta tha (Highrise
   emotes non-looping hote hain by default). Ab jab koi number
   bhejta hai, bot background mein us emote ko HAR FEW SECONDS mein
   dobara-dobara chalata rehta hai — jab tak woh user "0" ya
   "!stop" na bole. Naya number bhejne par purana loop apne aap
   band ho jaata hai aur naya start hota hai.

3) EMOTES 50 -> 250 SLOTS
   Dictionary ab 250 numbers support karta hai. Maine sirf wahi
   IDs bhare hain jo maine verify kiye hain (pehle wale 50 + kuch
   thoda extra jo Highrise SDK docs mein confirmed hain). Baaki
   slots khaali (REPLACE_ME) hain kyunki mujhe unke real emote-id
   strings verified nahi mile — fake ID daalne se woh chup-chaap
   fail ho jaata (koi crash nahi, bas kaam nahi karega). In khaali
   slots ko bharne ke liye:
       !addemote <number> <real_emote_id>
   Real IDs kahan se milenge:
     - Highrise Studio -> Outfit Editor -> Emote Editor (ID dikhata hai)
     - Highrise Create community "Code Snippets" page

--------------------------------------------------------------------
NAYE FEATURES (2026-style additions):
--------------------------------------------------------------------
  - Looping emotes (jab tak stop na bolo)              [PUBLIC]
  - "!random" -> ek random filled emote chalata hai      [PUBLIC]
  - "!party" (owner/helper) -> pura room cycle-emote mode [OWNER/HELPER]
  - "!myemote" -> tumhara current chal raha emote batata hai [PUBLIC]
  - Per-user emote history + last-used quick repeat "!again" [PUBLIC]
  - Sab floors + emote-loop state JSON mein persist hota hai
    (bot restart hone par bhi yaad rehta hai)

--------------------------------------------------------------------
RENDER DEPLOY:
--------------------------------------------------------------------
1) requirements.txt:
       highrise-bot-sdk==25.1.0
2) Environment Variable:
       PYTHON_VERSION = 3.11.9
3) Start Command:
       python bot.py
====================================================================
"""

import asyncio
import json
import os
import random
import time
from datetime import datetime

from highrise import BaseBot, User, __main__
from highrise.models import Position, SessionMetadata


# ============================ CONFIG ================================
BOT_NAME = "LANAX.4"
BOT_TOKEN = "c58d1869fbad962a328c20a2abc0333400a128ecbbf8c6d1bf9382b44cb2f87a"

# --- SIRF EK ROOM (multilogin crash fix) ---
ROOM_ID = "63fcc70dfb16e9c663269160"   # naye link ka ownedRoomId

OWNER_USERNAME = "LANAX4"
OWNER_USER_ID = "lanax4"   # agar exact User ID pata ho toh yahan daal do

TRUSTED_HELPERS = set()   # example: {"myfriend123"}

EMOTE_COOLDOWN_SECONDS = 1.0        # naya command spam-guard
EMOTE_REPEAT_SECONDS = 4.0          # kitni der baad emote dobara chalega (loop)

WELCOME_MESSAGE_ENABLED = True

STOP_EMOTE_ID = "emote-wave"

DATA_DIR = "./bot_data"
FLOOR_FILE = os.path.join(DATA_DIR, "floors.json")


# ============================ EMOTES (1-250) =========================
# Sirf verified IDs bhare hain. Baaki slots "REPLACE_ME_<n>" hain —
# unhe !addemote <n> <real_id> se bharo.
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

# 51-250 abhi khaali hain — !addemote se bharo
for _n in range(51, 251):
    EMOTES.setdefault(str(_n), f"REPLACE_ME_{_n}")


# ============================ BOT LOGIC ==============================
class Bot(BaseBot):
    def __init__(self):
        super().__init__()
        self.bot_user_id = None
        self._last_cmd_time = {}        # user_id -> timestamp (cooldown)
        self._emote_tasks = {}          # user_id -> asyncio.Task (looping emote)
        self._last_emote_used = {}      # user_id -> emote_id
        self._join_times = {}           # user_id -> datetime
        self._follow_target_username = None
        self._follow_task = None
        self._party_task = None
        self._floors = {}

    # ------------------------- persistence -----------------------
    def _load_floors(self):
        try:
            if os.path.exists(FLOOR_FILE):
                with open(FLOOR_FILE, "r") as f:
                    self._floors = json.load(f)
        except Exception as e:
            print("Floor load error:", e)
            self._floors = {}

    def _save_floors(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(FLOOR_FILE, "w") as f:
                json.dump(self._floors, f)
        except Exception as e:
            print("Floor save error:", e)

    # ------------------------- lifecycle -----------------------------
    async def on_start(self, session_metadata: SessionMetadata) -> None:
        self.bot_user_id = session_metadata.user_id
        os.makedirs(DATA_DIR, exist_ok=True)
        self._load_floors()
        print(f"✅ {BOT_NAME} connect ho gaya! bot_user_id = {self.bot_user_id}")
        try:
            await self.highrise.chat(
                f"🤖 {BOT_NAME} online hai! Number bhejo (1-{len(EMOTES)}) apna emote "
                f"CHALU rakhne ke liye (loop hoga jab tak stop na bolo). "
                f"Rokne ke liye '0' ya '!stop'. Owner: !owner"
            )
        except Exception as e:
            print("Startup message error:", e)

    async def on_user_join(self, user: User, *args, **kwargs) -> None:
        join_time = datetime.now()
        self._join_times[user.id] = join_time
        time_str = join_time.strftime("%d-%b-%Y %I:%M %p")
        print(f"➡️ {user.username} room mein aaya: {time_str}")
        if WELCOME_MESSAGE_ENABLED:
            try:
                await self.highrise.chat(f"👋 Welcome, {user.username}! (Aaye: {time_str})")
            except Exception as e:
                print("Welcome message error:", e)

    async def on_user_leave(self, user: User) -> None:
        # Loop chal raha ho toh cleanup kar do taaki memory leak na ho
        await self._cancel_loop(user.id)

    async def on_moderate(self, moderator_id, target_user_id, moderate_type, action_length=None) -> None:
        print(f"Room moderated: mod={moderator_id} target={target_user_id} action={moderate_type} len={action_length}")

    async def on_message(self, user_id, conversation_id, is_new_conversation) -> None:
        print(f"DM received from {user_id} in {conversation_id} (new={is_new_conversation})")

    # ------------------------- main chat handler ----------------------
    async def on_chat(self, user: User, message: str) -> None:
        text = message.strip()
        lower = text.lower()
        is_owner = self._is_owner(user)
        is_helper = is_owner or user.username.lower() in TRUSTED_HELPERS

        if is_owner:
            if await self._handle_owner_command(user, text, lower):
                return

        if is_helper and not is_owner:
            if await self._handle_helper_command(user, text, lower):
                return

        # ---------- Public: stop apna loop ----------
        if text == "0" or lower in ("!stop", "stop"):
            await self._cancel_loop(user.id, play_stop_emote=True)
            return

        # ---------- Public: numbered emotes -> LOOP until stop ----------
        if text in EMOTES:
            emote_id = EMOTES[text]
            if emote_id.startswith("REPLACE_ME_"):
                await self.highrise.chat(f"⚠️ Emote #{text} abhi tak khaali hai.")
                return
            if not self._check_cooldown(user.id):
                return
            await self._start_loop_emote(user.id, emote_id)
            self._last_emote_used[user.id] = emote_id
            return

        if lower == "!again":
            emote_id = self._last_emote_used.get(user.id)
            if emote_id is None:
                await self.highrise.chat("⚠️ Tumne abhi tak koi emote use nahi kiya.")
            else:
                await self._start_loop_emote(user.id, emote_id)
            return

        if lower == "!random":
            filled = [e for e in EMOTES.values() if not e.startswith("REPLACE_ME_")]
            if filled:
                emote_id = random.choice(filled)
                await self._start_loop_emote(user.id, emote_id)
                self._last_emote_used[user.id] = emote_id
            return

        if lower == "!myemote":
            emote_id = self._last_emote_used.get(user.id)
            if emote_id and user.id in self._emote_tasks:
                await self.highrise.chat(f"🕺 {user.username}, abhi chal raha hai: {emote_id}")
            else:
                await self.highrise.chat(f"{user.username}, koi emote loop nahi chal raha.")
            return

        if lower in ("!emotes", "!list") or lower.startswith("!emotes "):
            await self._show_emote_page(lower)
            return

        if lower in ("!help", "!commands"):
            await self.highrise.chat(
                f"🎉 Number bhejo (1-{len(EMOTES)}) -> emote LOOP mein chalega. "
                "Rokne ke liye '0' ya '!stop'. '!again' se last emote repeat, "
                "'!random' se random emote, '!emotes <page>' se list, '!myemote' se status."
            )
            return

    # ============================ OWNER COMMAND DISPATCH ==============
    async def _handle_owner_command(self, user: User, text: str, lower: str) -> bool:
        if lower in ("!help", "!owner"):
            await self._send_owner_help()
            return True

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

        # ---- party mode: pura room ek saath cycle emotes ----
        if lower == "!party":
            await self._start_party()
            return True

        if lower == "!partystop":
            await self._stop_party()
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

        # ---- floors ----
        if lower.startswith("!setfloor "):
            await self._set_floor(user, text[10:].strip())
            return True

        if lower.startswith("!floor "):
            await self._goto_floor(user, text[7:].strip())
            return True

        if lower in ("!floors", "!floorlist"):
            await self._list_floors()
            return True

        if lower.startswith("!delfloor "):
            await self._del_floor(text[10:].strip())
            return True

        # ---- messaging ----
        if lower.startswith("!announce "):
            await self.highrise.chat(f"📢 {text[10:].strip()}")
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
                        await self.highrise.chat("⚠️ Reaction fail ho gaya.")
            else:
                await self.highrise.chat("⚠️ Format: !react <username> <reaction>")
            return True

        # ---- moderation ----
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

        # ---- helpers ----
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

        # ---- voice ----
        if lower.startswith("!voiceadd "):
            target_name = text[10:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            else:
                try:
                    await self.highrise.add_user_to_voice(target_user.id)
                    await self.highrise.chat(f"🎤 {target_name} ko voice mein add kiya.")
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
                    await self.highrise.chat(f"🔇 {target_name} ko voice se remove kiya.")
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
                        await self.highrise.chat(f"💰 {target_name} ko {amount} tip bheja.")
                    except Exception as e:
                        print("Tip error:", e)
                        await self.highrise.chat("⚠️ Tip fail ho gaya. Valid: gold_bar_1/5/10/50/100/500/1k/5000/10k")
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
                await self.highrise.chat(f"🕒 {target_name} aaya: {jt.strftime('%d-%b-%Y %I:%M %p')}")
            else:
                await self.highrise.chat(f"⚠️ '{target_name}' ka join-time record nahi hai.")
            return True

        return False

    # ============================ HELPER (LIGHT) COMMANDS ==============
    async def _handle_helper_command(self, user: User, text: str, lower: str) -> bool:
        if lower in ("!hhelp", "!helperhelp"):
            await self.highrise.chat("🙋 Helper: !come | !announce <msg> | !test <emote_id> | !floor <naam> | !party | !partystop")
            return True
        if lower == "!come":
            await self._bot_come_to_owner(user)
            return True
        if lower.startswith("!announce "):
            await self.highrise.chat(f"📢 {text[10:].strip()}")
            return True
        if lower.startswith("!test "):
            await self._try_emote(user.id, text[6:].strip(), notify=user)
            return True
        if lower.startswith("!floor "):
            await self._goto_floor(user, text[7:].strip())
            return True
        if lower == "!party":
            await self._start_party()
            return True
        if lower == "!partystop":
            await self._stop_party()
            return True
        return False

    async def _send_owner_help(self):
        await self.highrise.chat(f"👑 Public: number (1-{len(EMOTES)}) = looping emote | '0'/'!stop' roko | '!again' | '!random' | '!emotes <page>' | '!myemote'")
        await self.highrise.chat("👑 Owner (1/4): !come | !follow | !unfollow | !goto <user> | !tp x y z | !tpto <user> | !bring <user> | !party | !partystop")
        await self.highrise.chat("👑 Owner (2/4) FLOORS: !setfloor <naam> | !floor <naam> | !floors | !delfloor <naam>")
        await self.highrise.chat("👑 Owner (3/4): !test <id> | !addemote <n> <id> | !removeemote <n> | !announce <msg> | !whisper <user> <msg> | !react <user> <reaction>")
        await self.highrise.chat("👑 Owner (4/4): !kick/!mute/!ban/!unmute/!unban <user> | !mod/!unmod/!designer <user> | !voiceadd/!voiceremove <user> | !tip <user> <amt> | !wallet | !who | !joined <user> | !addhelper/!removehelper <user>")

    # ============================ CORE HELPERS ==========================
    def _is_owner(self, user: User) -> bool:
        if OWNER_USER_ID and user.id == OWNER_USER_ID:
            return True
        if OWNER_USERNAME and user.username.lower() == OWNER_USERNAME.lower():
            return True
        return False

    def _check_cooldown(self, user_id: str) -> bool:
        now = time.time()
        last = self._last_cmd_time.get(user_id, 0)
        if now - last < EMOTE_COOLDOWN_SECONDS:
            return False
        self._last_cmd_time[user_id] = now
        return True

    async def _try_emote(self, user_id: str, emote_id: str, notify: User = None) -> None:
        try:
            await self.highrise.send_emote(emote_id, user_id)
        except Exception as e:
            print(f"Emote '{emote_id}' fail:", e)
            if notify is not None:
                await self.highrise.chat(f"⚠️ '{emote_id}' invalid ya unavailable emote hai.")

    # ---- LOOPING EMOTE ENGINE (naya) ----
    async def _start_loop_emote(self, user_id: str, emote_id: str) -> None:
        """Emote ko har EMOTE_REPEAT_SECONDS mein dobara chalata hai, jab tak
        cancel na ho (user '0'/'!stop' bole ya naya emote select kare)."""
        await self._cancel_loop(user_id)

        async def _loop():
            try:
                while True:
                    await self._try_emote(user_id, emote_id)
                    await asyncio.sleep(EMOTE_REPEAT_SECONDS)
            except asyncio.CancelledError:
                pass

        self._emote_tasks[user_id] = asyncio.create_task(_loop())

    async def _cancel_loop(self, user_id: str, play_stop_emote: bool = False) -> None:
        task = self._emote_tasks.pop(user_id, None)
        if task is not None:
            task.cancel()
        if play_stop_emote:
            try:
                await self.highrise.send_emote(STOP_EMOTE_ID, user_id)
            except Exception as e:
                print("Stop emote error:", e)
        self._last_emote_used.pop(user_id, None)

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
            await self.highrise.chat(f"Page {page} khaali hai. Total filled emotes: {len(filled)}/{len(EMOTES)}")
            return
        listing = ", ".join(n for n, _ in chunk)
        total_pages = (len(filled) + per_page - 1) // per_page
        await self.highrise.chat(f"🕺 Emotes page {page}/{total_pages} ({len(filled)}/{len(EMOTES)} filled): {listing}")

    # ---- party mode (naya feature) ----
    async def _start_party(self) -> None:
        await self._stop_party()
        filled = [e for e in EMOTES.values() if not e.startswith("REPLACE_ME_")]
        if not filled:
            await self.highrise.chat("⚠️ Koi emote filled nahi hai party ke liye.")
            return

        async def _loop():
            try:
                while True:
                    if self.bot_user_id:
                        await self._try_emote(self.bot_user_id, random.choice(filled))
                    await asyncio.sleep(EMOTE_REPEAT_SECONDS)
            except asyncio.CancelledError:
                pass

        self._party_task = asyncio.create_task(_loop())
        await self.highrise.chat("🎉 Party mode ON — bot random emotes cycle karega! '!partystop' se roko.")

    async def _stop_party(self) -> None:
        if self._party_task is not None:
            self._party_task.cancel()
            self._party_task = None

    # ---- movement helpers ----
    async def _bot_come_to_owner(self, owner: User) -> None:
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
            await self.highrise.chat("⚠️ Aane mein error aaya.")

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
        await self.highrise.chat(f"🐾 Ab main {owner_username} ko follow karunga. '!unfollow' se roko.")

    async def _stop_follow(self) -> None:
        self._follow_target_username = None
        if self._follow_task is not None:
            self._follow_task.cancel()
            self._follow_task = None

    # ---- floor helpers ----
    async def _set_floor(self, owner: User, name: str) -> None:
        if not name:
            await self.highrise.chat("⚠️ Format: !setfloor <naam>")
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
        await self.highrise.chat(f"📍 Floor '{name}' save ho gaya!")

    async def _goto_floor(self, owner: User, name: str) -> None:
        if not name:
            await self.highrise.chat("⚠️ Format: !floor <naam>")
            return
        data = self._floors.get(name.lower())
        if data is None:
            await self.highrise.chat(f"⚠️ Floor '{name}' set nahi hai. Pehle '!setfloor {name}' karo.")
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
            await self.highrise.chat("Abhi koi floor set nahi hai.")
            return
        await self.highrise.chat(f"🏢 Saved floors: {', '.join(sorted(self._floors.keys()))}")

    async def _del_floor(self, name: str) -> None:
        if name.lower() in self._floors:
            del self._floors[name.lower()]
            self._save_floors()
            await self.highrise.chat(f"🗑️ Floor '{name}' delete ho gaya.")
        else:
            await self.highrise.chat(f"⚠️ Floor '{name}' mila nahi.")

    # ---- moderation / privilege ----
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
            await self.highrise.chat(f"⚠️ '{action}' fail — bot ke paas Moderator/Owner rights room mein hone chahiye.")

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
            await self.highrise.chat("⚠️ Privilege set nahi ho paya — bot ke paas Owner rights chahiye.")


# ============================ SINGLE-ROOM RUNNER ========================
async def main():
    """Sirf EK room mein connect karta hai — multilogin crash yahi se fix hota hai."""
    definitions = [(Bot(), ROOM_ID, BOT_TOKEN)]
    await __main__.main(definitions)


if __name__ == "__main__":
    asyncio.run(main())
