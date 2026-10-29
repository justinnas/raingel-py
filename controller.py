"""
controller.py - protocol constants, packet helpers and the Raingel-compatible light controller.
"""
import asyncio
from datetime import datetime

MIN_CHIPS, MAX_CHIPS = 16, 2048   # limits for ic-length
WRITE_CHAR = "0000ae01-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR = "0000ae02-0000-1000-8000-00805f9b34fb"
WRITE_WITH_RESPONSE = False   # packets are written without response
SCAN_SERVICE = "0000af30-0000-1000-8000-00805f9b34fb"
APP_ID = 22872   # mfr data = [group, type]

GROUPS = {1: "DIM", 2: "CCT", 3: "RGB", 4: "RGBW", 5: "RGBC", 6: "RGBCW",
          16: "MAGIC (addressable)", 17: "MAGIC_W_2PATH", 18: "MAGIC_C_2PATH",
          19: "START (sphere)", 20: "MAGIC_W", 21: "MAGIC_CW"}
MAGIC_GROUPS = (16, 20, 21)
TWO_PATH_GROUPS = (17, 18)
SPHERE_GROUP = 19

TYPES = {1: "bulb", 2: "strip", 3: "ceiling", 4: "flood", 5: "spot"}

# Addressable ("magic") effects, ids 1..18.
MAGIC_EFFECTS = ["fade", "jump", "breathe", "flash", "meteor", "heap-up", "float",
                 "follow-spot", "wave", "run-water", "rainbow", "blink", "bounce",
                 "shuttle", "like", "on-off", "mid", "twa"]

# Alternate form of a magic effect: a flag ORed into the mode byte.
# Effects not listed (blink, bounce, like, twa) have only one form.
EFFECT_ALT = {**{n: ("section", 0x80) for n in MAGIC_EFFECTS[0:4]},
              **{n: ("reverse", 0x40) for n in MAGIC_EFFECTS[4:11]},
              "shuttle": ("multicolor", 0x40), "on-off": ("alternate", 0x40),
              "mid": ("curtain-down", 0x40)}

# Plain RGB and sphere effects, sent as 07 <1..4> ...
RGB_EFFECTS = ["fade", "jump", "breathe", "flash"]

# Two-path scenes, ids 250..266; only the low 5 bits are sent.
TWO_PATH_SCENES = ["auto", "multicolor", "async-jump", "async-fade", "jump", "fade",
                   "twinkle-1", "twinkle-2", "strobe-1", "strobe-2", "flick", "breathe",
                   "ww-flick", "ww-breathe", "rgbw-jump", "rgbw-flick", "in-waves"]

# Palette indices used by scene colors.
PALETTE = ["red", "green", "blue", "yellow", "cyan", "purple", "orange", "white"]
MAX_SCENE_COLORS = 8

# Mic effects 0..3; addressable and plain RGB lights name them differently.
MIC_EFFECTS = {"classic": 0, "roll": 1, "soft": 1, "energy": 2, "dynamic": 2,
               "spectrum": 3, "disco": 3}

IC_ORDERS = ["RGB", "RBG", "GRB", "GBR", "BRG", "BGR"]   # sent as index + 1

# Alarm weekday bits, Monday = bit 0.
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_GROUPS = {"daily": 127, "everyday": 127, "weekdays": 31, "weekend": 96, "once": 0}
MAX_ALARMS = 6

GAP = 0.12   # pause after an IC-count change so the controller can apply it

