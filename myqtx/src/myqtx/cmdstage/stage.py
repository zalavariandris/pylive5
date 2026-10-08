import json
import math
import subprocess
import sys
import time
import uuid
from typing import Any

from .transport import encode_payload


class Stage:
    """Start a persistent Qt viewer on first show(), and stop it with close()."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        self.timeout = timeout
        self.name = f"cmdstage-{uuid.uuid4().hex}"
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.name = f"cmdstage-{uuid.uuid4().hex}"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "myqtx.cmdstage.viewer", self.name]
        )
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(f"Stage viewer exited during startup ({self.process.returncode})")
                try:
                    self._send({"action": "ping"})
                    return
                except (RuntimeError, TimeoutError):
                    time.sleep(0.02)
            raise TimeoutError("Stage viewer did not start")
        except BaseException:
            self._stop_process()
            raise

    def _send(self, message: dict[str, Any]) -> None:
        # Socket communication does not require a QApplication in the caller.
        from qtpy.QtNetwork import QLocalSocket

        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Stage is not running; call start() first")
        payload = (json.dumps(message, allow_nan=False) + "\n").encode("utf-8")
        deadline = time.monotonic() + self.timeout

        def remaining_ms() -> int:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Stage viewer did not acknowledge the command")
            return max(1, int(remaining * 1000))

        sock = QLocalSocket()
        try:
            sock.connectToServer(self.name)
            if not sock.waitForConnected(remaining_ms()):
                raise RuntimeError(f"Viewer unavailable: {sock.errorString()}")
            if sock.write(payload) != len(payload):
                raise RuntimeError(f"Could not send viewer command: {sock.errorString()}")
            while sock.bytesToWrite():
                if not sock.waitForBytesWritten(remaining_ms()):
                    raise TimeoutError("Could not send viewer command")
            while not sock.canReadLine():
                if sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
                    raise RuntimeError("Stage viewer disconnected before acknowledging the command")
                sock.waitForReadyRead(remaining_ms())
            result = json.loads(bytes(sock.readLine()))
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Viewer error"))
        finally:
            sock.abort()

    def show(self, data: object = None) -> None:
        """Start if needed, then display data and wait for the viewer to own it."""
        with encode_payload(data) as payload:
            self.start()
            self._send({"action": "show", "data": payload})

    def clear(self) -> None:
        """Clear the content if the viewer is running."""
        if self.process is not None and self.process.poll() is None:
            self._send({"action": "clear"})

    def _stop_process(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        try:
            if process.poll() is not None:
                return
            try:
                self._send({"action": "close"})
            except (RuntimeError, TimeoutError):
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass  # The final cleanup terminates an unresponsive viewer.
        finally:
            self._stop_process()

