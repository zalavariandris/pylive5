from qtpy.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QTextDocument
import re


class InvisiblesHighlighter(QSyntaxHighlighter):
	def __init__(self, parent: QTextDocument) -> None:
		super().__init__(parent)

		invisibles_format = QTextCharFormat()
		invisibles_format.setForeground(QColor("salmon"))

		self.highlightingRules = [
			(r"( )\1*", invisibles_format),
			(r"(\t)\1*", invisibles_format),
			(r"(\r)\1*", invisibles_format),
			(r"(\n)\1*", invisibles_format),
		]

	def highlightBlock(self, text):
		for pattern, fmt in self.highlightingRules:
			expression = re.compile(pattern)
			m = expression.search(text)
			while m is not None:
				start, end = m.span()
				self.setFormat(start, end - start, fmt)
				m = expression.search(text, end+1)