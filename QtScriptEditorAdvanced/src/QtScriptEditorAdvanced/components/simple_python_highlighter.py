from qtpy.QtWidgets import QPlainTextEdit, QApplication
from qtpy.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QTextCharFormat, QSyntaxHighlighter, QTextOption
from qtpy.QtCore import QRegularExpression

def complement(color:QColor):
	h, s, l, a = color.getHsl()
	return QColor.fromHsl((h+180)%360, s, l, a)

def shift(color:QColor, offset=180):
	h, s, l, a = color.getHsl()
	return QColor.fromHsl((h+offset)%360, s, l, a)

def dim(color:QColor, a=128):
	r,g,b,_ = color.getRgb()
	return QColor.fromRgb( r,g,b,a )


class SimplePythonHighlighter(QSyntaxHighlighter):
	def __init__(self, document):
		super().__init__(document)
		palette = QGuiApplication.palette()

		# Define text formats for different token types
		highlightColor = complement(palette.color(QPalette.ColorRole.Highlight))
		self.keyword_format = QTextCharFormat()
		self.keyword_format.setForeground(highlightColor)
		self.keyword_format.setFontItalic(True)
		self.keyword_format.setFontWeight(QFont.Weight.Bold)

		string_color = QColor("darkGreen")
		self.string_format = QTextCharFormat()
		self.string_format.setForeground(string_color)

		comment_color = dim( palette.color(QPalette.ColorRole.Text), 150 )
		
		self.comment_format = QTextCharFormat()
		self.comment_format.setForeground(comment_color)
		self.comment_format.setFontItalic(False)

		numbers_color = QColor("darkGreen")
		self.number_format = QTextCharFormat()
		self.number_format.setForeground(numbers_color)

		operator_color = QColor('green')
		self.operator_format = QTextCharFormat()
		self.operator_format.setForeground(operator_color)

		function_name_color = QColor("darkcyan")
		self.function_format = QTextCharFormat()
		self.function_format.setForeground(function_name_color)

		# Define Python keywords
		keywords = [
			"and", "as", "assert", "break", "class", "continue", 
			"def", "del", "elif", "else", "except", "False", 
			"finally", "for", "from", "global", "if", "import", 
			"in", "is", "lambda", "None", "nonlocal", "not", 
			"or", "pass", "raise", "return", "True", "try", 
			"while", "with", "yield"
		]
		keyword_pattern = '|'.join([r'\b' + word + r'\b' for word in keywords])

		# Store regex patterns for different token types
		self.rules = [
			(QRegularExpression(keyword_pattern),	self.keyword_format,	0),	# Keywords
			(QRegularExpression(r'#.*'),			self.comment_format,	0),	# Python comments
			(QRegularExpression(r'\".*\"'),			self.string_format,		0),	# Simple string pattern
			(QRegularExpression(r'\'.*\''),			self.string_format,		0),	# Single quote strings
			(QRegularExpression(r'\b[0-9]+\b'),		self.number_format,		0),	# Numbers
			(QRegularExpression(r'[+\-*/%&|^=<>!]+'), 	self.operator_format, 0),  # Operators
			(QRegularExpression(r'\b(\w+)\s*\('),	self.function_format,	1)	# Functions
		]

	def highlightBlock(self, text):
		"""Applies syntax highlighting to a block of text."""
		# Apply all rules to the text
		for pattern, text_format, group in self.rules:
			expression = pattern.globalMatch(text)
			while expression.hasNext():
				match = expression.next()
				start = match.capturedStart(group)
				length = match.capturedLength(group)
				self.setFormat(start, length, text_format)

		# Handle multi-line strings (triple quotes)
		self.highlight_multiline_strings(text)

	def highlight_multiline_strings(self, text):
		"""Handles highlighting for multi-line strings."""
		string_start_expr = QRegularExpression('\"\"\"|\'\'\'')  # Triple-quote start
		string_end_expr = QRegularExpression('\"\"\"|\'\'\'')    # Triple-quote end

		# Check if the block is within a string
		if self.previousBlockState() == 1:
			start_index = 0
		else:
			start_index = text.find(string_start_expr.pattern())

		while start_index >= 0:
			match = string_end_expr.match(text, start_index)
			if match.hasMatch():
				end_index = match.capturedEnd()
				length = end_index - start_index
				self.setFormat(start_index, length, self.string_format)
				start_index = text.find(string_start_expr.pattern(), end_index)
				self.setCurrentBlockState(0)
			else:
				# No end found, highlight until the end of the block
				self.setFormat(start_index, len(text) - start_index, self.string_format)
				self.setCurrentBlockState(1)
				break

if __name__ == '__main__':
	import sys
	app = QApplication(sys.argv)

	editor = QPlainTextEdit()
	editor.setWindowTitle("Symple Python Syntax Highlighter Example")
	editor.resize(450, 600)
	editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap);
	editor.setFont(QFont("Operator Mono", 10))
	editor.setTabChangesFocus(False)
	editor.setTabStopDistance(QFontMetricsF(editor.font()).horizontalAdvance(' ') * 4)
	editor.setWordWrapMode(QTextOption.WrapMode.NoWrap)
	highlighter = SimplePythonHighlighter(editor.document())

	from textwrap import dedent
	editor.setPlainText(dedent('''\
	# This is a Python example
	def foo():
		if True:
			x = -55
			print(f"Hello, World! {x}")  # This is a comment
	'''))
	editor.show()
	sys.exit(app.exec())
