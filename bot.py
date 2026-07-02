"""
====================================================================
  LANAX.4 — Highrise Bot (SINGLE ROOM, LOOPING EMOTES, FLOOR-TELEPORT)
  v5 — CRASH-PROOF + 24/7 READY
====================================================================

--------------------------------------------------------------------
IS VERSION MEIN KYA FIX/UPDATE HUA HAI (v5):
--------------------------------------------------------------------
1) AUTO-RESTART / CRASH-PROOF RUNNER
   Pehle agar `highrise.run()` ke andar KOI BHI unexpected exception
   aata tha (network drop, SDK internal error, koi bhi bug), pura
   Python process crash ho jaata tha aur exit code 1 ke saath band ho
   jaata tha. Render tab tak wait karta jab tak use dobara start na
   karna pade — isi wajah se bot "offline" dikhta tha.
   FIX: Ab `main()` ek infinite retry-loop mein hai. Agar bot kabhi
   bhi crash hoga (kisi bhi reason se), error log ho jayega aur bot
   khud 10 second baad dobara connect try karega — process kabhi
   exit nahi hoga. Isse Render restart-loop wali dikkat bhi khatam.

2) HEALTH-CHECK WEB SERVER (24/7 ke liye zaroori)
   Render "Web Service" type deployments ek open PORT expect karte
   hain, aur free-plan services bina traffic ke sleep ho sakti hain.
   FIX: Ek chhota aiohttp server add kiya hai jo $PORT par "OK" reply
   karta hai (`/` aur `/health` route). Isse:
     - Render ko pata chalta hai service healthy hai (agar Web
       Service type use kar rahe ho).
     - UptimeRobot (ya kisi bhi uptime-ping tool) se is URL ko har
       5 minute ping karke free-plan sleep hone se bacha sakte ho.

3) SECRETS AB ENVIRONMENT VARIABLES SE (safer)
   BOT_TOKEN aur ROOM_ID ab pehle os.environ se try hote hain, agar
   env var set nahi hai to purana hardcoded value fallback ke taur
   par chalta hai — isse token GitHub/public repo mein expose hone
   ka risk kam hota hai. Render Dashboard -> Environment mein
   BOT_TOKEN aur ROOM_ID daal sakte ho.

4) DM (private message) auto-reply — pehle jaisa hi, thoda polish.

5) Emote start/stop confirmation chat messages — pehle jaisa hi.

6) MINOR ROBUSTNESS FIXES:
   - Floors data har deploy pe reset ho sakta hai kyunki Render ka
     default disk ephemeral hota hai (persistent disk add-on ke
     bina). Isliye ek warning print hoti hai startup par.
   - Emote-loop tasks ab bot restart / on_start dobara chalne par
     bhi safely reset hote hain.

--------------------------------------------------------------------
"ONLINE 24/7" WALA ISSUE — ZAROORI JAANKARI:
--------------------------------------------------------------------
Yeh crash-proof runner bot ko crash hone par khud-ba-khud restart
karega bina process exit kiye — matlab agar Render "Background
Worker" ya "Web Service" chala rahe ho, wo baar-baar deploy/restart
nahi karega, bot process hamesha zinda rahega aur reconnect karta
rahega.

Lekin Render ke FREE plan ki apni limitation hai:
   - FREE "Web Service" 15 min inactivity ke baad sleep ho jaati hai
     (agar koi HTTP request na aaye). Health-check route isi liye
     add kiya hai — UptimeRobot se is URL ko 5 min mein ek baar ping
     karo taaki wo sleep na ho:
         https://<your-render-app>.onrender.com/health
   - FREE "Background Worker" ko koi bhi HTTP traffic wake nahi kar
     sakta — usme sirf paid "Starter" plan hi reliable 24/7 deta hai.

   -> Sabse reliable tareeka: Render Dashboard -> Service -> Settings
      -> Instance Type -> "Starter" (paid) plan.
   -> Free plan chahiye to service type "Web Service" rakho (Background
      Worker nahi) taaki health-check route ping ho sake.

--------------------------------------------------------------------
RENDER DEPLOY:
--------------------------------------------------------------------
1) requirements.txt:
       highrise-bot-sdk==25.1.0
       aiohttp>=3.9

2) Environment Variables (Render Dashboard -> Environment):
       PYTHON_VERSION = 3.11.9
       BOT_TOKEN       = <apna token>
       ROOM_ID         = <apna room id>
       PORT            = 10000   (Render usually apne aap set karta hai)

3) Start Command:
       python bot.py

4) Service Type:
   - Agar free plan par 24/7 ke liye health-check use karna hai to
     service ko "Web Service" banao (na ki "Background Worker"),
     taaki health-check route pe traffic aa sake.
====================================================================
"""

