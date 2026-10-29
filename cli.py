"""
cli.py - command parsing, dispatch and the interactive shell.
"""
import asyncio
import shlex

from connection import find_lights
from controller import (DAY_GROUPS, GROUPS, IC_ORDERS, MAGIC_EFFECTS, MAX_ALARMS, MAX_CHIPS,
                        MAX_SCENE_COLORS, MIC_EFFECTS, MIN_CHIPS, PALETTE, RGB_EFFECTS,
                        TWO_PATH_SCENES, TYPES, WEEKDAYS, group_commands)


def parse_color(values):
    if len(values) == 1:
        h = values[0].lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if len(values) == 3:
        return tuple(int(v) for v in values)
    raise SystemExit("color takes R G B or #RRGGBB")


def palette_indices(names, default):
    if not names:
        return default
    try:
        return [PALETTE.index(n) for n in names]
    except ValueError:
        raise SystemExit(f"colors must be from: {', '.join(PALETTE)}")


def parse_minutes(value):
    """'90' or '1:30' -> 90; 'cancel' -> 0."""
    if value.lower() in ("cancel", "off"):
        return 0
    try:
        if ":" in value:
            h, m = value.split(":")
            return int(h) * 60 + int(m)
        return int(value)
    except ValueError:
        raise SystemExit("delay takes minutes, H:MM or 'cancel'")


def parse_alarms(tokens):
    """
    '07:30 on weekdays 23:00 off sat sun' -> [(7, 30, True, 31), (23, 0, False, 96)].
    Each alarm starts with HH:MM, then optional on/off (default on) and days
    (daily, weekdays, weekend, once or mon..sun; default once). 'clear' -> [].
    """
    words = " ".join(tokens).lower().replace(",", " ").split()
    if words == ["clear"]:
        return []
    alarms = []
    for w in words:
        if ":" in w:
            try:
                hour, minute = (int(x) for x in w.split(":"))
            except ValueError:
                raise SystemExit(f"bad time {w!r}, use HH:MM")
            alarms.append([hour, minute, True, 0])
        elif not alarms:
            raise SystemExit("each alarm starts with a time, e.g. 07:30")
        elif w in ("on", "off"):
            alarms[-1][2] = w == "on"
        elif w in DAY_GROUPS:
            alarms[-1][3] |= DAY_GROUPS[w]
        elif w[:3] in WEEKDAYS:
            alarms[-1][3] |= 1 << WEEKDAYS.index(w[:3])
        else:
            raise SystemExit(f"bad alarm word {w!r}: use on/off, "
                             f"{', '.join(DAY_GROUPS)} or mon..sun")
    return [tuple(a) for a in alarms]


async def cmd_info(args):
    print("Scanning 10s for Raingel lights...")
    for dev, adv, (group, mtype) in await find_lights():
        print(f"{dev.address}  rssi={adv.rssi}  name={dev.name!r}  "
              f"group={GROUPS.get(group, f'unknown({group})') if group is not None else '?'}  "
              f"type={TYPES.get(mtype, mtype) if mtype is not None else '?'}")
        if group is not None:
            print(f"    commands: {', '.join(group_commands(group))}")


async def execute(light, args):
    """Run one parsed command; the controller's ValueErrors become SystemExit messages."""
    try:
        await _execute(light, args)
    except ValueError as e:
        raise SystemExit(f"error: {e}")


async def _execute(light, args):
    if args.cmd == "on":
        await light.power(True)
    elif args.cmd == "off":
        await light.power(False)
    elif args.cmd == "brightness":
        await light.brightness(args.value)
    elif args.cmd == "color":
        await light.color(*parse_color(args.rgb))
    elif args.cmd == "white":
        await light.white(args.level)
    elif args.cmd == "cct":
        await light.cct(args.temperature)
    elif args.cmd == "effect":
        colors = palette_indices(args.colors, range(8))
        await light.effect(args.name, args.speed, args.brightness, colors, args.alt)
    elif args.cmd == "rgb-effect":
        colors = palette_indices(args.colors, (0, 1, 2))
        await light.rgb_effect(args.name, args.speed, args.brightness, colors)
    elif args.cmd == "sphere-effect":
        colors = palette_indices(args.colors, (0, 1))
        await light.sphere_effect(args.name, args.speed, args.brightness, colors)
    elif args.cmd == "2path-effect":
        await light.two_path_effect(args.name, args.speed, args.brightness)
    elif args.cmd in ("motor", "laser"):
        await getattr(light, args.cmd)(args.state == "on", args.speed)
    elif args.cmd == "mic":
        await light.device_mic(MIC_EFFECTS[args.effect], args.sensitivity)
    elif args.cmd == "delay":
        minutes = parse_minutes(args.time)
        await light.delay(minutes)
        print(f"delay set to {minutes} min" if minutes else "delay cancelled")
    elif args.cmd == "alarm":
        alarms = parse_alarms(args.spec)
        await light.alarms(alarms)
        print(f"{len(alarms)} alarm(s) sent" if alarms else "alarms cleared")
    elif args.cmd == "sync-time":
        await light.sync_time()
    elif args.cmd == "ic-order":
        await light.ic_order(args.order)
    elif args.cmd == "ic-length":
        await light.set_ic_count(args.chips)
    elif args.cmd == "raw":
        await light.send(bytes.fromhex(args.hex.replace(" ", "")))
    elif args.cmd == "wait":
        await asyncio.sleep(args.seconds)


