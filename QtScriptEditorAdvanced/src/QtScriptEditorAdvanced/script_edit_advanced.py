from typing import *

from qtpy.QtCore import Qt, QEvent
from qtpy.QtGui import QColor, QContextMenuEvent, QKeyEvent, QPalette, QFont, QTextOption
from qtpy.QtWidgets import QPlainTextEdit
import re

# components
from .components.pygments_syntax_highlighter import PygmentsSyntaxHighlighter
from .components.simple_python_highlighter import SimplePythonHighlighter
from .components.script_cursor import ScriptCursor
from .components.textedit_number_editor import TextEditNumberEditor

# code assist
import rope.base.project
from rope.contrib import codeassist

from .components.jedi_completer import JediCompleter
from .components.async_jedi_completer import AsyncJediCompleter
from .components.textedit_completer import PythonKeywordsCompleter
from .components.linter_widget import TextEditLinterWidget
from .components.line_number_area import LineNumberArea
from .cell_support import Cell, split_cells, cell_at_line



class ScriptEditAdvanced(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        ### Font###
        font = self.font()
        font.setFamilies(["monospace", "Operator Mono Book"])
        # font.setPointSize(10)
        font.setWeight(QFont.Weight.Medium)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.setFont(font)

        ### TextEdit Behaviour ###
        self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.setTabChangesFocus(False)
        self._indent_using_spaces = True
        self._tabsize = 4
        self.setTabSize(4)
        
        ### script typing behaviour ###
        self.installEventFilter(self)

        """ line numbers """
        self.lineNumberArea = LineNumberArea(self)

        """ Syntax Highlighter """
        options = self.document().defaultTextOption() 
        options.setFlags(QTextOption.Flag.ShowTabsAndSpaces)
        self.document().setDefaultTextOption(options)
        self.highlighter = PygmentsSyntaxHighlighter(self.document())
        blue3 = QColor.fromHsl(210, 15*255//100, 22*255//100)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, blue3)  # Light yellow color
        self.setPalette(palette)

        # ### Autocomplete ###
        self.completer = PythonKeywordsCompleter(self)

        # ### Linter ###e
        self.linter = TextEditLinterWidget(self)

        ### Setup Textedit ###
        self.setWindowTitle("ScriptTextEdit")

        ### Edit Numbers ###
        self.number_editor = TextEditNumberEditor(self)

    # def sizeHint(self) -> QSize:
    #     width = self.fontMetrics().horizontalAdvance('O') * 70
    #     return QSize(width, int(width*8/7))

    def contextMenuEvent(self, e: QContextMenuEvent|None):
        print("Context menu event triggered")
        from pylive.declerative_qt import (
            createWidget, createAction, createMenu, createSeparator
        )
        edit_menu = createMenu("Line", [
            createAction(
                "Toggle Comment", lambda: self.toggleComment()
            ),
            createSeparator(),
            createAction(
                "Indent", lambda: self.indent()
            ),
            createAction(
                "Unindent", lambda: self.unindent()
            ),
        ])

        indent_using_spaces_action = QAction("Indent Using Spaces")
        indent_using_spaces_action.setCheckable(True)
        indent_using_spaces_action.setChecked(self.indentUsingSpaces())
        indent_using_spaces_action.toggled.connect(
            lambda: self.setIndentUsingSpaces(indent_using_spaces_action.isChecked())
        )
        indentation_menu = createMenu("Indentation", 
            [
                createAction(
                    "Convert Indentation to Tabs", 
                    lambda: self.convertIndentationToTabs()
                ),
                createAction(
                    "Convert Indentation to Spaces", 
                    lambda: self.convertIndentationToSpaces()
                ),
                createAction("Guess from text (not implemented yet)")
            ]
            +[createSeparator()]+
            [
                createAction(
                    f"TabWidth: {i}",
                    lambda i=i: self.setTabSize(i)
                ) for i in range(1,9)
            ]
            +[createSeparator()]+
            [indent_using_spaces_action]
        )

        if menu := self.createStandardContextMenu():
            menu.addMenu(edit_menu)
            menu.addMenu(indentation_menu)
            menu.exec(e.globalPos());
            del menu # i am not sure if we need this here in python

    ### TEXT EDITING ###
    def indentUsingSpaces(self):
        return self._indent_using_spaces

    def setIndentUsingSpaces(self, indentUsingSpaces:bool):
        self._indent_using_spaces = indentUsingSpaces

    def tabSize(self):
        return self._tabsize

    def setTabSize(self, tabsize:int):
        self._tabsize = tabsize
        spacesize = self.fontMetrics().horizontalAdvance(' ')
        self.setTabStopDistance(spacesize * tabsize)
    
    def convertIndentationToTabs(self):
        text = self.toPlainText()
        text = text.replace(" "*self.tabSize(), "\t")
        self.setPlainText(text)
        self.setIndentUsingSpaces(False)

    def convertIndentationToSpaces(self):
        text = self.toPlainText()
        text = text.replace("\t", " "*self.tabSize())
        self.setPlainText(text)
        self.setIndentUsingSpaces(True)

    def toggleComment(self):
        cursor = ScriptCursor(self.textCursor())
        cursor.toggleCommentSelection(comment="# ")
        self.setTextCursor(cursor)

    def indent(self):
        cursor = ScriptCursor(self.textCursor())
        cursor.indentSelection()
        self.setTextCursor(cursor)

    def unindent(self):
        cursor = ScriptCursor(self.textCursor())
        cursor.unindentSelection()
        self.setTextCursor(cursor)
        
    ### Script Cursor ###
    def eventFilter(self, o: QObject, e: QEvent) -> bool: #type: ignore
        if self.isReadOnly():
            return super().eventFilter(o, e)
        
        if e.type() == QEvent.Type.KeyPress:
            cursor = ScriptCursor(self.textCursor())
            e = cast(QKeyEvent, e)
            editor = self
            if e.key() == Qt.Key.Key_Tab:
                if cursor.hasSelection() and len(cursor.selection().toPlainText().split("\n")) > 1:
                    cursor.indentSelection()
                    editor.setTextCursor(cursor)
                    return True
                else:
                    if self.indentUsingSpaces():
                        cursor.insertText(" "*self.tabSize())
                    else:
                        cursor.insertText("\t")
                    return True

            elif e.key() == Qt.Key.Key_Backtab:  # Shift + Tab
                if cursor.hasSelection() and len(cursor.selection().toPlainText().split("\n")) > 1:
                    cursor.unindentSelection()
                    editor.setTextCursor(cursor)
                    return True

            elif e.key() == Qt.Key.Key_Slash and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
                cursor.toggleCommentSelection(comment="# ")
                editor.setTextCursor(cursor)
                return True

            elif e.key() == Qt.Key.Key_Return:
                cursor.insertNewLine(indentation=" "*self.tabSize() if self.indentUsingSpaces() else "\t")
                cursor.MoveMode
                return True

        return super().eventFilter(o, e)




def main():
    from textwrap import dedent
    from qtpy.QtWidgets import QApplication
    app = QApplication([])
    editor = ScriptEditAdvanced()
    editor.setReadOnly(False)
    
    editor.setPlainText(dedent("""\
    def hello_world():
        print("Hello, World!")
        # This is a comment
        x = 42
        return x
    """))

    # def validate_script(script:str):
    #     import ast
    #     try:
    #         editor.linter.clear()
    #         ast.parse(script)
    #     except SyntaxError as e:
    #         editor.linter.lintException(e, 'underline')
    #     except Exception as e:
    #         editor.linter.lintException(e, 'label')

    # editor.textChanged.connect(lambda: 
    #     validate_script(editor.toPlainText()))


    editor.show()
    app.exec()


if __name__ == "__main__":
    main()