# ---------------------------------------------------------- PHONE MIC / MUSIC ---
# Not implemented: "phone mic" and music modes. The phone does all the audio
# analysis and streams the result; the light only renders it.
#
#   11 04                      enter phone-mic mode, sent when recording /
#                              a track starts
#   10 RR GG BB 00 00 VV EE    one frame
#        RR GG BB  next color of a 6-step cycle, advanced every frame:
#                  red, (255,125,0), yellow, green, blue, cyan
#        VV        loudness, sent as `value & 0xFF` (wraps, does not clamp)
#        EE        mic effect 0..3 (same ids as MIC_EFFECTS); music always sends 3
#   10 RR GG BB 00 00 00 EE    on stop (VV = 0)
#
# Mic loudness: 16 kHz mono 16-bit PCM, one frame per read then a 150 ms sleep:
#     VV = max(0, int(20 * log10(mean(abs(samples))) * 2.55))
# Music loudness (one frame per FFT capture of the playing audio):
#     db = int(10 * log10(sum(b * b for b in waveform) / len(waveform)))
#          (waveform bytes read as signed bytes)
#     VV = int((db - 40) * 0.85 * 255)
# -----------------------------------------------------------------------------


def clamp(v, lo=0, hi=255):
    return max(lo, min(hi, int(v)))


def pack_colors(indices, pad_to=0):
    """[0, 1, 2] -> count byte + nibble-packed indices: 03 01 20 (padded)."""
    nibbles = "".join(f"{i:x}" for i in indices)
    if len(nibbles) % 2:
        nibbles += "0"
    body = bytes.fromhex(nibbles).ljust(pad_to, b"\x00")
    return bytes([len(indices)]) + body


def clock_packet(now=None):
    """08 01 00 00 00 + year (LE) month day hour min sec."""
    now = now or datetime.now()
    return bytes([0x08, 0x01, 0, 0, 0, now.year & 0xFF, now.year >> 8,
                  now.month, now.day, now.hour, now.minute, now.second])


def connect_packets():
    """Packets to send after every (re)connect: the clock, which alarms depend on."""
    return [clock_packet()]


def parse_advertisement(manufacturer_data, service_uuids):
    """(group, type) from a light's advertisement, either may be None; None if it isn't a light."""
    mfr = manufacturer_data.get(APP_ID)
    if mfr is None and SCAN_SERVICE not in service_uuids:
        return None
    group = mfr[0] if mfr else None
    mtype = mfr[1] if mfr and len(mfr) > 1 else None
    return group, mtype


def check_colors(colors):
    """Scene colors: at most MAX_SCENE_COLORS PALETTE indices."""
    colors = list(colors)
    if len(colors) > MAX_SCENE_COLORS:
        raise ValueError(f"at most {MAX_SCENE_COLORS} colors")
    if any(not 0 <= c < len(PALETTE) for c in colors):
        raise ValueError(f"color indices must be 0..{len(PALETTE) - 1}")
    return colors


def group_commands(group):
    """The commands that apply to a device group."""
    color = {2: ["cct"], 16: ["color"], 4: ["color", "white"], 5: ["color", "cct"],
             19: ["color", "white", "motor", "laser"], 20: ["color", "white"],
             21: ["color", "cct"]}.get(group, ["color", "cct", "white"])
    if group in MAGIC_GROUPS:
        scene, settings = "effect", ["ic-order", "ic-length"]
    elif group in TWO_PATH_GROUPS:
        scene, settings = "2path-effect", ["ic-order"]
    elif group == SPHERE_GROUP:
        scene, settings = "sphere-effect", ["ic-order"]
    else:
        scene, settings = "rgb-effect", ["ic-order"]
    return ["on/off", "brightness"] + color + [scene, "mic", "delay", "alarm"] + settings


