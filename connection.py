"""
connection.py - BLE scanning and connections to Raingel-compatible lights.
"""
import asyncio

from bleak import BleakClient, BleakScanner
from bleak.args.winrt import WinRTClientArgs
from bleak.backends.device import BLEDevice

from controller import (NOTIFY_CHAR, WRITE_CHAR, WRITE_WITH_RESPONSE, connect_packets,
                        parse_advertisement)


async def find_lights(timeout=10.0):
    """[(BLEDevice, AdvertisementData, (group, type))] for every Raingel-compatible light seen."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    lights = []
    for dev, adv in found.values():
        info = parse_advertisement(adv.manufacturer_data, adv.service_uuids)
        if info is not None:
            lights.append((dev, adv, info))
    return lights


class Connection:
    """One or more lights; every packet is written to all of them."""

    def __init__(self, addresses, verbose=False, retries=6, address_type=None):
        self.addresses = list(addresses)
        self.address_type = address_type   # None = let Windows decide; "public" / "random"
        self.verbose = verbose
        self.retries = retries
        self.clients = {}      # address -> BleakClient

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def _is_connected(self, address):
        client = self.clients.get(address)
        return client is not None and client.is_connected

    @property
    def connected(self):
        return all(self._is_connected(a) for a in self.addresses)

    async def connect(self):
        for address in self.addresses:
            if not self._is_connected(address):
                await self._connect_one(address)

    async def _connect_one(self, address):
        """
        Connect by MAC without scanning: a hand-made BLEDevice makes bleak
        skip its internal find_device_by_address.
        """
        device = BLEDevice(address, None, None)
        winrt = WinRTClientArgs(address_type=self.address_type) if self.address_type \
            else WinRTClientArgs()
        for attempt in range(1, self.retries + 1):
            try:
                client = BleakClient(device, disconnected_callback=self._on_disconnect,
                                     timeout=15.0, winrt=winrt)
                self.clients[address] = client
                await client.connect()
                if self.verbose:
                    await client.start_notify(
                        NOTIFY_CHAR, lambda _s, data, a=address: self._on_notify(a, data))
                for packet in connect_packets():
                    await client.write_gatt_char(WRITE_CHAR, packet,
                                                 response=WRITE_WITH_RESPONSE)
                print(f"connected to {address}")
                return
            except Exception as e:
                print(f"{address}: connect attempt {attempt}/{self.retries} failed: "
                      f"{e or type(e).__name__}")
                await self._close_one(address)
                await asyncio.sleep(1.5)
        raise ConnectionError(f"could not connect to {address}")

    async def close(self):
        for address in list(self.clients):
            await self._close_one(address)

    async def _close_one(self, address):
        client = self.clients.pop(address, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    def _on_disconnect(self, client):
        print(f"\n({client.address} disconnected, will reconnect on next command)")

    def _on_notify(self, address, data):
        prefix = f"{address} " if len(self.addresses) > 1 else ""
        print(f"{prefix}<- {bytes(data).hex(' ')}")

    async def send(self, data):
        await self.connect()
        if self.verbose:
            print(f"-> {data.hex(' ')}")
        for address in self.addresses:
            try:
                await self._write(address, data)
            except Exception as e:
                print(f"{address}: write failed ({e}), reconnecting...")
                await self._close_one(address)
                await self._connect_one(address)
                await self._write(address, data)

    async def _write(self, address, data):
        await self.clients[address].write_gatt_char(WRITE_CHAR, data,
                                                    response=WRITE_WITH_RESPONSE)
