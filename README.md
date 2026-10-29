# raingel-py

A reverse-engineered Python command-line tool for controlling Raingel-compatible Bluetooth LE LED lights from Windows.

Simple and lightweight - can be used as a reference for other applications or custom UIs.

## Requirements

- Windows 10 or 11 with Bluetooth LE
- Python 3.9+
- [bleak](https://github.com/hbldh/bleak)

```sh
pip install -r requirements.txt
```

## Quick start

```sh
python rain.py info     # find lights and their supported commands
python rain.py      # start interactive shell
```

After finding your device, set `DEVICE` at the top of `rain.py` to your light's address.

> Many controllers only allow one connection at the time. Try closing the app on your phone if there are connection issues.

## Options

| Option | Description |
| --- | --- |
| `--address MAC` | Light to control. Repeat for several lights. |
| `--all` | Scan and control every light found |
| `--address-type public\|random` | Force the BLE address type if Windows can't find the light |
| `-v`, `--verbose` | Print packets sent and replies |

## Interactive shell

Run with no command to stay connected and type commands. It reconnects automatically.

```
raingel> on; color 255 0 0; wait 1; color #0000ff
raingel> help effect
raingel> quit
```

Separate commands with `;`. `help CMD` shows a command's options.

## Which commands fit my light?

`info` shows each light's device group and the commands it supports.

| Device group | Color commands | Scene command |
| --- | --- | --- |
| MAGIC (addressable) | `color` | `effect` |
| MAGIC_W | `color`, `white` | `effect` |
| MAGIC_CW | `color`, `cct` | `effect` |
| RGBW | `color`, `white` | `rgb-effect` |
| RGBC | `color`, `cct` | `rgb-effect` |
| CCT | `cct` | `rgb-effect` |
| RGB, RGBCW, DIM | `color`, `cct`, `white` | `rgb-effect` |
| MAGIC_W_2PATH, MAGIC_C_2PATH | `color`, `cct`, `white` | `2path-effect` |
| START (sphere) | `color`, `white`, `motor`, `laser` | `sphere-effect` |

`on`, `off`, `brightness`, `mic`, `delay`, `alarm` and `ic-order` work on every group. `ic-length` is for addressable lights only.

## Commands

Run each one as `python rain.py CMD ...`, or type it in the shell.

### Power and color

```sh
on
off
brightness 60       # 0..100
color 255 0 128     # or "#ff0080"
white 200           # white channel 0..255
cct 80              # color temperature: 0 warm .. 255 cool
```

### Scenes

> Note: custom effects and effect colors may not be fully supported as it is limited by the lights' actual controller.

All scenes take `--speed 0..100` and `--brightness 0..100`. `--colors` takes up to 8 of: `red`, `green`, `blue`, `yellow`, `cyan`, `purple`, `orange`, `white`.

```sh
effect rainbow --speed 70               # addressable
effect meteor --colors red blue --alt
rgb-effect breathe --colors red blue    # plain RGB-type
sphere-effect jump --colors red white   # sphere
2path-effect twinkle-1 --speed 60       # two-path (no colors)
```

| Command | Effects |
| --- | --- |
| `effect` | fade, jump, breathe, flash, meteor, heap-up, float, follow-spot, wave, run-water, rainbow, blink, bounce, shuttle, like, on-off, mid, twa |
| `rgb-effect`, `sphere-effect` | fade, jump, breathe, flash |
| `2path-effect` | auto, multicolor, async-jump, async-fade, jump, fade, twinkle-1, twinkle-2, strobe-1, strobe-2, flick, breathe, ww-flick, ww-breathe, rgbw-jump, rgbw-flick, in-waves |

`--alt` picks an effect's second form: by section (fade to flash), reverse (meteor to rainbow), multicolor (shuttle), alternate (on-off), curtain down (mid).

### Sphere lights

```sh
motor on --speed 30     # rotation
laser on --speed 50     # star / laser projector
motor off
```

### Sound (light's own microphone)

```sh
mic energy --sensitivity 80
```

Effects: classic, roll / soft, energy / dynamic, spectrum / disco. The two names are what addressable and other lights call the same effect; either works.

### Timers

```sh
delay 30        # minutes, or H:MM
delay cancel
alarm 07:30 on weekdays 23:00 off daily
alarm 08:00 on sat sun
alarm clear
```

Each alarm is a time, then `on`/`off` (default `on`), then days: `daily`, `weekdays`, `weekend`, `once` or `mon`..`sun` (default once). The light holds up to 6 alarms, and each `alarm` command replaces the list.

The light's clock is set on every connect; `sync-time` sets it on demand.

### Settings

```sh
ic-order GRB    # chip color order: RGB RBG GRB GBR BRG BGR
ic-length 144   # number of addressable chips, 16..2048
```

### Debugging

```sh
raw "03 ff 00 00 00 00 00"  # send any bytes
wait 1.5                    # pause, for shell command chains
```

## Protocol

Service `AE30`, write characteristic `AE01` (write-without-response), notify characteristic `AE02`. Lights advertise service `AF30` and manufacturer data `22872` = `[group, type]`. No framing or checksum: first byte is the command, then raw arguments.

| Bytes | Command | Notes |
| --- | --- | --- |
| `01 PP` | Power | `01` on, `00` off |
| `02 BB` | Brightness | 0..100 |
| `03 RR GG BB WW CC FF` | Color | `FF` = 0: RGB. `FF` = 1: `WW` white level or `CC` color temperature |
| `04 EE SS` | Device mic | effect 0..3, sensitivity 0..100 |
| `05 EN 01 LL HH` | Delay | `EN` 1 set / 0 cancel, minutes little-endian |
| `07 MM SS BB [colors]` | Scene | speed, brightness; mode and colors depend on the group |
| `08 01 00 00 00 YY YY MO DD HH MI SS` | Clock | year little-endian |
| `0D [HH MM WD]...` | Alarms | max 6, `HH \|= index << 5`, `MM \|= 0x80` for on, `WD` weekday bits (Mon = 1) |
| `0E OO` | IC order | 1..6 = RGB RBG GRB GBR BRG BGR |
| `0F LL HH` | IC count | little-endian |
| `15 EN 00 SS` | Motor | sphere lights |
| `17 EN 00 SS 64` | Laser | sphere lights |

Scene colors are a count byte followed by palette indices packed one per nibble (padded to 4 bytes for addressable and sphere lights). Two-path scenes send `(250 + scene) & 0x1F` and no colors.

Phone-mic and music modes are not implemented. Their protocol is documented in a comment block in `rain.py`.
<br>

---

<br>

> This script may also be compatible with older DoHome (DoHomeStrip) devices. Though, this is not tested.

> **Disclaimer:** This is an independent, unofficial project, made with the help of AI. Not affiliated with Raingel or any device manufacturer.  Use it at your own risk.
