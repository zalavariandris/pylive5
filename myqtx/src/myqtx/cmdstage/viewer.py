import json
import sys
import traceback
from typing import Any

from qtpy.QtCore import QTimer
from qtpy.QtNetwork import QLocalServer, QLocalSocket
from qtpy.QtWidgets import QApplication

from myqtx.displaywidget import DisplayWidget

from .transport import decode_payload


class ViewerServer:
    def __init__(self, name: str) -> None:
        self.display_widget = DisplayWidget()
        self.display_widget.setWindowTitle("cmdstage")
        self.display_widget.resize(960, 700)
        self.connections: set[QLocalSocket] = set()
        self.server = QLocalServer()
        if not self.server.listen(name):
            raise RuntimeError(f"Cannot listen on {name}: {self.server.errorString()}")
        self.server.newConnection.connect(self.accept)
        self.display_widget.show()

    def accept(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            if sock is None:
                break
            self.connections.add(sock)
            sock.readyRead.connect(lambda s=sock: self.read(s))
            sock.disconnected.connect(lambda s=sock: self.disconnect(s))
            # A complete request may already be buffered when we accept it.
            self.read(sock)

    def disconnect(self, sock: QLocalSocket) -> None:
        self.connections.discard(sock)
        sock.deleteLater()

    def read(self, sock: QLocalSocket) -> None:
        while sock.canReadLine():
            line = bytes(sock.readLine())
            try:
                response = self.handle(json.loads(line))
            except Exception as exc:
                traceback.print_exc()
                response = {"ok": False, "error": str(exc)}
            sock.write((json.dumps(response) + "\n").encode("utf-8"))
            sock.flush()

    def handle(self, command: dict[str, Any]) -> dict[str, Any]:
        match command["action"]:
            case "ping":
                pass
            case "show":
                self.display_widget.display(decode_payload(command["data"]))
                self.display_widget.show()
            case "clear":
                self.display_widget.clear()
            case "close":
                app = QApplication.instance()
                if app is not None:
                    QTimer.singleShot(0, app.quit)
            case _:
                raise ValueError("Unknown stage command")
        return {"ok": True}


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    server = ViewerServer(sys.argv[1])
    try:
        return app.exec()
    finally:
        server.server.close()


if __name__ == "__main__":
    sys.exit(main())
