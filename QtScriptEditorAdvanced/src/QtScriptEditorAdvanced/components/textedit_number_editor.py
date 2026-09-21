from typing import cast

from qtpy.QtWidgets import QTextEdit, QPlainTextEdit, QApplication
from qtpy.QtGui import QTextCharFormat, QTextCursor, QColor
from qtpy.QtCore import Qt, QEvent, QObject, QPointF

from textwrap import dedent
import math

class TextEditNumberEditor(QObject):
    def __init__(self, textedit:QTextEdit|QPlainTextEdit):
        super().__init__(parent=textedit)
        
        self.hovered_cursor = None  # Store the currently hovered cursor
        self.default_format = QTextCharFormat()  # Store the default format
        self.highlight_format = QTextCharFormat()
        # self.highlight_format.setForeground(QColor("lightgreen"))
        self.highlight_format.setUnderlineStyle(QTextCharFormat.SingleUnderline)

        # Enable mouse tracking for the viewport
        self.dragging = False
        self.drag_start_y = None
        self.original_value = None
        self.number_cursor = None

        textedit.viewport().setMouseTracking(True)
        # Install the event filter on the viewport
        textedit.viewport().installEventFilter(self)
        self.textedit = textedit

    def getNumberCursor(self, cursor:QTextCursor)->QTextCursor|None:
        # acts like cursor.select(QTextCursor.WordUnderCursor) but includes tne '-' sign as well
        # (WordUnderCursor does not include the '-' sign.)
        word_cursor = QTextCursor(cursor)

        word_cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor) # Workaround: for some reason when i insert new number below, the cursor canot be moved back to its original location.
        word_cursor.select(QTextCursor.SelectionType.WordUnderCursor)

        word = word_cursor.selectedText()

        if word.isdigit():  # Check for digits without the negative sign
            start = word_cursor.selectionStart()
            end = word_cursor.selectionEnd()
            number_cursor = QTextCursor(word_cursor)
            number_cursor.setPosition(start-1, QTextCursor.MoveMode.MoveAnchor)
            number_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            extended_text = number_cursor.selectedText()

            if extended_text.startswith('-'):  # Check if the '-' is part of the number
                return number_cursor
            else:
                return word_cursor
        else:
            return None


    def eventFilter(self, obj, event): #type: ignore
        # The viewport receives teardown events after the editor is deleted.
        # Only mouse events need to access the editor.
        if event.type() not in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
            return False

        # Disable numeric drag editing in read-only mode.
        if self.textedit.isReadOnly():
            if self.dragging:
                self.dragging = False
                self.original_value = None
            self.clearHoverHighlight()
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
                obj.setCursor(Qt.CursorShape.IBeamCursor)
            return super().eventFilter(obj, event)

        if event.type() == QEvent.Type.MouseMove and not self.dragging:
            number_cursor = self.getNumberCursor(
                self.textedit.cursorForPosition(
                    event.position().toPoint()
                )
            )
            # if self.number_cursor:
            #     print(dedent(f"""\
            #     MOUSE HOVER MOVE
            #     position: {self.number_cursor.position()}
            #     anchor:   {self.number_cursor.anchor()}
            #     text: '{self.number_cursor.selectedText()}'

            #     """))
            # else:
            #     print(dedent(f"""\
            #     MOUSE HOVER MOVE
            #     - no number cursor -

            #     """))
            if number_cursor:
                self.applyHighlight(number_cursor)
                obj.setCursor(Qt.CursorShape.SizeHorCursor)
                self.number_cursor = number_cursor
            else:
                self.clearHoverHighlight()
                obj.setCursor(Qt.CursorShape.IBeamCursor)

        elif event.type() == QEvent.Type.MouseButtonPress:
            if self.number_cursor:
                # Start dragging
                self.dragging = True
                self.drag_start = event.position().toPoint()
                # print(dedent(f"""\
                # MOUSE PRESS
                # position: {self.number_cursor.position()}
                # anchor:   {self.number_cursor.anchor()}
                # text: '{self.number_cursor.selectedText()}'

                # """))
                self.original_value = int(self.number_cursor.selectedText())

                return False

        elif event.type() == QEvent.Type.MouseMove and self.dragging:
            assert self.original_value is not None
            if self.number_cursor:
                # Calculate drag distance and compute the new value
                mouse_delta = event.position().toPoint() - self.drag_start

                delta_value = (mouse_delta.x() - mouse_delta.y()) * abs(self.original_value or 1)//100
                new_value = self.original_value + delta_value

                # Ensure we replace the entire number
                if self.number_cursor:
                    # print(dedent(f"""\
                    # MOUSE DRAG MOVE
                    # position: {self.number_cursor.position()}
                    # anchor:   {self.number_cursor.anchor()}
                    # text: '{self.number_cursor.selectedText()}'

                    # """))
                    position= self.number_cursor.position()
                    anchor=   self.number_cursor.anchor()
                    self.number_cursor.insertText(str(new_value))  # Replace with the new value

                    # note: insert text will move the cursor to the end of the number.
                    # find the newly inserted text
                    self.number_cursor = self.getNumberCursor(self.number_cursor)
                    return True        

        elif event.type() == QEvent.Type.MouseButtonRelease and self.dragging:
            # Stop dragging
            self.dragging = False
            obj.setCursor(Qt.CursorShape.IBeamCursor)
            self.clearHoverHighlight()
            return True
        else:
            ...

        # # THIS IS FOR DEBUG ONLY !!!!!!!!!!
        # if event.type() == QEvent.Type.MouseMove:
        #     return True

        return super().eventFilter(obj, event)

    def applyHighlight(self, cursor:QTextCursor):
        """Highlight the current hovered word."""
        if self.number_cursor!=cursor:
            ...
            # self.textedit.blockSignals(True)
            # cursor.setCharFormat(self.highlight_format)
            # self.textedit.blockSignals(False)

    def clearHoverHighlight(self):
        """Remove the highlight from the previously hovered word."""
        if self.number_cursor:
            ...
            # self.textedit.blockSignals(True)
            # self.number_cursor.setCharFormat(self.default_format)
            # self.textedit.blockSignals(False)
            self.number_cursor = None


if __name__ == "__main__":
    app = QApplication([])
    editor = QTextEdit()
    editor.textChanged.connect(lambda: print("text changed!"))
    editor.setWindowTitle("Edit numbers with mouse inside a QTextEdit")
    editor.setPlainText("Hover over numbers like -40 or (10, 250) to highlight, and drag to edit them.")
    number_editor = TextEditNumberEditor(editor)
    editor.show()
    app.exec()
