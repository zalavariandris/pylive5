from typing import Any, Literal, cast
from qtpy.QtCore import QRectF, QSizeF, Qt, QObject
from qtpy.QtGui import QColor, QTextCharFormat, QTextCursor
from qtpy.QtWidgets import QLabel, QPlainTextEdit

from enum import StrEnum

class LinterLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

class LinterMode(StrEnum):
    UNDERLINE = "underline"
    LABEL = "label"

class LinterLabelItem(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setAlignment(Qt.AlignmentFlag.AlignBaseline)
        self.setAutoFillBackground(True)
        # error_palette = QPalette()
        # error_palette.setColor(QPalette.ColorRole.Window, QColor(200,20,20,180))
        # error_palette.setColor(QPalette.ColorRole.WindowText, error_palette.color(QPalette.ColorRole.PlaceholderText))

        # # notification_label.setPalette(error_palette)
        # match level:
        #     case "info":
        #         level_color = 'rgba(0,0,200,100)'
        #     case "warning":
        #         level_color = 'rgba(200,200,0,100)'
        #     case "error":
        #         level_color = 'rgba(200,0,0,100)'
        #     case _:
        #         level_color = 'rgba(0,0,200,100)'

        self.setStyleSheet("""\
            padding: 0 2;
            border-radius: 3;
            background-color: {level_color};
            margin: 0;
            color: rgba(255,255,255,220);
        """.format(level_color='rgba(200,0,0,100)'))
        self.setWindowOpacity(0.5)


class TextEditLinterWidget(QObject):
    def __init__(self, textedit: QPlainTextEdit):
        super().__init__(textedit)

        self.textedit = textedit
        self.labels = []
        self.underlines = []

    def label(self, lineno, message):
        def getLineRect():
            # Check if the block corresponding to the line number is valid
            block = self.textedit.document().findBlockByLineNumber(lineno - 1)  # Use lineno - 1 for 0-based index

            if not block.isValid():  # Ensure the block is valid
                raise ValueError(f"{lineno} is not a valid line number")

            # Get the topLeft position
            font_metrics = self.textedit.fontMetrics()
            block_rect = self.textedit.blockBoundingGeometry(block)
            topleft = block_rect.topLeft()
            topleft+=self.textedit.contentOffset()

            # get line size
            text_width = font_metrics.horizontalAdvance(block.text())
            text_height = block_rect.height()
            
            return QRectF(topleft, QSizeF(text_width, text_height))
            

        # Create and position the notification label
        notification_label = LinterLabelItem(parent=self.textedit.viewport())
        notification_label.setText(f"{message}")  # Use the retrieved message
        notification_label.setFont(self.textedit.font())


        # Calculate the x position with a little padding
        # Get font metrics to align with the text baseline
        rect = getLineRect()
        # ascent = font_metrics.ascent()
        # descent = font_metrics.descent()
        # notification_x = int(block_rect.left() + text_width+5)
        # notification_y = int(block_rect.bottom() - ascent+1)
        notification_label.move(int(rect.right()), int(rect.top()))  # Adjust x and y position
        notification_label.show()

        # Store the notification label for future reference
        self.labels.append(notification_label)

    def underline(self, lineno, message:str|None=None):
        """Underline a specific line to indicate an error."""
        block = self.textedit.document().findBlockByLineNumber(lineno - 1)  # Line numbers are 1-based.
        if not block.isValid():
            return

        self.textedit.document().blockSignals(True)
        fmt = QTextCharFormat()
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        fmt.setUnderlineColor(QColor(200, 0, 0))
        if message:
            fmt.setToolTip(message)

        # Apply formatting to the entire block (line)
        cursor = QTextCursor(block)
        # if offset is None:
        #     cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        # else:
            # underline single charater
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        # cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, offset-1)
        # cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
        # cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
        cursor.setCharFormat(fmt)

        self.textedit.document().blockSignals(False)

    def clear(self):
        """Clear all underlines"""
        self.textedit.document().blockSignals(True)
        cursor = QTextCursor(self.textedit.document())
        cursor.select(QTextCursor.SelectionType.Document)
        format = QTextCharFormat()
        cursor.setCharFormat(format)
        self.textedit.document().blockSignals(False)

        """remove all labels"""
        for label in [lbl for lbl in self.labels]:
            label.hide()
            label.deleteLater()
        self.labels = []

    def lint(self, lineno:int, message:str, mode:LinterMode=LinterMode.UNDERLINE):
        match mode:
            case LinterMode.UNDERLINE:
                self.underline(lineno, message)
            case LinterMode.LABEL:
                self.label(lineno, message)

    def lintException(self, e:Exception, mode:LinterMode):
        import traceback
        if isinstance(e, SyntaxError):
            text = str(e.msg)
            if e.lineno:
                self.lint(e.lineno, e.msg, mode)
        else:
            tb = traceback.TracebackException.from_exception(e)
            last_frame = tb.stack[-1]
            if last_frame.lineno:
                self.lint(last_frame.lineno, str(e), mode)

if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication, QPlainTextEdit
    from qtpy.QtGui import QFont
    
    app = QApplication()
    textedit = QPlainTextEdit()
    textedit.setWindowTitle("Linter example")
    textedit.setTabStopDistance(textedit.fontMetrics().horizontalAdvance(" ")*4)
    font = textedit.font()
    font.setPointSize(12)
    font.setWeight(QFont.Weight.Medium)
    font.setStyleHint(QFont.StyleHint.TypeWriter)
    font.setFamilies(["monospace", "Operator Mono Book"])
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    textedit.setFont(font)
    textedit.resize(600,300)
    textedit.show()

    linter = TextEditLinterWidget(textedit)

    textedit.textChanged.connect(lambda: (
        linter.clear(),
        linter.underline(1, "this is an underline"),
        linter.label(2, "this is a label")
    ))
    from textwrap import dedent
    textedit.setPlainText(dedent("""\
    def hello():
        print("Hey!")
    """))
    app.exec()