class Controller:
    """
    Builds packets for the lights and writes them through a connection (anything with
    send(data)). Invalid arguments raise ValueError. color, white, cct and device_mic
    turn the light on first.
    """

    def __init__(self, conn):
        self.conn = conn

    async def send(self, data):
        await self.conn.send(data)

    async def power(self, on):
        await self.send(bytes([0x01, 0x01 if on else 0x00]))

    async def brightness(self, pct):
        await self.send(bytes([0x02, clamp(pct, 0, 100)]))

    async def set_ic_count(self, n):
        """Number of addressable chips, MIN_CHIPS..MAX_CHIPS."""
        if not MIN_CHIPS <= n <= MAX_CHIPS:
            raise ValueError(f"chip count must be {MIN_CHIPS}..{MAX_CHIPS}")
        await self.send(bytes([0x0F, n & 0xFF, n >> 8]))
        await asyncio.sleep(GAP)

    async def color(self, r, g, b):
        await self.power(True)
        await self.send(bytes([0x03, clamp(r), clamp(g), clamp(b), 0, 0, 0]))

    async def white(self, level):
        """White channel level 0..255."""
        await self.power(True)
        await self.send(bytes([0x03, 0, 0, 0, clamp(level), 0, 0x01]))

    async def cct(self, temperature):
        """Color temperature: 0 = warm .. 255 = cool."""
        await self.power(True)
        await self.send(bytes([0x03, 0, 0, 0, 0, clamp(temperature), 0x01]))

    async def _scene(self, mode, speed, brightness, colors=b""):
        await self.send(bytes([0x07, mode, clamp(speed, 0, 100), clamp(brightness, 0, 100)])
                        + colors)

    async def effect(self, name, speed=50, brightness=100, colors=range(8), alt=False):
        """Addressable ('magic') effects; colors are PALETTE indices."""
        mode_id = MAGIC_EFFECTS.index(name) + 1
        if alt:
            if name not in EFFECT_ALT:
                raise ValueError(f"{name} has no alternate form")
            mode_id |= EFFECT_ALT[name][1]
        await self._scene(mode_id, speed, brightness, pack_colors(check_colors(colors), pad_to=4))

    async def rgb_effect(self, name, speed=50, brightness=100, colors=(0, 1, 2)):
        """Effects for plain RGB / RGBW / RGBC / RGBCW / CCT / DIM controllers."""
        await self._scene(RGB_EFFECTS.index(name) + 1, speed, brightness,
                          pack_colors(check_colors(colors)))

    async def sphere_effect(self, name, speed=50, brightness=100, colors=(0, 1)):
        """Effects for sphere ('START') lights; colors padded to 4 bytes."""
        await self._scene(RGB_EFFECTS.index(name) + 1, speed, brightness,
                          pack_colors(check_colors(colors), pad_to=4))

    async def two_path_effect(self, name, speed=50, brightness=100):
        """Scenes for two-path (MAGIC_W_2PATH / MAGIC_C_2PATH) lights."""
        await self._scene((250 + TWO_PATH_SCENES.index(name)) & 0x1F, speed, brightness)

    async def motor(self, on, speed=50):
        """Sphere lights' rotation motor."""
        await self.send(bytes([0x15, 1 if on else 0, 0, clamp(speed, 0, 100)]))

    async def laser(self, on, speed=50):
        """Sphere lights' laser / star projector."""
        await self.send(bytes([0x17, 1 if on else 0, 0, clamp(speed, 0, 100), 0x64]))

    async def device_mic(self, effect=0, sensitivity=50):
        """Let the light's own microphone drive it."""
        await self.power(True)
        await self.send(bytes([0x04, effect, clamp(sensitivity, 0, 100)]))

    async def delay(self, minutes):
        """Delay timer; 0 minutes cancels."""
        minutes = clamp(minutes, 0, 0xFFFF)
        await self.send(bytes([0x05, 1 if minutes else 0, 0x01, minutes & 0xFF, minutes >> 8]))

    async def alarms(self, alarms):
        """
        Replace the light's alarm list. alarms: (hour, minute, turn_on, weekday_bits),
        at most 6; weekday_bits 0 = no repeat. An empty list clears them all.
        """
        if len(alarms) > MAX_ALARMS:
            raise ValueError(f"the light holds at most {MAX_ALARMS} alarms")
        if not alarms:
            return await self.send(bytes([0x0D, 0, 0]))
        data = bytearray([0x0D])
        for i, (hour, minute, on, days) in enumerate(alarms):
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError(f"bad alarm time {hour}:{minute:02}")
            data += bytes([hour | i << 5, minute | (0x80 if on else 0), days])
        await self.send(bytes(data))

    async def sync_time(self):
        await self.send(clock_packet())

    async def ic_order(self, order):
        """Chip color order, persisted by the light."""
        await self.send(bytes([0x0E, IC_ORDERS.index(order) + 1]))
