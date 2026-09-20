# dim tabs and spaces
# if _ShowTabsAndSpaces_ option is enabled on a QtextEdit document, this highlighter can dim those characters


from qtpy.QtWidgets import QPlainTextEdit
from qtpy.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QGuiApplication, QPalette
from qtpy.QtCore import Qt
import re

class WhitespaceHighlighter(QSyntaxHighlighter):
	def __init__(self, document):
		super().__init__(document)

		palette = QGuiApplication.palette()
		text_color = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text)
		text_color.setAlpha(20)

		# Define the format for visible whitespace (e.g., light gray color)
		self.whitespace_format = QTextCharFormat()
		self.whitespace_format.setForeground(text_color)  # Light gray
		self.invisible_format = QTextCharFormat()
		self.invisible_format.setForeground(QColor(200, 200, 200, 0))  # Light gray

		# Regex to find tabs and spaces
		self.whitespace_regex = re.compile(r'[ \t]+')

	def highlightBlock(self, text):		
		# Apply the format for tabs and spaces
		for match in self.whitespace_regex.finditer(text):
			start, end = match.span()
			self.setFormat(start, end - start, self.whitespace_format)