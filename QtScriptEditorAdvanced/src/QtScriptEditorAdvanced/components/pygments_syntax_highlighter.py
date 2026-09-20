from qtpy.QtWidgets import QTextEdit, QApplication, QWidget, QHBoxLayout, QListWidget
from qtpy.QtGui import QColor, QFont, QFontMetricsF, QTextCharFormat, QSyntaxHighlighter, QPalette, QTextDocument


from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.style import Style
from pygments.token import Token
from pygments.styles import get_style_by_name
from pygments.formatter import Formatter


class MyFormatter(Formatter):
	""" Custom Pygments formatter for PyQt highlighting. """
	def __init__(self, color_scheme: Style):
		super().__init__()
		self.color_scheme = color_scheme
		self.formats = []

		# Build a mapping of Pygments token types to QTextCharFormat
		self.token_formats = {}
		for token, style in self.color_scheme:
			text_format = QTextCharFormat()
			if style['color']:
				text_format.setForeground(QColor(f"#{style['color']}"))
			if style['bold']:
				text_format.setFontWeight(QFont.Weight.Bold)
			if style['italic']:
				text_format.setFontItalic(True)
			if style['underline']:
				text_format.setFontUnderline(True)
			self.token_formats[token] = text_format

	def format(self, tokensource, outfile):
		""" Process tokens and store formats for later use. """
		offset = 0
		for ttype, value in tokensource:
			length = len(value)
			char_format = self.token_formats.get(ttype, QTextCharFormat())

			self.formats.append((offset, length, value, ttype, char_format))
			offset += length


import re
class PygmentsSyntaxHighlighter(QSyntaxHighlighter):
	def __init__(self, document, color_scheme: str | Style = "dracula"):
		if not isinstance(document, QTextDocument):
			raise ValueError(f"Document must be a QTextDocument, got:{document}")
			
		super().__init__(document)

		if isinstance(color_scheme, str):
			color_scheme = get_style_by_name(color_scheme)
		self.lexer = PythonLexer()
		self.color_scheme = color_scheme

		# Regex to detect whitespace
		self.whitespace_regex = re.compile(r"[ \t]+")

		# Create a QTextCharFormat for whitespace
		self.whitespace_format = QTextCharFormat()
		
		# Retrieve the comment color from the Pygments style
		pygments_comment_style = self.color_scheme.styles.get(Token.Comment, "#888888")
		whitespace_color = QColor(pygments_comment_style)
		
		# Set transparency
		whitespace_color.setAlpha(50)  # Adjust alpha value as needed
		self.whitespace_format.setForeground(whitespace_color)

	def highlightBlock(self, block_text):
		""" Apply syntax highlighting to a block of text. """
		# Create the formatter for this block
		formatter = MyFormatter(self.color_scheme)

		# Use Pygments to tokenize the text and apply formatting
		highlight(block_text, self.lexer, formatter)


		# Apply the formats calculated by the formatter
		for start, length, text, ttype, char_format in formatter.formats:
			# print(ttype)
			# print(f"'{text}'")
			# print()

			self.setFormat(start, length, char_format)

			# multiline comment highlitinf workaround, that does not work....
			# HasTripleQuotes = ttype == Token.Literal.String.Double and text in {'"""', "'''"}
			# if HasTripleQuotes or self.previousBlockState()>1:
			# 	print("multiline start")
			# 	self.setCurrentBlockState(1)

			# if self.currentBlockState()>0:
			# 	charformat = QTextCharFormat()
			# 	charformat.setForeground(QColor("green"))
			# 	self.setFormat(start, length, charformat)


			# if HasTripleQuotes and self.previousBlockState()>1:
			# 	print("multiline end")
			# 	self.setCurrentBlockState(0)

		# Handle whitespace formatting separately
		for match in self.whitespace_regex.finditer(block_text):
			start, end = match.span()
			self.setFormat(start, end - start, self.whitespace_format)


### Main Application ###
if __name__ == "__main__":
	import sys
	app = QApplication(sys.argv)

	from pygments.styles import get_all_styles

	window = QWidget()
	mainLayout = QHBoxLayout()
	window.setLayout(mainLayout)
	listwidget = QListWidget()
	for style in get_all_styles():
		listwidget.addItem(style)

	mainLayout.addWidget(listwidget)

	# Create a QTextEdit and apply the highlighter
	editor = QTextEdit()
	editor.setWindowTitle("PygmentsSyntaxHighlighter component example")
	editor.setTabStopDistance(QFontMetricsF(editor.font()).horizontalAdvance(' ') * 4)
	highlighter = PygmentsSyntaxHighlighter(editor.document())

	def set_color_scheme(style_name="dracula"):
		color_scheme = get_style_by_name(style_name)
		highlighter = PygmentsSyntaxHighlighter(editor.document(), color_scheme)
		palette = editor.palette()
		palette.setColor(QPalette.Base, QColor(f"{color_scheme.background_color}"))
		editor.setPalette(palette)

	listwidget.currentItemChanged.connect(lambda current, prev: set_color_scheme(current.text()))
	listwidget.setCurrentIndex(listwidget.model().index(10,0))
	# Set some Python code to highlight
	from textwrap import dedent
	sample_code = dedent('''
	def hello_world():
		print("Hello, World!")
		# This is a comment
		x = 42
		return x

	""" multiline
	comment
	"""
	''')
	editor.setPlainText(sample_code)

	mainLayout.addWidget(editor)
	window.show()

	sys.exit(app.exec())
