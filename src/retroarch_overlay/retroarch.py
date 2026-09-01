import socket
from typing import Protocol

from .models import RetroArchStatus


class RetroArchError(RuntimeError):
    pass


class MemoryReader(Protocol):
    def read_memory(self, address: int, size: int) -> bytes: ...


def parse_status_response(response: str) -> RetroArchStatus:
    parts = response.strip().split(" ", 2)
    if len(parts) < 2 or parts[0] != "GET_STATUS":
        raise RetroArchError(f"Unexpected status response: {response!r}")

    detail = parts[2] if len(parts) == 3 else ""
    core, separator, content_detail = detail.partition(",")
    content = content_detail.strip() if separator else ""
    content_crc32 = ""
    content_match = content.rsplit(",crc32=", 1)
    if len(content_match) == 2 and len(content_match[1]) == 8:
        content, content_crc32 = content_match[0], content_match[1].lower()
    return RetroArchStatus(parts[1], core.strip(), content, content_crc32)


def parse_memory_response(response: str, address: int) -> bytes:
    parts = response.strip().split()
    expected_address = f"{address:x}"
    if len(parts) < 2 or parts[0] != "READ_CORE_MEMORY":
        raise RetroArchError(f"Unexpected memory response: {response!r}")
    if parts[1].lower() != expected_address:
        raise RetroArchError(f"Memory response address mismatch: {response!r}")
    if len(parts) >= 3 and parts[2] == "-1":
        raise RetroArchError("RetroArch core has no descriptor for that address")
    try:
        return bytes(int(value, 16) for value in parts[2:])
    except ValueError as error:
        raise RetroArchError(f"Invalid memory response: {response!r}") from error


class RetroArchClient:
    _ALLOWED_COMMANDS = frozenset({"GET_STATUS", "READ_CORE_MEMORY"})
    _MEMORY_CHUNK_SIZE = 256

    def __init__(self, host: str = "127.0.0.1", port: int = 55355, timeout: float = 0.4):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _request(self, command: str) -> str:
        verb = command.partition(" ")[0]
        if verb not in self._ALLOWED_COMMANDS:
            raise RetroArchError(f"Command is not permitted: {verb}")

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.settimeout(self.timeout)
            connection.sendto(command.encode("ascii"), (self.host, self.port))
            try:
                response, _ = connection.recvfrom(65_535)
            except TimeoutError as error:
                raise RetroArchError("RetroArch did not respond") from error
        return response.decode("ascii", errors="replace")

    def get_status(self) -> RetroArchStatus:
        return parse_status_response(self._request("GET_STATUS"))

    def read_memory(self, address: int, size: int) -> bytes:
        if address < 0 or not 1 <= size <= 4096:
            raise ValueError("Memory reads require a non-negative address and 1-4096 bytes")

        chunks = []
        for offset in range(0, size, self._MEMORY_CHUNK_SIZE):
            chunk_address = address + offset
            chunk_size = min(self._MEMORY_CHUNK_SIZE, size - offset)
            response = self._request(
                f"READ_CORE_MEMORY {chunk_address:x} {chunk_size}"
            )
            data = parse_memory_response(response, chunk_address)
            if len(data) != chunk_size:
                raise RetroArchError(
                    f"Expected {chunk_size} bytes at 0x{chunk_address:X}, "
                    f"received {len(data)}"
                )
            chunks.append(data)
        return b"".join(chunks)
