"""
====================================================================
  LANAX.4 — Highrise Bot (SINGLE ROOM, LOOPING EMOTES, FLOOR-TELEPORT)
  v8 — STOP-FIX + DM AUTHORIZATION + DM EMOTE LIST
====================================================================

--------------------------------------------------------------------
V8 MEIN KYA FIX HUA (Hinglish notes):
--------------------------------------------------------------------
1) "EMOTE STOP NAHI HOTA" — ASLI WAJAH (race condition):
   Pehle jab user "0"/!stop bhejta tha, purana loop-task sirf
   `.cancel()` hota tha lekin code aage badh jaata tha bina yeh check
   kiye ki purana task WAAKAI ruk gaya ya nahi. Agar isi beech user
   jaldi se naya number bhej deta, to `_start_loop_emote` ek NAYA
   loop start kar deta jabki purana abhi bhi ek aakhri emote bhej
   sakta tha (cancellation sirf agle "await" pe fire hoti hai).
   Result: do loops overlap ho jaate — isiliye lagta tha "emote ruk
   hi nahi raha".
   FIX: `_cancel_loop()` ab `task.cancel()` ke baad `await task` bhi
   karta hai — matlab naya loop tabhi start hoga jab purana 100%
   band ho chuka ho. Ab koi overlap nahi hoga.

2) DM AUTHORIZATION (naya feature):
   Naya player agar emote use karna chahta hai, to use pehle BOT ko
   DM (private message) mein "hi" / "hello" / "hey" bhejna hoga.
   Bot uska user_id save kar lega (persisted to disk), aur uske baad
   wo room mein number bhejkar emote loop use kar payega.
   Owner aur trusted helpers ko yeh restriction नहीं लगती।
   Owner manually bhi kisi ko access de/hata sakta hai:
       !auth <username>      → access diya
       !deauth <username>    → access hataya
       !authlist             → total authorized count dikhata hai

3) DM EMOTE LIST (naya feature):
   Jisko pata nahi kaunsi emotes available hain, wo BOT ko DM mein
   "emotes" ya "list" ya "emote list" likh kar bhej sakta hai — bot
   saari filled emote numbers DM mein bhej dega (chunks mein, taaki
   message limit na tooté).

4) "MAIN OFFLINE JAata HUN TO BOT BHI OFFLINE HO JAATA HAI":
   Yeh coincidence hai, code bug nahi. Render ka FREE plan Web
   Service ko ~15 min traffic na aane par sula deta hai — poora
   process (health server + bot subprocess) ruk jaata hai. Agar
   aapka external keep-alive ping (UptimeRobot / cron-job.org)
   theek se set nahi hai ya woh khud kabhi "down" reh jaata hai, to
   bot bhi so jaata hai — aur jab aap room join karte ho, waqt sirf
   coincide karta hai (aap aksar usi time online aate ho jab aap
   khud check karte ho). ROOM_ID hamesha same hai, bot kabhi
   "follow" nahi karta — is file mein aisi koi logic hi nahi hai.
   FIX/ACTION REQUIRED (already in place, bas confirm/setup karo):
     a) UptimeRobot (free) ya cron-job.org par ek HTTP(s) monitor
        banao jo har 5 minute mein aapke Render URL ke /health par
        hit kare (e.g. https://your-app.onrender.com/health).
     b) Agar guaranteed 24/7 chahiye bina kisi external ping ke, to
        Render ka paid "Starter" plan lo (usmein sleep hi nahi hota).
   Is file ka apna internal self-ping (har 4 min) madad karta hai
   lekin free plan par akela kaafi nahi hai.

--------------------------------------------------------------------
RENDER START COMMAND — DO ONE OF THESE:
--------------------------------------------------------------------
OPTION A (RECOMMENDED — health-check + keep-alive + auto-restart):
   Service Type : Web Service
   Start Command: python bot.py
   Phir UptimeRobot monitor lagao /health par, har 5 min.

OPTION B (pure official CLI, no health-check/keep-alive):
   Service Type : Background Worker (paid Starter plan chahiye asli
                  24/7 ke liye, free workers HTTP traffic se wake
                  nahi hote)
   Start Command: highrise bot:Bot $ROOM_ID $BOT_TOKEN

Environment Variables (dono options ke liye):
       PYTHON_VERSION = 3.11.9
       BOT_TOKEN       = <your token>
       ROOM_ID         = <your room id>
       PORT            = 10000   (Option A; Render usually sets
                                   this automatically)

requirements.txt:
       highrise-bot-sdk==25.1.0
       aiohttp>=3.9
====================================================================
"""

import asyncio
import json
import logging
import os
import random
import sys
import time
import traceback
from datetime import datetime

from highrise import BaseBot, User
from highrise.models import Position, SessionMetadata

try:
    from aiohttp import web, ClientSession, ClientTimeout
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


# ============================ LOGGING ================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("LANAX4")


# ============================ CONFIG ================================
BOT_NAME = "LANAX.4"

# Env vars take priority — falls back to the hardcoded value if unset.
BOT_TOKEN = os.environ.get(
    "BOT_TOKEN",
    "c58d1869fbad962a328c20a2abc0333400a128ecbbf8c6d1bf9382b44cb2f87a",
)

# --- ONLY ONE ROOM (single-room fix, do not change) ---
ROOM_ID = os.environ.get("ROOM_ID", "63fcc70dfb16e9c663269160")

OWNER_USERNAME = "LANAX4"
OWNER_USER_ID = "lanax4"   # put the exact User ID here if you have it

TRUSTED_HELPERS = set()   # example: {"myfriend123"}

EMOTE_COOLDOWN_SECONDS = 1.0        # per-command spam guard
EMOTE_REPEAT_SECONDS = 4.0          # loop interval for a playing emote

WELCOME_MESSAGE_ENABLED = True
WELCOME_MESSAGE_DELAY_SECONDS = 1.5   # anti-spam-drop delay before greeting

STOP_EMOTE_ID = "emote-wave"

DATA_DIR = "./bot_data"
FLOOR_FILE = os.path.join(DATA_DIR, "floors.json")
AUTH_FILE = os.path.join(DATA_DIR, "authorized.json")

# Seconds to wait before retrying after the bot process exits/crashes
RECONNECT_DELAY_SECONDS = 10

# Self-ping interval (internal keep-alive helper — see notes at top)
SELF_PING_INTERVAL_SECONDS = 240

# Quick public floor teleports — fill these in with real coordinates for
# your room (use !setfloor 0 / !setfloor 1 / !setfloor 2 as the owner
# while standing at each spot, which saves them here automatically).
QUICK_FLOORS = ["0", "1", "2"]