import asyncio
import json
import logging
import os
import random
import time
import traceback
from datetime import datetime

import highrise
from highrise import BaseBot, User
from highrise.__main__ import BotDefinition
from highrise.models import Position, SessionMetadata

try:
    from aiohttp import web
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

# Env vars ko priority — agar set nahi hain to purana hardcoded value chalega.
BOT_TOKEN = os.environ.get(
    "BOT_TOKEN",
    "c58d1869fbad962a328c20a2abc0333400a128ecbbf8c6d1bf9382b44cb2f87a",
)

# --- SIRF EK ROOM (multilogin crash fix) ---
ROOM_ID = os.environ.get("ROOM_ID", "63fcc70dfb16e9c663269160")

OWNER_USERNAME = "LANAX4"
OWNER_USER_ID = "lanax4"   # agar exact User ID pata ho toh yahan daal do

TRUSTED_HELPERS = set()   # example: {"myfriend123"}

EMOTE_COOLDOWN_SECONDS = 1.0        # naya command spam-guard
EMOTE_REPEAT_SECONDS = 4.0          # kitni der baad emote dobara chalega (loop)

WELCOME_MESSAGE_ENABLED = True

STOP_EMOTE_ID = "emote-wave"

DATA_DIR = "./bot_data"
FLOOR_FILE = os.path.join(DATA_DIR, "floors.json")

# Bot crash ho jaaye to kitne second baad reconnect try kare
RECONNECT_DELAY_SECONDS = 10

DM_WELCOME_MESSAGE = (
    "👋 Hi! Main {bot} hoon. Room mein jaake number (1 se 250) bhejo "
    "koi bhi emote LOOP mein chalane ke liye — rokne ke liye '0' ya "
    "'!stop' bhejo. Commands ke liye room chat mein '!help' likho."
)
DM_FALLBACK_MESSAGE = (
    "Main abhi sirf room ke commands samajhta hoon 🙂 Room mein aakar "
    "'!help' bhejo poori list dekhne ke liye."
)


