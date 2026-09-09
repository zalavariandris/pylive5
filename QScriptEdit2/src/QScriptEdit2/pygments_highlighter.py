
from qtpy.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor
from pygments import lex
from pygments.lexers import PythonLexer
from pygments.styles import get_style_by_name



class PygmentsHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        self.lexer = PythonLexer()
        self.style = get_style_by_name("default")

        self.formats = {}
        for token, style in self.style:
            fmt = QTextCharFormat()
            if style['color']:
                fmt.setForeground(QColor("#" + style['color']))
            if style['bold']:
                fmt.setFontWeight(75)
            if style['italic']:
                fmt.setFontItalic(True)
            self.formats[token] = fmt

    def highlightBlock(self, text):
        for token, content in lex(text, self.lexer):
            length = len(content)
            fmt = self.formats.get(token)
            if fmt:
                self.setFormat(text.find(content), length, fmt)