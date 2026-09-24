from typing import *

from qtpy.QtCore import Qt, QEvent
from qtpy.QtGui import QColor, QContextMenuEvent, QKeyEvent, QPalette, QFont, QTextOption
from qtpy.QtWidgets import QMenu, QPlainTextEdit, QAction
from qtpy.QtWidgets import QGraphicsOpacityEffect

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
from .components.python_keywords_completer import PythonKeywordsCompleter
from .components.linter_widget import TextEditLinterWidget
from .components.line_number_area import LineNumberArea
from .cell_support import Cell, split_cells, cell_at_line



class ScriptEditAdvanced(QPlainTextEdit):
    def __init__(self, 
                 highlighter=PygmentsSyntaxHighlighter, 
                 completer:Type[AsyncJediCompleter]|Type[PythonKeywordsCompleter]|None=AsyncJediCompleter, 
                 parent=None
                ):
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

        ### Setup Textedit ###
        self.setWindowTitle("ScriptTextEdit")
        
        ### script typing behaviour ###
        self.installEventFilter(self)

        ### TextEdit Options ###
        options = self.document().defaultTextOption() 
        options.setFlags(QTextOption.Flag.ShowTabsAndSpaces)
        self.document().setDefaultTextOption(options)
        blue3 = QColor.fromHsl(210, 15*255//100, 22*255//100)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, blue3)  # Light yellow color
        self.setPalette(palette)

        ### line numbers ###
        self.lineNumberArea = LineNumberArea(self)

        ### Syntax Highlighter ###
        
        self._highlighter = highlighter(self.document())

        # ### Autocomplete ###
        if completer is not None:
            self._completer = completer(self)
        else:
            self._completer = None

        ### Linter ###
        self._linter = TextEditLinterWidget(self)

        ### Edit Numbers ###
        self.number_editor = TextEditNumberEditor(self)

        ### dim effect ###
        self._dim_effect = QGraphicsOpacityEffect(self)
        self._dim_effect.setOpacity(0.75)
        self._dim_effect.setEnabled(not self.isEnabled())
        self.setGraphicsEffect(self._dim_effect)

    # def sizeHint(self) -> QSize:
    #     width = self.fontMetrics().horizontalAdvance('O') * 70
    #     return QSize(width, int(width*8/7))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)

        if event.type() == QEvent.Type.EnabledChange:
            effect = self.graphicsEffect()
            if effect is not None:
                effect.setEnabled(not self.isEnabled())

    def contextMenuEvent(self, e: QContextMenuEvent|None):
        edit_menu = QMenu("Edit", self)
        edit_menu.addAction("Toggle Comment", lambda: self.toggleComment())
        edit_menu.addSeparator()
        edit_menu.addAction("Indent", lambda: self.indent())
        edit_menu.addAction("Unindent", lambda: self.unindent())

        indent_using_spaces_action = QAction("Indent Using Spaces")
        indent_using_spaces_action.setCheckable(True)
        indent_using_spaces_action.setChecked(self.indentUsingSpaces())
        indent_using_spaces_action.toggled.connect(
            lambda: self.setIndentUsingSpaces(indent_using_spaces_action.isChecked())
        )
        
        indentation_menu = QMenu("Indentation", self)
        indentation_menu.addAction("Convert Indentation to Tabs", lambda: self.convertIndentationToTabs())
        indentation_menu.addAction("Convert Indentation to Spaces", lambda: self.convertIndentationToSpaces())
        indentation_menu.addAction("Guess from text (not implemented yet)")
        indentation_menu.addSeparator()
        for i in range(1, 9):
            indentation_menu.addAction(f"TabWidth: {i}", lambda i=i: self.setTabSize(i))
        indentation_menu.addSeparator()
        indentation_menu.addAction(indent_using_spaces_action)

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

    def validate_script(script:str):
        import ast
        try:
            editor._linter.clear()
            ast.parse(script)
        except SyntaxError as e:
            editor._linter.lintException(e, 'underline')
        except Exception as e:
            editor._linter.lintException(e, 'label')

    editor.textChanged.connect(lambda: 
        validate_script(editor.toPlainText()))


    editor.show()
    app.exec()


if __name__ == "__main__":
    main()