# ============================ EMOTES (1-250) =========================
# Sirf verified IDs bhare hain. Baaki slots "REPLACE_ME_<n>" hain —
# unhe !addemote <n> <real_id> se bharo.
EMOTES_SET = {
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
    "23": "emote-cutey",  # Emote cute
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
    "287": "swagbounce",
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
    "311": "emote-reachforthestars"
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
        self._emote_number_used = {}    # user_id -> number string (for chat msgs)
        self._join_times = {}           # user_id -> datetime
        self._follow_target_username = None
        self._follow_task = None
        self._party_task = None
        self._floors = {}
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

    # ------------------------- lifecycle -----------------------------
    async def on_start(self, session_metadata: SessionMetadata) -> None:
        # Restart/reconnect ke baad purane loops fresh se shuru karo
        self._emote_tasks.clear()
        self._last_emote_used.clear()
        self._emote_number_used.clear()

        self.bot_user_id = session_metadata.user_id
        os.makedirs(DATA_DIR, exist_ok=True)
        self._load_floors()
        log.info(f"✅ {BOT_NAME} connect ho gaya! bot_user_id = {self.bot_user_id}")
        try:
            await self.highrise.chat(
                f"🤖 {BOT_NAME} online hai! Number bhejo (1-{len(EMOTES)}) apna emote "
                f"CHALU rakhne ke liye (loop hoga jab tak stop na bolo). "
                f"Rokne ke liye '0' ya '!stop'. Owner: !owner"
            )
        except Exception as e:
            log.warning(f"Startup message error: {e}")

    async def on_user_join(self, user: User, *args, **kwargs) -> None:
        join_time = datetime.now()
        self._join_times[user.id] = join_time
        time_str = join_time.strftime("%d-%b-%Y %I:%M %p")
        log.info(f"➡️ {user.username} room mein aaya: {time_str}")
        if WELCOME_MESSAGE_ENABLED:
            try:
                await self.highrise.chat(f"👋 Welcome, {user.username}! (Aaye: {time_str})")
            except Exception as e:
                log.warning(f"Welcome message error: {e}")

    async def on_user_leave(self, user: User) -> None:
        # Loop chal raha ho toh cleanup kar do taaki memory leak na ho
        await self._cancel_loop(user.id)

    async def on_moderate(self, moderator_id, target_user_id, moderate_type, action_length=None) -> None:
        log.info(f"Room moderated: mod={moderator_id} target={target_user_id} action={moderate_type} len={action_length}")

    # ---- DM (private message) handling — bot reply karta hai ----
    async def on_message(self, user_id, conversation_id, is_new_conversation) -> None:
        log.info(f"DM received from {user_id} in {conversation_id} (new={is_new_conversation})")
        try:
            if is_new_conversation or conversation_id not in self._greeted_conversations:
                self._greeted_conversations.add(conversation_id)
                await self.highrise.send_message(
                    conversation_id,
                    DM_WELCOME_MESSAGE.format(bot=BOT_NAME),
                    "text",
                )
            else:
                await self.highrise.send_message(conversation_id, DM_FALLBACK_MESSAGE, "text")
        except Exception as e:
            log.warning(f"DM reply error: {e}")

    # ------------------------- main chat handler ----------------------
    async def on_chat(self, user: User, message: str) -> None:
        try:
            await self._handle_chat(user, message)
        except Exception:
            # Kabhi bhi single chat command fail ho, pura bot crash na ho —
            # sirf error log ho aur bot chalta rahe.
            log.error(f"on_chat handler error:\n{traceback.format_exc()}")

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

        # ---------- Public: stop apna loop ----------
        if text == "0" or lower in ("!stop", "stop"):
            await self._cancel_loop(user.id, play_stop_emote=True, announce=user)
            return

        # ---------- Public: numbered emotes -> LOOP until stop ----------
        if text in EMOTES:
            emote_id = EMOTES[text]
            if emote_id.startswith("REPLACE_ME_"):
                await self.highrise.chat(f"⚠️ Emote #{text} abhi tak khaali hai.")
                return
            if not self._check_cooldown(user.id):
                return
            await self._start_loop_emote(user.id, emote_id, announce=user, number=text)
            self._last_emote_used[user.id] = emote_id
            return

        if lower == "!again":
            emote_id = self._last_emote_used.get(user.id)
            if emote_id is None:
                await self.highrise.chat("⚠️ Tumne abhi tak koi emote use nahi kiya.")
            else:
                await self._start_loop_emote(user.id, emote_id, announce=user)
            return

        if lower == "!random":
            filled = [e for e in EMOTES.values() if not e.startswith("REPLACE_ME_")]
            if filled:
                emote_id = random.choice(filled)
                await self._start_loop_emote(user.id, emote_id, announce=user)
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
                        log.warning(f"Whisper error: {e}")
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
                        log.warning(f"React error: {e}")
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
                    log.warning(f"Voice add error: {e}")
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
                    log.warning(f"Voice remove error: {e}")
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
                        log.warning(f"Tip error: {e}")
                        await self.highrise.chat("⚠️ Tip fail ho gaya. Valid: gold_bar_1/5/10/50/100/500/1k/5000/10k")
            else:
                await self.highrise.chat("⚠️ Format: !tip <username> <gold_bar_amount>")
            return True

        if lower == "!wallet":
            try:
                wallet = await self.highrise.get_wallet()
                await self.highrise.chat(f"💼 Bot wallet: {wallet.content}")
            except Exception as e:
                log.warning(f"Wallet error: {e}")
                await self.highrise.chat("⚠️ Wallet fetch nahi ho paya.")
            return True

        if lower == "!who":
            try:
                room_users = (await self.highrise.get_room_users()).content
                names = ", ".join(ru.username for ru, _ in room_users)
                await self.highrise.chat(f"👥 Room mein: {names}" if names else "Room khaali hai.")
            except Exception as e:
                log.warning(f"Who error: {e}")
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
            log.warning(f"Emote '{emote_id}' fail: {e}")
            if notify is not None:
                await self.highrise.chat(f"⚠️ '{emote_id}' invalid ya unavailable emote hai.")

    # ---- LOOPING EMOTE ENGINE ----
    async def _start_loop_emote(self, user_id: str, emote_id: str, announce: User = None, number: str = None) -> None:
        """Emote ko har EMOTE_REPEAT_SECONDS mein dobara chalata hai, jab tak
        cancel na ho (user '0'/'!stop' bole ya naya emote select kare).
        `announce` diya ho to bot world chat mein confirmation bhejta hai."""
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
                await self.highrise.chat(f"🕺 {announce.username} ne emote {label} start kiya (loop) — rokne ke liye '0' bhejo.")
            except Exception as e:
                log.warning(f"Announce error: {e}")

    async def _cancel_loop(self, user_id: str, play_stop_emote: bool = False, announce: User = None) -> None:
        task = self._emote_tasks.pop(user_id, None)
        had_loop = task is not None
        if task is not None:
            task.cancel()
        if play_stop_emote:
            try:
                await self.highrise.send_emote(STOP_EMOTE_ID, user_id)
            except Exception as e:
                log.warning(f"Stop emote error: {e}")
        self._last_emote_used.pop(user_id, None)
        self._emote_number_used.pop(user_id, None)
        if announce is not None and had_loop:
            try:
                await self.highrise.chat(f"⏹️ {announce.username} ka emote loop band ho gaya.")
            except Exception as e:
                log.warning(f"Announce error: {e}")

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

    # ---- party mode ----
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
            except Exception:
                log.error(f"Party loop crashed:\n{traceback.format_exc()}")

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
            log.warning(f"Come-here error: {e}")
            await self.highrise.chat("⚠️ Aane mein error aaya.")

    async def _teleport_owner_to_coords(self, owner: User, coords_str: str) -> None:
        try:
            parts = coords_str.split()
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            dest = Position(x, y, z, facing="FrontRight")
            await self.highrise.teleport(owner.id, dest)
            await self.highrise.chat(f"🚀 {owner.username}, teleport ho gaye {x},{y},{z} par!")
        except Exception as e:
            log.warning(f"TP error: {e}")
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
            log.warning(f"TPTO error: {e}")
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
            log.warning(f"Bring error: {e}")
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
                    log.warning(f"Follow loop error: {e}")
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
            log.warning(f"Floor TP error: {e}")
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
            log.warning(f"Moderate '{action}' error: {e}")
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
            log.warning(f"Set privilege '{privilege}' error: {e}")
            await self.highrise.chat("⚠️ Privilege set nahi ho paya — bot ke paas Owner rights chahiye.")


# ============================ HEALTH-CHECK SERVER ========================
async def _health_handler(request):
    return web.Response(text="OK - LANAX.4 bot is running")


async def start_health_server():
    """Chhota HTTP server jo Render health-check aur UptimeRobot ping ke
    liye zaroori hai. Agar aiohttp installed nahi hai ya PORT set nahi
    hai, to yeh silently skip ho jayega — bot phir bhi chalega."""
    if not AIOHTTP_AVAILABLE:
        log.warning("aiohttp installed nahi hai — health-check server skip ho gaya. "
                    "requirements.txt mein 'aiohttp' add karo 24/7 uptime-ping ke liye.")
        return

    port = int(os.environ.get("PORT", "10000"))
    app = web.Application()
    app.router.add_get("/", _health_handler)
    app.router.add_get("/health", _health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"🌐 Health-check server chal raha hai port {port} par (/ aur /health)")


# ============================ CRASH-PROOF RUNNER ========================
async def run_bot_forever():
    """Bot ko baar-baar reconnect karta hai agar kabhi crash ho jaaye —
    process kabhi exit nahi hota, isliye Render ise 'crashed' nahi maanega."""
    definitions = [BotDefinition(Bot, ROOM_ID, BOT_TOKEN)]
    attempt = 0
    while True:
        attempt += 1
        try:
            log.info(f"🚀 Bot start ho raha hai (attempt #{attempt})...")
            await highrise.run(definitions)
            # Agar highrise.run() normally return kar jaaye (rare case)
            log.warning("highrise.run() khatam ho gaya bina exception ke — dobara start kar rahe hain.")
        except Exception:
            log.error(f"❌ Bot crash ho gaya:\n{traceback.format_exc()}")
        log.info(f"⏳ {RECONNECT_DELAY_SECONDS} second baad reconnect try karenge...")
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)


async def main():
    await asyncio.gather(
        start_health_server(),
        run_bot_forever(),
    )


if __name__ == "__main__":
    asyncio.run(main())