# Keywords that trigger DM authorization ("access mil gaya")
AUTH_KEYWORDS = ("hi", "hello", "hey", "start", "unlock", "emote on")
# Keywords that trigger the DM emote list
EMOTE_LIST_KEYWORDS = ("emote list", "emotelist", "list emote", "emotes", "list")

DM_WELCOME_MESSAGE = (
    "👋 Hi! Main {bot} hoon. Emotes use karne ke liye bas 'hi' bhejo — "
    "turant access mil jaayega. Kaunsi emotes hain yeh jaanne ke liye "
    "'emotes' likh kar bhejo. Room mein jaakar number bhejo (1 se {max}) "
    "emote LOOP karne ke liye — '0' ya '!stop' bhejo rokne ke liye."
)
DM_FALLBACK_MESSAGE = (
    "Samajh nahi aaya 🙂 'hi' bhejo access lene ke liye, ya 'emotes' bhejo "
    "puri list paane ke liye."
)
DM_AUTH_GRANTED_MESSAGE = (
    "✅ Ho gaya! Ab room mein jaakar emote number (1-{max}) bhejo, emote "
    "loop ho jaayega. '0' ya '!stop' se rok sakte ho. 'emotes' likh kar "
    "DM karo poori list ke liye."
)


# ============================ EMOTES (1-311) =========================
EMOTES = {
    "1": "emote-model",
    "2": "emote-dontstartnow",
    "3": "emote-russian",
    "4": "emote-teleport",
    "5": "emote-curtsy",
    "6": "emote-letsgoshopping",
    "7": "emote-greedy",
    "8": "emote-singalong",
    "9": "emote-pennywise",
    "10": "emote-bow",
    "11": "emote-snowballfight",
    "12": "emote-confused",
    "13": "emote-charging",
    "14": "emote-floating",
    "15": "emote-froghop",
    "16": "emote-enthused",
    "17": "emote-gravedance",
    "18": "emote-swordfight",
    "19": "emote-dotheworm",
    "20": "emote-viralgroove",
    "21": "emote-shuffledance",
    "22": "emote-raisetheroof",
    "23": "emote-cutey",
    "24": "emote-telekinesis",
    "25": "emote-energyball",
    "26": "emote-maniac",
    "27": "emote-snowangel",
    "28": "emote-sweating",
    "29": "emote-kpop",
    "30": "emote-cutey",
    "31": "emote-casual",
    "32": "emote-pose1",
    "33": "emote-pose3",
    "34": "emote-pose5",
    "35": "emote-pose7",
    "36": "emote-pose8",
    "37": "emote-gagging",
    "38": "emote-savage",
    "39": "emote-sayso",
    "40": "emote-fashion",
    "41": "emote-gravity",
    "42": "emote-uwu",
    "43": "emote-wrong",
    "44": "emote-sleigh",
    "45": "emote-hyped",
    "46": "emote-zombie",
    "47": "emote-punk",
    "48": "emote-shy",
    "49": "emote-icecream",
    "50": "emote-touch",
    "51": "emote-guitar",
    "52": "emote-kawaii",
    "53": "emote-scritchy",
    "54": "emote-celebration",
    "55": "emote-surprise",
    "56": "emote-bashful",
    "57": "emote-creepycute",
    "58": "emote-pose10",
    "59": "emote-repose",
    "60": "emote-boxer",
    "61": "emote-creepypuppet",
    "62": "emote-penguin",
    "63": "emote-yes",
    "64": "emote-tired",
    "65": "emote-sad",
    "66": "emote-kiss",
    "67": "emote-jinglebell",
    "68": "emote-nervous",
    "69": "emote-toilet",
    "70": "emote-astronaut",
    "71": "emote-animedance",
    "72": "emote-iceskating",
    "73": "emote-headblowup",
    "74": "emote-ditzypose",
    "75": "emote-gift",
    "76": "emote-pushit",
    "77": "emote-launch",
    "78": "emote-salute",
    "79": "emote-cutesalute",
    "80": "emote-fairytwirl",
    "81": "emote-fairyfloat",
    "82": "emote-smooch",
    "83": "emote-fishingpull",
    "84": "emote-fishingcast",
    "85": "emote-fishing",
    "86": "emote-mining",
    "87": "emote-minesuccess",
    "88": "emote-minefail",
    "89": "emote-fishingpull",
    "90": "emote-tough",
    "91": "emote-fail",
    "92": "emote-disappointed",
    "93": "emote-cold",
    "94": "emote-wop",
    "95": "emote-party",
    "96": "emote-stargazing",
    "97": "emote-partnerhug",
    "98": "emote-ghostfloat",
    "99": "emote-zombie",
    "100": "emote-relaxed",
    "101": "emote-attentive",
    "102": "emote-sleepy",
    "103": "emote-poutyface",
    "104": "emote-posh",
    "105": "emote-sleepy",
    "106": "emote-taploop",
    "107": "emote-sit",
    "108": "emote-shy",
    "109": "emote-bummed",
    "110": "emote-chillin",
    "111": "emote-annoyed",
    "112": "emote-aerobics",
    "113": "emote-ponder",
    "114": "emote-heropose",
    "115": "emote-relaxing",
    "116": "emote-cozynap",
    "117": "emote-feelthebeat",
    "118": "emote-irritated",
    "119": "emote-ibelieveicanfly",
    "120": "emote-thewave",
    "121": "emote-think",
    "122": "emote-theatrical",
    "123": "emote-tapdance",
    "124": "emote-superrun",
    "125": "emote-superpunch",
    "126": "emote-sumofight",
    "127": "emote-thumbsuck",
    "128": "emote-splitsdrop",
    "129": "emote-secrethandshake",
    "130": "emote-ropepull",
    "131": "emote-roll",
    "132": "emote-rofl",
    "133": "emote-robot",
    "134": "emote-rainbow",
    "135": "emote-proposing",
    "136": "emote-peekaboo",
    "137": "emote-peace",
    "138": "emote-panic",
    "139": "emote-no",
    "140": "emote-ninjarun",
    "141": "emote-nightfever",
    "142": "emote-monsterfail",
    "143": "emote-levelup",
    "144": "emote-amused",
    "145": "emote-laugh",
    "146": "emote-superkick",
    "147": "emote-jump",
    "148": "emote-judochop",
    "149": "emote-imaginaryjetpack",
    "150": "emote-hugyourself",
    "151": "emote-hello",
    "152": "emote-harlemshake",
    "153": "emote-happy",
    "154": "emote-handstand",
    "155": "emote-moonwalk",
    "156": "emote-gangnamstyle",
    "157": "emote-faint",
    "158": "emote-clumsy",
    "159": "emote-fall",
    "160": "emote-facepalm",
    "161": "emote-exasperated",
    "162": "emote-elbowbump",
    "163": "emote-disco",
    "164": "emote-blastoff",
    "165": "emote-faintdrop",
    "166": "emote-collapse",
    "167": "emote-revival",
    "168": "emote-dab",
    "169": "emote-cold",
    "170": "emote-bunnyhop",
    "171": "emote-boo",
    "172": "emote-homerun",
    "173": "emote-fallingapart",
    "174": "emote-thumbsup",
    "175": "emote-point",
    "176": "emote-sneeze",
    "177": "emote-smirk",
    "178": "emote-sick",
    "179": "emote-gasp",
    "180": "emote-punch",
    "181": "emote-pray",
    "182": "emote-stinky",
    "183": "emote-naughty",
    "184": "emote-mindblown",
    "185": "emote-lying",
    "186": "emote-levitate",
    "187": "emote-fireballlunge",
    "188": "emote-giveup",
    "189": "emote-stunned",
    "190": "emote-sob",
    "191": "emote-clap",
    "192": "emote-arrogance",
    "193": "emote-angry",
    "194": "emote-voguehands",
    "195": "emote-smoothwalk",
    "196": "emote-ringonit",
    "197": "emote-orangejuice",
    "198": "emote-rockout",
    "199": "emote-macarena",
    "200": "emote-handsintheair",
    "201": "emote-duckwalk",
    "202": "emote-pushups",
    "203": "emote-attention",
    "204": "emote-zombie",
    "205": "emote-ghost",
    "206": "emote-hearteyes",
    "207": "emote-heartfingers",
    "208": "emote-heartshape",
    "209": "emote-eyeroll",
    "210": "emote-embarrassed",
    "211": "emote-sexy",
    "212": "emote-puppet",
    "213": "emote-fighter",
    "214": "emote-frustrated",
    "215": "emote-laidback",
    "216": "emote-slap",
    "217": "emote-tiktok7",
    "218": "emote-shrink",
    "219": "emote-howl",
    "220": "emote-bitnervous",
    "221": "emote-karmadance",
    "222": "emote-trampoline",
    "223": "emote-nocturnalhowl",
    "224": "emote-cheer",
    "225": "emote-hipshake",
    "226": "emote-confused2",
    "227": "emote-fruity",
    "228": "emote-magnetic",
    "229": "emote-coolguy",
    "230": "emote-riflethrow",
    "231": "emote-swingsneakidle",
    "232": "emote-swingnet3",
    "233": "emote-swingcelebrate",
    "234": "emote-swingnet2",
    "235": "emote-swingnet",
    "236": "emote-idlesleep",
    "237": "emote-sugarbitepose1",
    "238": "emote-sugarbitepose2",
    "239": "emote-sugarbitepose3",
    "240": "emote-nova",
    "241": "emote-yoga",
    "242": "emote-sitpose",
    "243": "emote-yogawarrior",
    "244": "emote-yogawarrior3",
    "245": "emote-stand2",
    "246": "emote-runningman",
    "247": "emote-yogasurprise",
    "248": "emote-yog",
    "249": "emote-sweettease",
    "250": "emote-rebeldarling",
    "251": "emote-chaoscutie",
    "252": "emote-sweetlure",
    "253": "emote-stormmood",
    "254": "emote-stormgroove",
    "255": "emote-comehere",
    "256": "emote-silentlyjudging",
    "257": "emote-justvibing",
    "258": "emote-crowdjammer",
    "259": "emote-sweetjammer",
    "260": "emote-springsun",
    "261": "emote-midnightpoise",
    "262": "emote-midnightstrut",
    "263": "emote-midnightallure",
    "264": "emote-daydreaming",
    "265": "emote-offdutyangelsbackoff",
    "266": "emote-bloomcharm",
    "267": "emote-bloomflutter",
    "268": "emote-bloomradiance",
    "269": "emote-divamoment",
    "270": "emote-sugarsun",
    "271": "emote-spiderman",
    "272": "emote-kawaiipose",
    "273": "emote-celebration",
    "274": "emote-rest",
    "275": "emote-floss",
    "276": "emote-kickingback",
    "277": "emote-zerogravitychill",
    "278": "emote-heroentrance",
    "279": "emote-headball",
    "280": "emote-woah",
    "281": "emote-breakdance",
    "282": "emote-minedance",
    "283": "emote-selfietime",
    "284": "emote-flex",
    "285": "emote-yogaflow",
    "286": "emote-cursing",
    "287": "emote-swagbounce",
    "288": "emote-blowingkisses",
    "289": "emote-flirtywave",
    "290": "emote-knockknock",
    "291": "emote-headball",
    "292": "emote-robotic",
    "293": "emote-balletbliss",
    "294": "emote-gwiddy",
    "295": "emote-pureheart",
    "296": "emote-frolic",
    "297": "emote-popularvibe",
    "298": "emote-shuffle",
    "299": "emote-graceful",
    "300": "emote-boogieswing",
    "301": "emote-twerkitout",
    "302": "emote-karate",
    "303": "emote-freshstep",
    "304": "emote-breakdance",
    "305": "emote-pose13",
    "306": "emote-tiktok6",
    "307": "emote-outfit2",
    "308": "emote-pose12",
    "309": "emote-pose11",
    "310": "emote-aliceshrink",
    "311": "emote-reachforthestars",
}


