"""
rain.py - Windows controller for Raingel-compatible BLE LED lights.

See README.md for commands, device groups and the protocol.
"""
import argparse
import asyncio

from cli import add_commands, cmd_info, execute, shell
from connection import Connection, find_lights
from controller import Controller


# =============== SET DEVICE HERE ===============

DEVICE = "B5:98:05:F3:76:B3"

# ===============================================


async def run(args, cmd_parser, commands):
    if args.cmd == "info":
        return await cmd_info(args)
    addresses = args.address or [DEVICE]
    if args.all:
        print("Scanning 10s for lights...")
        addresses = [dev.address for dev, _adv, _mfr in await find_lights()]
        if not addresses:
            raise SystemExit("no lights found")
    async with Connection(addresses, verbose=args.verbose,
                          address_type=args.address_type) as conn:
        light = Controller(conn)
        if args.cmd is None:
            await shell(light, cmd_parser, commands)
        else:
            await execute(light, args)
            if args.verbose:
                await asyncio.sleep(1)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--address", action="append",
                   help=f"light MAC; repeat for several lights (default {DEVICE})")
    p.add_argument("--all", action="store_true", help="scan and control every light found")
    p.add_argument("--address-type", choices=["public", "random"],
                   help="force the BLE address type if Windows can't find the light")
    p.add_argument("-v", "--verbose", action="store_true", help="print packets and replies")
    add_commands(p.add_subparsers(dest="cmd"))

    # parser for lines typed into the shell
    cmd_parser = argparse.ArgumentParser(prog="", add_help=False)
    cmd_sub = cmd_parser.add_subparsers(dest="cmd", required=True)
    add_commands(cmd_sub)

    try:
        asyncio.run(run(p.parse_args(), cmd_parser, list(cmd_sub.choices)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