async def shell(light, parser, commands):
    """Stay connected and read commands from the prompt."""
    print(f"Commands: {', '.join(c for c in commands if c != 'info')}.\n"
          "'help CMD' for options, 'quit' to exit.")
    while True:
        try:
            line = (await asyncio.to_thread(input, "raingel> ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            break
        if line.startswith("help"):
            line = (line[4:].strip() + " -h").strip()
        # allow several commands on one line: "on; color 255 0 0; wait 1; off"
        for part in line.split(";"):
            try:
                cmd = parser.parse_args(shlex.split(part))
                await execute(light, cmd)
            except SystemExit as e:  # argparse error or -h; keep the shell alive
                if isinstance(e.code, str):
                    print(e.code)
            except Exception as e:
                print(f"error: {e}")


def add_scene_args(s, colors_help=None):
    s.add_argument("--speed", type=int, default=50, help="0..100")
    s.add_argument("--brightness", type=int, default=100, help="0..100")
    if colors_help:
        s.add_argument("--colors", nargs="+", metavar="COLOR",
                       help=f"up to {MAX_SCENE_COLORS} from {PALETTE}; {colors_help}")


def add_commands(sub):
    sub.add_parser("info", help="scan, show each light's group and commands (one-shot only)")
    sub.add_parser("on")
    sub.add_parser("off")
    sub.add_parser("brightness").add_argument("value", type=int, help="0..100")
    sub.add_parser("color", help="RGB color").add_argument(
        "rgb", nargs="+", help="R G B or #RRGGBB")
    sub.add_parser("white", help="white channel (RGBW, RGBCW, MAGIC_W, ...)").add_argument(
        "level", type=int, help="0..255")
    sub.add_parser("cct", help="color temperature (CCT, RGBC, RGBCW, MAGIC_CW, ...)").add_argument(
        "temperature", type=int, help="0 warm .. 255 cool")

    s = sub.add_parser("effect", help="scene for addressable lights (MAGIC, MAGIC_W, MAGIC_CW)")
    s.add_argument("name", choices=MAGIC_EFFECTS)
    add_scene_args(s, "default: all 8")
    s.add_argument("--alt", action="store_true",
                   help="alternate form: section (fade..flash), reverse (meteor..rainbow),"
                        " multicolor (shuttle), alternate (on-off), curtain-down (mid)")

    s = sub.add_parser("rgb-effect", help="scene for RGB, RGBW, RGBC, RGBCW, CCT, DIM lights")
    s.add_argument("name", choices=RGB_EFFECTS)
    add_scene_args(s, "default: red green blue")

    s = sub.add_parser("sphere-effect", help="scene for sphere (START) lights")
    s.add_argument("name", choices=RGB_EFFECTS)
    add_scene_args(s, "default: red green")

    s = sub.add_parser("2path-effect", help="scene for two-path lights")
    s.add_argument("name", choices=TWO_PATH_SCENES)
    add_scene_args(s)

    for name, what in (("motor", "rotation motor"), ("laser", "laser / star projector")):
        s = sub.add_parser(name, help=f"sphere lights' {what}")
        s.add_argument("state", choices=["on", "off"])
        s.add_argument("--speed", type=int, default=50, help="0..100")

    s = sub.add_parser("mic", help="react to sound using the light's own microphone")
    s.add_argument("effect", nargs="?", default="classic", choices=MIC_EFFECTS,
                   help="addressable: classic/roll/energy/spectrum, others: classic/soft/dynamic/disco")
    s.add_argument("--sensitivity", type=int, default=50, help="0..100")

    sub.add_parser("delay", help="delay timer").add_argument(
        "time", help="minutes, H:MM, or 'cancel'")
    sub.add_parser("alarm", help=f"replace the light's alarms (max {MAX_ALARMS})").add_argument(
        "spec", nargs="+",
        help="HH:MM [on|off] [daily|weekdays|weekend|once|mon..sun] ..., or 'clear'")
    sub.add_parser("sync-time", help="set the light's clock to this PC's time")
    sub.add_parser("ic-order", help="chip color order").add_argument(
        "order", type=str.upper, choices=IC_ORDERS)
    sub.add_parser("ic-length", help="number of addressable chips").add_argument(
        "chips", type=int, help=f"{MIN_CHIPS}..{MAX_CHIPS}")

    sub.add_parser("raw").add_argument("hex")
    sub.add_parser("wait").add_argument("seconds", type=float)