# ============================ BOT LOGIC ==============================
class Bot(BaseBot):
    def __init__(self):
        super().__init__()
        self.bot_user_id = None
        self._last_cmd_time = {}        # user_id -> timestamp (cooldown)
        self._emote_tasks = {}          # user_id -> asyncio.Task (looping emote)
        self._last_emote_used = {}      # user_id -> emote_id
        self._emote_number_used = {}    # user_id -> number string (for chat msgs)
        self._join_times = {}           # user_id -> datetime
        self._follow_target_username = None
        self._follow_task = None
        self._party_task = None
        self._testrange_task = None
        self._floors = {}
        self._authorized_user_ids = set()   # DM se "hi" bhejne wale users
        self._greeted_conversations = set()   # conversation_id already greeted

    # ------------------------- persistence -----------------------
    def _load_floors(self):
        try:
            if os.path.exists(FLOOR_FILE):
                with open(FLOOR_FILE, "r") as f:
                    self._floors = json.load(f)
        except Exception as e:
            log.warning(f"Floor load error: {e}")
            self._floors = {}

    def _save_floors(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(FLOOR_FILE, "w") as f:
                json.dump(self._floors, f)
        except Exception as e:
            log.warning(f"Floor save error: {e}")

    def _load_authorized(self):
        try:
            if os.path.exists(AUTH_FILE):
                with open(AUTH_FILE, "r") as f:
                    self._authorized_user_ids = set(json.load(f))
        except Exception as e:
            log.warning(f"Auth load error: {e}")
            self._authorized_user_ids = set()

    def _save_authorized(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(AUTH_FILE, "w") as f:
                json.dump(list(self._authorized_user_ids), f)
        except Exception as e:
            log.warning(f"Auth save error: {e}")

    # ------------------------- lifecycle -----------------------------
    async def on_start(self, session_metadata: SessionMetadata) -> None:
        # Fresh start after every (re)connect — clear old loop state.
        self._emote_tasks.clear()
        self._last_emote_used.clear()
        self._emote_number_used.clear()
        self._greeted_conversations.clear()

        self.bot_user_id = session_metadata.user_id
        os.makedirs(DATA_DIR, exist_ok=True)
        self._load_floors()
        self._load_authorized()
        log.info(f"✅ {BOT_NAME} connected! bot_user_id = {self.bot_user_id}")
        try:
            await self.highrise.chat(
                f"🤖 {BOT_NAME} is online! Emote use karne ke liye pehle mujhe DM mein "
                f"'hi' bhejo, phir number (1-{len(EMOTES)}) bhejkar emote LOOP karo. "
                f"'0'/'!stop' se rok sakte ho. Quick floors: !floor0 !floor1 !floor2. Owner: !owner"
            )
        except Exception as e:
            log.warning(f"Startup message error: {e}")

    async def on_user_join(self, user: User, *args, **kwargs) -> None:
        join_time = datetime.now()
        self._join_times[user.id] = join_time
        time_str = join_time.strftime("%d-%b-%Y %I:%M %p")
        log.info(f"➡️ {user.username} joined the room: {time_str}")
        if WELCOME_MESSAGE_ENABLED:
            asyncio.create_task(self._send_welcome_with_retry(user, time_str))

    async def _send_welcome_with_retry(self, user: User, time_str: str) -> None:
        # Small delay avoids Highrise's anti-spam swallowing a chat message
        # sent the instant a join event fires.
        await asyncio.sleep(WELCOME_MESSAGE_DELAY_SECONDS)
        for attempt in range(2):
            try:
                await self.highrise.chat(f"👋 Welcome, {user.username}! (Joined: {time_str})")
                return
            except Exception as e:
                log.warning(f"Welcome message error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(1.5)

    async def on_user_leave(self, user: User) -> None:
        # Clean up their loop so we don't leak memory/tasks.
        await self._cancel_loop(user.id)

    async def on_moderate(self, moderator_id, target_user_id, moderate_type, action_length=None) -> None:
        log.info(f"Room moderated: mod={moderator_id} target={target_user_id} action={moderate_type} len={action_length}")

    # ---- DM (private message) handling ----
    async def _get_last_dm_text(self, conversation_id: str) -> str:
        """Fetches the most recent DM text in this conversation. Defensive
        about SDK attribute naming since it can vary between SDK versions."""
        try:
            resp = await self.highrise.get_messages(conversation_id)
            msgs = getattr(resp, "content", resp) or getattr(resp, "messages", None) or resp
            if not msgs:
                return ""
            last = msgs[-1] if isinstance(msgs, (list, tuple)) else None
            if last is None:
                return ""
            for attr in ("content", "message", "text", "body"):
                val = getattr(last, attr, None)
                if val:
                    return str(val).strip().lower()
        except Exception as e:
            log.warning(f"get_messages error: {e}")
        return ""

    async def _dm_send_emote_list(self, conversation_id: str) -> None:
        numbers = sorted(EMOTES.keys(), key=lambda n: int(n))
        if not numbers:
            await self.highrise.send_message(conversation_id, "Abhi koi emote list nahi hai.", "text")
            return
        chunk_size = 40
        chunks = [numbers[i:i + chunk_size] for i in range(0, len(numbers), chunk_size)]
        await self.highrise.send_message(
            conversation_id,
            f"🕺 Total {len(numbers)} emotes hain. Room mein jaakar number bhejo, wahi emote loop hoga:",
            "text",
        )
        for chunk in chunks:
            try:
                await self.highrise.send_message(conversation_id, ", ".join(chunk), "text")
            except Exception as e:
                log.warning(f"Emote list DM chunk error: {e}")
            await asyncio.sleep(0.5)

    async def on_message(self, user_id, conversation_id, is_new_conversation) -> None:
        log.info(f"DM received from {user_id} in {conversation_id} (new={is_new_conversation})")
        try:
            text = await self._get_last_dm_text(conversation_id)

            # 1) Emote list request
            if any(k in text for k in EMOTE_LIST_KEYWORDS):
                await self._dm_send_emote_list(conversation_id)
                return

            # 2) Authorization opt-in — "hi"/"hello" etc, ya bilkul naya conversation
            if any(k in text for k in AUTH_KEYWORDS) or is_new_conversation:
                already = user_id in self._authorized_user_ids
                self._authorized_user_ids.add(user_id)
                self._save_authorized()
                if already:
                    await self.highrise.send_message(
                        conversation_id,
                        f"✅ Aapke paas pehle se hi access hai! Room mein number (1-{len(EMOTES)}) bhejo.",
                        "text",
                    )
                else:
                    await self.highrise.send_message(
                        conversation_id,
                        DM_AUTH_GRANTED_MESSAGE.format(max=len(EMOTES)),
                        "text",
                    )
                return

            # 3) Fallback
            await self.highrise.send_message(conversation_id, DM_FALLBACK_MESSAGE, "text")
        except Exception as e:
            log.warning(f"DM reply error: {e}")

    # ------------------------- main chat handler ----------------------
    async def on_chat(self, user: User, message: str) -> None:
        try:
            await self._handle_chat(user, message)
        except Exception:
            # One bad command should never crash the whole bot.
            log.error(f"on_chat handler error:\n{traceback.format_exc()}")

    def _is_authorized(self, user: User, is_owner: bool, is_helper: bool) -> bool:
        return is_owner or is_helper or user.id in self._authorized_user_ids

    async def _handle_chat(self, user: User, message: str) -> None:
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

        # ---------- Public: quick floor teleports ----------
        if lower in ("!floor0", "!f0", "!ground", "!groundfloor"):
            await self._public_goto_quick_floor(user, "0")
            return
        if lower in ("!floor1", "!f1"):
            await self._public_goto_quick_floor(user, "1")
            return
        if lower in ("!floor2", "!f2"):
            await self._public_goto_quick_floor(user, "2")
            return

        # ---------- Public: stop own loop (koi bhi rok sakta hai, auth ki zaroorat nahi) ----------
        if text == "0" or lower in ("!stop", "stop"):
            await self._cancel_loop(user.id, play_stop_emote=True, announce=user)
            return

        # ---------- Public: numbered emotes -> LOOP until stop (authorization required) ----------
        if text in EMOTES:
            if not self._is_authorized(user, is_owner, is_helper):
                await self.highrise.chat(
                    f"🔒 {user.username}, emote use karne se pehle mujhe DM mein 'hi' bhejo!"
                )
                return
            emote_id = EMOTES[text]
            if not self._check_cooldown(user.id):
                return
            await self._start_loop_emote(user.id, emote_id, announce=user, number=text)
            self._last_emote_used[user.id] = emote_id
            return

        if lower == "!again":
            if not self._is_authorized(user, is_owner, is_helper):
                await self.highrise.chat(f"🔒 {user.username}, pehle DM mein 'hi' bhejo!")
                return
            emote_id = self._last_emote_used.get(user.id)
            if emote_id is None:
                await self.highrise.chat("⚠️ You haven't used any emote yet.")
            else:
                await self._start_loop_emote(user.id, emote_id, announce=user)
            return

        if lower == "!random":
            if not self._is_authorized(user, is_owner, is_helper):
                await self.highrise.chat(f"🔒 {user.username}, pehle DM mein 'hi' bhejo!")
                return
            filled = list(EMOTES.values())
            if filled:
                emote_id = random.choice(filled)
                await self._start_loop_emote(user.id, emote_id, announce=user)
                self._last_emote_used[user.id] = emote_id
            return

        if lower == "!myemote":
            emote_id = self._last_emote_used.get(user.id)
            if emote_id and user.id in self._emote_tasks:
                await self.highrise.chat(f"🕺 {user.username}, currently playing: {emote_id}")
            else:
                await self.highrise.chat(f"{user.username}, no emote loop is running for you.")
            return

        if lower in ("!emotes", "!list") or lower.startswith("!emotes "):
            await self._show_emote_page(lower)
            return

        if lower in ("!help", "!commands"):
            await self.highrise.chat(
                f"🎉 Pehle mujhe DM mein 'hi' bhejo access lene ke liye. Phir number "
                f"(1-{len(EMOTES)}) bhejo LOOP karne ke liye. '0'/'!stop' rokta hai. "
                "'!again' repeats, '!random' random emote, '!emotes <page>' list dikhata "
                "hai, '!myemote' status, '!floor0/!floor1/!floor2' teleport karta hai."
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

        if lower.startswith("!testrange "):
            parts = text[11:].strip().split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                await self._start_testrange(int(parts[0]), int(parts[1]))
            else:
                await self.highrise.chat("⚠️ Format: !testrange <start> <end>  e.g. !testrange 46 60")
            return True

        if lower == "!testrangestop":
            await self._stop_testrange()
            return True

        if lower.startswith("!addemote "):
            parts = text[10:].strip().split(maxsplit=1)
            if len(parts) == 2 and parts[0].isdigit():
                EMOTES[parts[0]] = parts[1]
                await self.highrise.chat(f"✅ Emote #{parts[0]} = '{parts[1]}' added.")
            else:
                await self.highrise.chat("⚠️ Format: !addemote <number> <emote_id>")
            return True

        if lower.startswith("!removeemote "):
            n = text[13:].strip()
            if n in EMOTES:
                del EMOTES[n]
                await self.highrise.chat(f"🗑️ Emote #{n} removed.")
            else:
                await self.highrise.chat("⚠️ That number isn't in the list.")
            return True

        # ---- authorization management ----
        if lower.startswith("!auth "):
            target_name = text[6:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            else:
                self._authorized_user_ids.add(target_user.id)
                self._save_authorized()
                await self.highrise.chat(f"🔓 {target_name} ab emotes use kar sakta hai.")
            return True

        if lower.startswith("!deauth "):
            target_name = text[8:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' room mein nahi mila.")
            else:
                self._authorized_user_ids.discard(target_user.id)
                self._save_authorized()
                await self.highrise.chat(f"🔒 {target_name} ka access hata diya.")
            return True

        if lower == "!authlist":
            await self.highrise.chat(f"🔓 Total authorized users: {len(self._authorized_user_ids)}")
            return True

        # ---- party mode: whole room cycles emotes together ----
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
                await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
            else:
                await self.highrise.walk_to(pos)
                await self.highrise.chat(f"🚶 Walking towards {target_name}...")
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
                    await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
                else:
                    try:
                        await self.highrise.send_whisper(target_user.id, msg)
                        await self.highrise.chat(f"✉️ Whisper sent to {target_name}.")
                    except Exception as e:
                        log.warning(f"Whisper error: {e}")
                        await self.highrise.chat("⚠️ Whisper failed.")
            else:
                await self.highrise.chat("⚠️ Format: !whisper <username> <message>")
            return True

        if lower.startswith("!react "):
            parts = text[7:].strip().split(maxsplit=1)
            if len(parts) == 2:
                target_name, reaction = parts
                target_user, _ = await self._get_position(target_name)
                if target_user is None:
                    await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
                else:
                    try:
                        await self.highrise.react(reaction, target_user.id)
                    except Exception as e:
                        log.warning(f"React error: {e}")
                        await self.highrise.chat("⚠️ Reaction failed.")
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
            await self.highrise.chat(f"✅ {name} is now a trusted helper.")
            return True
        if lower.startswith("!removehelper "):
            name = text[14:].strip().lower()
            TRUSTED_HELPERS.discard(name)
            await self.highrise.chat(f"🗑️ {name} is no longer a helper.")
            return True

        # ---- voice ----
        if lower.startswith("!voiceadd "):
            target_name = text[10:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
            else:
                try:
                    await self.highrise.add_user_to_voice(target_user.id)
                    await self.highrise.chat(f"🎤 Added {target_name} to voice.")
                except Exception as e:
                    log.warning(f"Voice add error: {e}")
                    await self.highrise.chat("⚠️ Voice add failed.")
            return True
        if lower.startswith("!voiceremove "):
            target_name = text[13:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
            else:
                try:
                    await self.highrise.remove_user_from_voice(target_user.id)
                    await self.highrise.chat(f"🔇 Removed {target_name} from voice.")
                except Exception as e:
                    log.warning(f"Voice remove error: {e}")
                    await self.highrise.chat("⚠️ Voice remove failed.")
            return True

        # ---- economy ----
        if lower.startswith("!tip "):
            parts = text[5:].strip().split()
            if len(parts) == 2:
                target_name, amount = parts
                target_user, _ = await self._get_position(target_name)
                if target_user is None:
                    await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
                else:
                    try:
                        await self.highrise.tip_user(target_user.id, amount)
                        await self.highrise.chat(f"💰 Sent {amount} tip to {target_name}.")
                    except Exception as e:
                        log.warning(f"Tip error: {e}")
                        await self.highrise.chat("⚠️ Tip failed. Valid: gold_bar_1/5/10/50/100/500/1k/5000/10k")
            else:
                await self.highrise.chat("⚠️ Format: !tip <username> <gold_bar_amount>")
            return True

        if lower == "!wallet":
            try:
                wallet = await self.highrise.get_wallet()
                await self.highrise.chat(f"💼 Bot wallet: {wallet.content}")
            except Exception as e:
                log.warning(f"Wallet error: {e}")
                await self.highrise.chat("⚠️ Couldn't fetch wallet.")
            return True

        if lower == "!who":
            try:
                room_users = (await self.highrise.get_room_users()).content
                names = ", ".join(ru.username for ru, _ in room_users)
                await self.highrise.chat(f"👥 In room: {names}" if names else "Room is empty.")
            except Exception as e:
                log.warning(f"Who error: {e}")
            return True

        if lower.startswith("!joined "):
            target_name = text[8:].strip()
            target_user, _ = await self._get_position(target_name)
            if target_user is None:
                await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
            elif target_user.id in self._join_times:
                jt = self._join_times[target_user.id]
                await self.highrise.chat(f"🕒 {target_name} joined: {jt.strftime('%d-%b-%Y %I:%M %p')}")
            else:
                await self.highrise.chat(f"⚠️ No join-time recorded for '{target_name}'.")
            return True

        return False

    # ============================ HELPER (LIGHT) COMMANDS ==============
    async def _handle_helper_command(self, user: User, text: str, lower: str) -> bool:
        if lower in ("!hhelp", "!helperhelp"):
            await self.highrise.chat("🙋 Helper: !come | !announce <msg> | !test <emote_id> | !floor <name> | !party | !partystop")
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
        await self.highrise.chat(f"👑 Public: 'hi' DM karo access ke liye → number (1-{len(EMOTES)}) = looping emote | '0'/'!stop' stops it | '!again' | '!random' | '!emotes <page>' | '!myemote' | !floor0/!floor1/!floor2")
        await self.highrise.chat("👑 Owner (1/4): !come | !follow | !unfollow | !goto <user> | !tp x y z | !tpto <user> | !bring <user> | !party | !partystop")
        await self.highrise.chat("👑 Owner (2/4) FLOORS: !setfloor <name> | !floor <name> | !floors | !delfloor <name>  (use 0/1/2 as names for the public quick-floors)")
        await self.highrise.chat("👑 Owner (3/4): !test <id> | !testrange <start> <end> | !testrangestop | !addemote <n> <id> | !removeemote <n> | !announce <msg> | !whisper <user> <msg> | !react <user> <reaction>")
        await self.highrise.chat("👑 Owner (4/4): !kick/!mute/!ban/!unmute/!unban <user> | !mod/!unmod/!designer <user> | !voiceadd/!voiceremove <user> | !tip <user> <amt> | !wallet | !who | !joined <user> | !addhelper/!removehelper <user> | !auth/!deauth <user> | !authlist")

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
            log.warning(f"Emote '{emote_id}' failed: {e}")
            if notify is not None:
                await self.highrise.chat(f"⚠️ '{emote_id}' is an invalid or unavailable emote.")

    # ---- LOOPING EMOTE ENGINE ----
    async def _start_loop_emote(self, user_id: str, emote_id: str, announce: User = None, number: str = None) -> None:
        """Replays the emote every EMOTE_REPEAT_SECONDS until cancelled
        (user sends '0'/'!stop' or picks a new emote). Purana loop pehle
        POORI TARAH ruk jaata hai (_cancel_loop ab await karta hai) taaki
        do loops kabhi overlap na ho — yehi "emote stop nahi hota" wala
        bug tha."""
        await self._cancel_loop(user_id)

        async def _loop():
            try:
                while True:
                    await self._try_emote(user_id, emote_id)
                    await asyncio.sleep(EMOTE_REPEAT_SECONDS)
            except asyncio.CancelledError:
                pass
            except Exception:
                log.error(f"Emote loop crashed for {user_id}:\n{traceback.format_exc()}")

        self._emote_tasks[user_id] = asyncio.create_task(_loop())
        if number:
            self._emote_number_used[user_id] = number

        if announce is not None:
            label = f"#{number}" if number else emote_id
            try:
                await self.highrise.chat(f"🕺 {announce.username} started emote {label} (looping) — send '0' to stop.")
            except Exception as e:
                log.warning(f"Announce error: {e}")

    async def _cancel_loop(self, user_id: str, play_stop_emote: bool = False, announce: User = None) -> None:
        task = self._emote_tasks.pop(user_id, None)
        had_loop = task is not None
        if task is not None:
            task.cancel()
            # FIX: purana task poori tarah khatam hone ka wait karo, warna
            # naya loop start hote hi purana ek aakhri emote bhej sakta hai
            # aur lagta hai "stop nahi ho raha".
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.error(f"Error while cancelling loop for {user_id}:\n{traceback.format_exc()}")
        if play_stop_emote:
            try:
                await self.highrise.send_emote(STOP_EMOTE_ID, user_id)
            except Exception as e:
                log.warning(f"Stop emote error: {e}")
        self._last_emote_used.pop(user_id, None)
        self._emote_number_used.pop(user_id, None)
        if announce is not None and had_loop:
            try:
                await self.highrise.chat(f"⏹️ {announce.username}'s emote loop stopped.")
            except Exception as e:
                log.warning(f"Announce error: {e}")

    async def _get_position(self, username: str):
        room_users = (await self.highrise.get_room_users()).content
        for room_user, pos in room_users:
            if room_user.username.lower() == username.lower():
                return room_user, pos
        return None, None

    async def _show_emote_page(self, lower: str):
        filled = sorted(EMOTES.items(), key=lambda t: int(t[0]))
        if not filled:
            await self.highrise.chat("No emotes are active yet.")
            return
        parts = lower.split()
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        per_page = 10
        start = (page - 1) * per_page
        chunk = filled[start:start + per_page]
        if not chunk:
            await self.highrise.chat(f"Page {page} is empty. Total emotes: {len(filled)}")
            return
        listing = ", ".join(n for n, _ in chunk)
        total_pages = (len(filled) + per_page - 1) // per_page
        await self.highrise.chat(f"🕺 Emotes page {page}/{total_pages} ({len(filled)} total): {listing}")

    # ---- owner diagnostics: batch-test a range of emote numbers ----
    async def _start_testrange(self, start: int, end: int) -> None:
        await self._stop_testrange()
        if start > end:
            await self.highrise.chat("⚠️ Invalid range.")
            return

        async def _loop():
            try:
                for n in range(start, end + 1):
                    emote_id = EMOTES.get(str(n))
                    if not emote_id:
                        continue
                    if self.bot_user_id:
                        await self.highrise.chat(f"Testing #{n} → {emote_id}")
                        await self._try_emote(self.bot_user_id, emote_id)
                    await asyncio.sleep(3.5)
                await self.highrise.chat(f"✅ Test range {start}-{end} finished. Note any that didn't animate, then fix with !addemote or remove with !removeemote.")
            except asyncio.CancelledError:
                pass
            except Exception:
                log.error(f"Testrange loop crashed:\n{traceback.format_exc()}")

        self._testrange_task = asyncio.create_task(_loop())

    async def _stop_testrange(self) -> None:
        if self._testrange_task is not None:
            self._testrange_task.cancel()
            self._testrange_task = None

    # ---- party mode ----
    async def _start_party(self) -> None:
        await self._stop_party()
        filled = list(EMOTES.values())
        if not filled:
            await self.highrise.chat("⚠️ No emotes are filled in for party mode.")
            return

        async def _loop():
            try:
                while True:
                    if self.bot_user_id:
                        await self._try_emote(self.bot_user_id, random.choice(filled))
                    await asyncio.sleep(EMOTE_REPEAT_SECONDS)
            except asyncio.CancelledError:
                pass
            except Exception:
                log.error(f"Party loop crashed:\n{traceback.format_exc()}")

        self._party_task = asyncio.create_task(_loop())
        await self.highrise.chat("🎉 Party mode ON — the bot will cycle random emotes! Send '!partystop' to stop.")

    async def _stop_party(self) -> None:
        if self._party_task is not None:
            self._party_task.cancel()
            self._party_task = None

    # ---- movement helpers ----
    async def _bot_come_to_owner(self, owner: User) -> None:
        _, owner_pos = await self._get_position(owner.username)
        if owner_pos is None:
            await self.highrise.chat("⚠️ Couldn't find your position.")
            return
        try:
            if self.bot_user_id:
                await self.highrise.teleport(self.bot_user_id, owner_pos)
            else:
                await self.highrise.walk_to(owner_pos)
            await self.highrise.chat(f"🛰️ Here I am, {owner.username}!")
        except Exception as e:
            log.warning(f"Come-here error: {e}")
            await self.highrise.chat("⚠️ Something went wrong coming over.")

    async def _teleport_owner_to_coords(self, owner: User, coords_str: str) -> None:
        try:
            parts = coords_str.split()
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            dest = Position(x, y, z, facing="FrontRight")
            await self.highrise.teleport(owner.id, dest)
            await self.highrise.chat(f"🚀 {owner.username}, teleported to {x},{y},{z}!")
        except Exception as e:
            log.warning(f"TP error: {e}")
            await self.highrise.chat("⚠️ Format: !tp <x> <y> <z>")

    async def _teleport_owner_to_user(self, owner: User, target_name: str) -> None:
        _, target_pos = await self._get_position(target_name)
        if target_pos is None:
            await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
            return
        try:
            await self.highrise.teleport(owner.id, target_pos)
            await self.highrise.chat(f"🚀 {owner.username}, teleported next to {target_name}!")
        except Exception as e:
            log.warning(f"TPTO error: {e}")
            await self.highrise.chat("⚠️ Teleport failed.")

    async def _bring_user_to_owner(self, owner: User, target_name: str) -> None:
        _, owner_pos = await self._get_position(owner.username)
        target_user, _ = await self._get_position(target_name)
        if owner_pos is None or target_user is None:
            await self.highrise.chat(f"⚠️ '{target_name}' or the owner isn't in the room.")
            return
        try:
            await self.highrise.teleport(target_user.id, owner_pos)
            await self.highrise.chat(f"🚀 Brought {target_name} to {owner.username}!")
        except Exception as e:
            log.warning(f"Bring error: {e}")
            await self.highrise.chat("⚠️ Bring failed.")

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
                    log.warning(f"Follow loop error: {e}")
                await asyncio.sleep(3)

        self._follow_task = asyncio.create_task(_loop())
        await self.highrise.chat(f"🐾 Now following {owner_username} (within this room only). Send '!unfollow' to stop.")

    async def _stop_follow(self) -> None:
        self._follow_target_username = None
        if self._follow_task is not None:
            self._follow_task.cancel()
            self._follow_task = None

    # ---- floor helpers (owner: named floors, saved) ----
    async def _set_floor(self, owner: User, name: str) -> None:
        if not name:
            await self.highrise.chat("⚠️ Format: !setfloor <name>  (use 0, 1, or 2 for the public quick-floors)")
            return
        _, owner_pos = await self._get_position(owner.username)
        if owner_pos is None:
            await self.highrise.chat("⚠️ Couldn't find your position.")
            return
        self._floors[name.lower()] = {
            "x": owner_pos.x, "y": owner_pos.y, "z": owner_pos.z,
            "facing": getattr(owner_pos, "facing", "FrontRight"),
        }
        self._save_floors()
        await self.highrise.chat(f"📍 Floor '{name}' saved!")

    async def _goto_floor(self, owner: User, name: str) -> None:
        if not name:
            await self.highrise.chat("⚠️ Format: !floor <name>")
            return
        data = self._floors.get(name.lower())
        if data is None:
            await self.highrise.chat(f"⚠️ Floor '{name}' isn't set. Use '!setfloor {name}' first.")
            return
        try:
            dest = Position(data["x"], data["y"], data["z"], facing=data.get("facing", "FrontRight"))
            await self.highrise.teleport(owner.id, dest)
            await self.highrise.chat(f"🚀 {owner.username}, teleported to floor '{name}'!")
        except Exception as e:
            log.warning(f"Floor TP error: {e}")
            await self.highrise.chat("⚠️ Floor teleport failed.")

    async def _list_floors(self) -> None:
        if not self._floors:
            await self.highrise.chat("No floors are set yet.")
            return
        await self.highrise.chat(f"🏢 Saved floors: {', '.join(sorted(self._floors.keys()))}")

    async def _del_floor(self, name: str) -> None:
        if name.lower() in self._floors:
            del self._floors[name.lower()]
            self._save_floors()
            await self.highrise.chat(f"🗑️ Floor '{name}' deleted.")
        else:
            await self.highrise.chat(f"⚠️ Floor '{name}' not found.")

    # ---- floor helper (public: quick 0/1/2 for any room user) ----
    async def _public_goto_quick_floor(self, user: User, name: str) -> None:
        """Any user in the room can self-teleport to floor 0/1/2 once the
        owner has saved them with !setfloor 0 / !setfloor 1 / !setfloor 2."""
        data = self._floors.get(name)
        if data is None:
            await self.highrise.chat(
                f"⚠️ Floor '{name}' isn't set up yet. Owner needs to stand there "
                f"and send '!setfloor {name}' once."
            )
            return
        try:
            dest = Position(data["x"], data["y"], data["z"], facing=data.get("facing", "FrontRight"))
            await self.highrise.teleport(user.id, dest)
            await self.highrise.chat(f"🚀 {user.username}, teleported to floor {name}!")
        except Exception as e:
            log.warning(f"Public floor TP error: {e}")
            await self.highrise.chat("⚠️ Teleport failed.")

    # ---- moderation / privilege ----
    async def _moderate(self, target_name: str, action: str, minutes: int = None) -> None:
        target_user, _ = await self._get_position(target_name)
        if target_user is None:
            await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
            return
        try:
            if minutes is not None:
                await self.highrise.moderate_room(target_user.id, action, minutes)
            else:
                await self.highrise.moderate_room(target_user.id, action)
            await self.highrise.chat(f"🛡️ {target_name}: {action} done.")
        except Exception as e:
            log.warning(f"Moderate '{action}' error: {e}")
            await self.highrise.chat(f"⚠️ '{action}' failed — the bot needs Moderator/Owner rights in this room.")

    async def _set_privilege(self, target_name: str, privilege: str) -> None:
        target_user, _ = await self._get_position(target_name)
        if target_user is None:
            await self.highrise.chat(f"⚠️ '{target_name}' not found in the room.")
            return
        try:
            await self.highrise.set_room_privilege(target_user.id, privilege)
            await self.highrise.chat(f"🎖️ {target_name} is now '{privilege}'.")
        except Exception as e:
            log.warning(f"Set privilege '{privilege}' error: {e}")
            await self.highrise.chat("⚠️ Couldn't set privilege — the bot needs Owner rights.")


# ============================ HEALTH-CHECK SERVER ========================
async def _health_handler(request):
    return web.Response(text="OK - LANAX.4 bot is running")


async def start_health_server():
    """Small HTTP server needed for Render's health-check and for
    UptimeRobot-style external pings. If aiohttp isn't installed or PORT
    isn't set, this is skipped silently — the bot still runs, it just
    won't be reachable/pingable over HTTP (see 24/7 notes at top)."""
    if not AIOHTTP_AVAILABLE:
        log.warning("aiohttp not installed — health-check server skipped. "
                    "Add 'aiohttp' to requirements.txt for 24/7 uptime pinging.")
        return

    port = int(os.environ.get("PORT", "10000"))
    app = web.Application()
    app.router.add_get("/", _health_handler)
    app.router.add_get("/health", _health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"🌐 Health-check server running on port {port} (/ and /health)")


async def self_ping_loop():
    """Internal keep-alive: pings the bot's own /health endpoint every
    SELF_PING_INTERVAL_SECONDS. This generates internal HTTP traffic which
    helps on some hosts, but on Render's FREE plan an EXTERNAL ping
    (UptimeRobot etc.) every 5-10 min is still required — see the 24/7
    notes at the top of this file."""
    if not AIOHTTP_AVAILABLE:
        return
    port = int(os.environ.get("PORT", "10000"))
    url = f"http://127.0.0.1:{port}/health"
    timeout = ClientTimeout(total=10)
    await asyncio.sleep(15)  # let the health server finish starting up first
    while True:
        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    log.info(f"🔁 Self-ping {url} → {resp.status}")
        except Exception as e:
            log.warning(f"Self-ping error: {e}")
        await asyncio.sleep(SELF_PING_INTERVAL_SECONDS)


# ============================ CRASH-PROOF RUNNER (CLI-BASED) ============
async def run_bot_forever():
    """
    Runs the bot through the OFFICIAL highrise-bot-sdk CLI, in a
    subprocess — exactly as the SDK README describes:

        highrise <module>:<BotClass> <room_id> <api_token>

    This doesn't depend on any PRIVATE/internal SDK function (like the
    old `highrise.run()`, which doesn't exist) so it's less likely to
    break on future SDK updates.

    If the CLI process ever exits/crashes (network drop, SDK error,
    etc.), it's restarted automatically — this process never
    permanently exits, and it always reconnects to the SAME ROOM_ID.
    """
    module_name = os.path.splitext(os.path.basename(__file__))[0]  # e.g. "bot"
    target = f"{module_name}:Bot"
    cmd = ["highrise", target, ROOM_ID, BOT_TOKEN]

    attempt = 0
    while True:
        attempt += 1
        log.info(f"🚀 Starting bot (attempt #{attempt}) via: highrise {target} <room_id> <token>")
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            # Stream the child process (highrise CLI) logs into our own
            # logger so everything shows up together in Render's logs.
            if process.stdout is not None:
                async for raw_line in process.stdout:
                    line = raw_line.decode(errors="ignore").rstrip()
                    if line:
                        log.info(f"[highrise-cli] {line}")
            returncode = await process.wait()
            log.warning(f"⚠️ highrise CLI process exited (code {returncode}).")
        except FileNotFoundError:
            log.error(
                "❌ 'highrise' command not found in this environment. "
                "Confirm 'highrise-bot-sdk==25.1.0' installed correctly "
                "(check Render build logs)."
            )
        except Exception:
            log.error(f"❌ Bot runner crashed:\n{traceback.format_exc()}")

        log.info(f"⏳ Retrying in {RECONNECT_DELAY_SECONDS} seconds...")
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)


async def main():
    await asyncio.gather(
        start_health_server(),
        self_ping_loop(),
        run_bot_forever(),
    )


if __name__ == "__main__":
    asyncio.run(main())
