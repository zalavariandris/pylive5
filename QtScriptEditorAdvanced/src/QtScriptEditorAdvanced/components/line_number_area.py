from typing import *
try:
    from typing import override
except ImportError:
    from typing_extensions import override

from qtpy.QtWidgets import QPlainTextEdit, QWidget
from qtpy.QtGui import QPainter, QFontMetrics, QColor, QPaintEvent, QFont, QFontMetricsF, QPalette, QTextOption
from qtpy.QtCore import QRect, QRectF, Qt, QSize, Slot



class LineNumberArea(QWidget):
	def __init__(self, editor: QPlainTextEdit) -> None:
		super().__init__(parent=editor)
		self.editor = editor

		def onBlockCountChanged(newBlockCount:int):
			self.updateLineNumberAreaWidth(newBlockCount)

		editor.blockCountChanged.connect(onBlockCountChanged)

		def onUpdateRequest(rect:QRect, dy:int):
			if dy:
				self.scroll(0, dy)
			else:
				self.update(0, rect.y(), self.width(), rect.height())
			if rect.contains(editor.viewport().rect()):
				self.updateLineNumberAreaWidth(0)

		editor.updateRequest.connect(onUpdateRequest)
		self.updateLineNumberAreaWidth(0)

		self._bars = []

	def clearBars(self):
		self._bars = []
		self.update()

	def insertBar(self, first_line_no:int, last_line_no:int, color:QColor|None=None):
		if not color:
			color = self.palette().color(QPalette.ColorRole.Accent)
		self._bars.append((first_line_no, last_line_no, color))
		self.update()

	def removeBar(self, first_line_no:int, last_line_no:int):
		self._bars.remove((first_line_no, last_line_no))
		self.update()

	@override
	def sizeHint(self)->QSize:
		return QSize(self.lineNumberAreaWidth(), 0)

	def lineNumberAreaWidth(self):
		digits = 1;
		line_count = max(1, self.editor.blockCount())
		while line_count >= 10:
			line_count /= 10
			digits+=1

		space = 3 + self.fontMetrics().horizontalAdvance('9') * digits;

		return space

	@Slot(int)
	def updateLineNumberAreaWidth(self, newBlockCount:int):
		self.editor.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)
		editor_contents_rect = self.editor.contentsRect()
		self.setGeometry(QRect(
			editor_contents_rect.left(),
			editor_contents_rect.top(),
			self.lineNumberAreaWidth(),
			editor_contents_rect.height()
		))

	def paintEvent(self, event:QPaintEvent):

		self.paintBars()

		painter = QPainter(self);
		palette = self.palette()
		text_color = palette.color(QPalette.ColorRole.PlaceholderText)


		block = self.editor.firstVisibleBlock()
		block_number = block.blockNumber()
		top = round(self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top())
		bottom = top + round(self.editor.blockBoundingRect(block).height())

		while block.isValid() and top <= event.rect().bottom():
			if block.isVisible() and bottom >= event.rect().top():
				number = str(block_number + 1)
				painter.setPen(text_color)
				painter.drawText(0, top, self.width(), self.fontMetrics().height(),
								 Qt.AlignRight, number)
			
			block = block.next()
			top = bottom
			bottom = top + round(self.editor.blockBoundingRect(block).height())
			block_number += 1

		

	def paintBars(self):
		painter = QPainter(self);
		
		painter.setPen(Qt.NoPen)
		content_offset = self.editor.contentOffset()
		for begin, end, color in self._bars:
			begin_block = self.editor.document().findBlockByLineNumber(begin-1)
			end_block = self.editor.document().findBlockByLineNumber(end-1)

			begin_rect = self.editor.blockBoundingGeometry(begin_block)
			end_rect = self.editor.blockBoundingGeometry(end_block)

			color.setAlpha(128)
			painter.setBrush(color)
			painter.drawRoundedRect(QRectF(
				content_offset.x(),
				begin_rect.top()+content_offset.y()+2, 
				self.width(),
				end_rect.bottom()-begin_rect.top()-4
			), 4, 4)

class TextEditWithLineNumbers(QPlainTextEdit):
	def __init__(self, parent=None):
		super().__init__(parent)
		""" Setup Textedit """
		######################
		self.setupTextEdit()

		""" Line numbers """
		self.lineNumberArea = LineNumberArea(self)

	def setupTextEdit(self):
		self.setWindowTitle("ScriptTextEdit")
		self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
		self.setTabChangesFocus(False)
		self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(' ') * 4)

		# set a monospace font
		font = self.font()

		font.setFamilies(["monospace", "Operator Mono Book"])
		font.setPointSize(10)
		font.setWeight(QFont.Weight.Medium)
		font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
		self.setFont(font)
		
		# # show whitespace
		# options = QTextOption()
		# options.setFlags(QTextOption.ShowTabsAndSpaces)
		# self.document().setDefaultTextOption(options)

		# resize window
		width = QFontMetrics(font).horizontalAdvance('O') * 70
		self.resize(width, int(width*4/3))

	@override
	def setFont(self, font:QFont):
		super().setFont(font)
		# set tab width to 4 spaces
		self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(' ') * 4)




if __name__ == "__main__":
	import sys
	from textwrap import dedent
	# from components.WhitespaceHighlighter import WhitespaceHighlighter
	import ast

	app = QApplication(sys.argv)
	textedit = QPlainTextEdit()
	def setup_textedit(textedit):
		textedit.setWindowTitle("ScriptTextEdit")
		textedit.setWordWrapMode(QTextOption.WrapMode.NoWrap)
		textedit.setTabChangesFocus(False)
		font = textedit.font()
		font.setFamilies(["monospace"])
		font.setStyleHint(QFont.StyleHint.TypeWriter);
		font.setPointSize(12)
		font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
		textedit.setFont(font)
		textedit.setTabStopDistance(QFontMetricsF(textedit.font()).horizontalAdvance(' ') * 4)
	setup_textedit(textedit)

	textedit.setPlainText(dedent("""\
	def hello_world():
		print("Hello, World!"
		# This is a comment
		x = 42
		return x
	"""))

	lineNumberArea = LineNumberArea(textedit)
	lineNumberArea.insertBar(2,4)

	# show app
	textedit.show()

	sys.exit(app.exec())
