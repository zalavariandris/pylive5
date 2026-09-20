from qtpy.QtWidgets import QPlainTextEdit, QTextEdit
from qtpy.QtGui import QFontMetricsF, QKeyEvent, QTextCursor, QTextDocument, QTextFrame, QTextBlock, QTextOption
from qtpy.QtCore import Qt

def indent_text(text, indent="\t"):
	lines = text.split("\n")
	indented_lines = []
	for i, line in enumerate(lines):
		indented_lines.append(indent+line)

	return "\n".join(indented_lines)

def unindent_text(text, indent="\t"):
	lines = text.split("\n")
	unindented_lines = []
	for i, line in enumerate(lines):
		if line.startswith(indent):
			unindented_lines.append(line[len(indent):])
		else:
			unindented_lines.append(line)
	return "\n".join(unindented_lines)

from textwrap import dedent

def find_common_indent(text: str) -> str:
	lines = [line for line in text.splitlines() if line.strip()]  # Get non-empty lines
	if not lines:
		return ""
	
	# Find minimum indent across all non-empty lines
	common_indent = min((len(line) - len(line.lstrip())) for line in lines)
	return lines[0][:common_indent]

def toggle_comment(text, comment="# "):
	lines = text.splitlines()
	lines_mask = [len(line.strip()) > 0 for line in lines]
	non_empty_lines = [line for line, mask in zip(lines, lines_mask) if mask]
	
	if not non_empty_lines:
		return text  # Return as-is if no non-empty lines
	
	common_indent = find_common_indent("\n".join(non_empty_lines))

	all_non_empty_lines_has_comment = all(line.lstrip().startswith(comment) for line in non_empty_lines)
	
	if all_non_empty_lines_has_comment:
		# Uncomment all non-empty lines
		for i, (line, mask) in enumerate(zip(lines, lines_mask)):
			if mask and line.lstrip().startswith(comment):
				# Remove comment prefix while maintaining indentation
				lines[i] = line[:len(common_indent)] + line[len(common_indent) + len(comment):]
	else:
		# Comment all non-empty lines
		for i, (line, mask) in enumerate(zip(lines, lines_mask)):
			if mask:
				# Add comment prefix while maintaining indentation
				lines[i] = line[:len(common_indent)] + comment + line[len(common_indent):]

	return "\n".join(lines)


class ScriptCursor(QTextCursor):
	def __init__(self, source:None|QTextDocument|QTextFrame|QTextBlock|QTextCursor=None):
		if source:
			super().__init__(source)
		else:
			super().__init__()

	def toggleCommentSelection(self, comment="# "):
		atBlockStart = self.atBlockStart()
		anchor = self.anchor()
		position = self.position()
		start = self.selectionStart()
		end = self.selectionEnd()

		if True: #self.hasSelection():# and len(self.selection().toPlainText().split("\n")) > 1:
			self.beginEditBlock()

			# extend selection to lines
			self.setPosition(start, QTextCursor.MoveMode.MoveAnchor)
			self.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor)
			self.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
			self.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
			lines_start = self.selectionStart()
			lines_end = self.selectionEnd()
			startOffset = start - lines_start
			endOffset = end - lines_end

			# Replace the selected text with the indented text
			text = self.selection().toPlainText()
			
			commented_text = toggle_comment(text, comment="# ")
			self.insertText(commented_text)

			# Calculate the new start and end positions after insert
			if len(commented_text) > len(text):
				new_start = lines_start + len(comment) + startOffset if not atBlockStart else lines_start
				new_end = lines_start + len(commented_text) + endOffset
			else:
				new_start = lines_start - len(text.split("\n")[0]) + len(commented_text.split("\n")[0]) + startOffset if not atBlockStart else lines_start
				new_end = lines_start + len(commented_text) + endOffset

			if anchor<position:
				self.setPosition(new_start, QTextCursor.MoveMode.MoveAnchor)
				self.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
			else:
				self.setPosition(new_end, QTextCursor.MoveMode.MoveAnchor)
				self.setPosition(new_start, QTextCursor.MoveMode.KeepAnchor)
			self.endEditBlock()

	def indentSelection(self, indentation="\t"):
		atBlockStart = self.atBlockStart()
		anchor = self.anchor()
		position = self.position()
		start = self.selectionStart()
		end = self.selectionEnd()

		if True: #self.hasSelection() and len(self.selection().toPlainText().split("\n")) > 1:
			self.beginEditBlock()

			# extend selection to lines
			self.setPosition(start, QTextCursor.MoveMode.MoveAnchor)
			self.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor)
			self.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
			self.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
			lines_start = self.selectionStart()
			lines_end = self.selectionEnd()
			startOffset = start - lines_start
			endOffset = end - lines_end

			# Replace the selected text with the indented text
			text = self.selection().toPlainText()
			

			indented_text = indent_text(text)
			self.insertText(indented_text)

			# Calculate the new start and end positions after indentation
			new_start = lines_start + len(indentation) + startOffset if not atBlockStart else lines_start  # +4 for added indentation
			new_end = lines_start + len(indented_text) + endOffset

			if anchor<position:
				self.setPosition(new_start, QTextCursor.MoveMode.MoveAnchor)
				self.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
			else:
				self.setPosition(new_end, QTextCursor.MoveMode.MoveAnchor)
				self.setPosition(new_start, QTextCursor.MoveMode.KeepAnchor)
			self.endEditBlock()
			# textEdit.setTextCursor(cursor)  # Set the cursor to the modified one

	def unindentSelection(self, indentation="\t"):
		atBlockStart = self.atBlockStart()
		anchor = self.anchor()
		position = self.position()
		start = self.selectionStart()
		end = self.selectionEnd()

		if True: #self.hasSelection() and len(self.selection().toPlainText().split("\n")) > 1:
			self.beginEditBlock()

			# extend selection to lines
			self.setPosition(start, QTextCursor.MoveMode.MoveAnchor)
			self.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor)
			self.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
			self.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
			lines_start = self.selectionStart()
			lines_end = self.selectionEnd()
			startOffset = start - lines_start
			endOffset = end - lines_end

			# Replace the selected text with the indented text
			text = self.selection().toPlainText()
			lines = text.split("\n")

			unindented_text = unindent_text(text)
			self.insertText(unindented_text)

			# Calculate the new start and end positions after indentation
			new_start = lines_start - len(text.split("\n")[0]) + len(unindented_text.split("\n")[0]) + startOffset if not atBlockStart else lines_start
			new_end = lines_start + len(unindented_text) + endOffset

			if anchor<position:
				self.setPosition(new_start, QTextCursor.MoveMode.MoveAnchor)
				self.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
			else:
				self.setPosition(new_end, QTextCursor.MoveMode.MoveAnchor)
				self.setPosition(new_start, QTextCursor.MoveMode.KeepAnchor)
			self.endEditBlock()
			# self.setTextCursor(cursor)  # Set the cursor to the modified one

	def insertNewLine(self, indentation="\t"):
		# print("inser")
		original = QTextCursor(self)
		# select from line start adn retrive indentation
		self.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor)
		self.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
		line = self.selection().toPlainText()

		current_line_indentation = line[:-len(line.lstrip())] if line.lstrip() else line

		# reset selection
		self.setPosition(original.anchor(), QTextCursor.MoveMode.MoveAnchor)
		self.setPosition(original.position(), QTextCursor.MoveMode.KeepAnchor)

		# insert new line with indentation
		new_line_indentation = current_line_indentation
		if line and line[-1] in ":({[":
			new_line_indentation+=indentation
		self.insertText("\n"+new_line_indentation)



if __name__ == "__main__":
	class ScriptTextEdit(QPlainTextEdit):
		def __init__(self, parent=None):
			super().__init__(parent)
			self.setWindowTitle("ScriptTextEdit")
			self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
			self.setTabChangesFocus(False)
			self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(' ') * 4)

		def scriptCursor(self) -> ScriptCursor:
			return ScriptCursor(super().textCursor())

		def setFont(self, font):
			super().setFont(font)
			self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(' ') * 4)

		def keyPressEvent(self, e: QKeyEvent) -> None:
			cursor = self.textCursor()
			if e.key() == Qt.Key.Key_Tab:
				if cursor.hasSelection() and len(cursor.selection().toPlainText().split("\n")) > 1:
					self.indentSelection()
				else:
					cursor.insertText('\t')
			elif e.key() == Qt.Key.Key_Backtab:  # Shift + Tab
				if cursor.hasSelection() and len(cursor.selection().toPlainText().split("\n")) > 1:
					self.unindentSelection()
			elif e.key() == Qt.Key.Key_Slash and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
				self.toggleCommentSelection()
			elif e.key() == Qt.Key.Key_Return or Qt.Key.Key_Enter:
				self.scriptCursor().insertNewLine()
			else:
				super().keyPressEvent(e)

		def textCursor(self) -> QTextCursor:
			return QTextCursor(super().textCursor())

		def toggleCommentSelection(self):
			cursor = self.scriptCursor()
			cursor.toggleCommentSelection(comment="# ")
			self.setTextCursor(cursor)

		def indentSelection(self):
			cursor = self.scriptCursor()
			cursor.indentSelection()
			self.setTextCursor(cursor)

		def unindentSelection(self):
			cursor = self.scriptCursor()
			cursor.unindentSelection()
			self.setTextCursor(cursor)


	import sys
	from textwrap import dedent
	from pylive.QtScriptEditor.components.WhitespaceHighlighter import WhitespaceHighlighter

	app = QApplication(sys.argv)
	window = ScriptTextEdit()

	font = QFont("Operator Mono", 14)
	window.setFont(font)
	width = QFontMetrics(font).horizontalAdvance('O') * 70
	window.resize(width, int(width*4/3))

	# show whitespace characters
	option = QTextOption(window.document().defaultTextOption())
	option.setFlags(QTextOption.Flag.ShowTabsAndSpaces)
	window.document().setDefaultTextOption(option)

	# Dim whitespace characters
	WhitespaceHighlighter(window.document())
	
	window.setPlainText(dedent("""\
	class Person:
		def __init__(self, name:str):
			self.name = name

		def say(self):
			print(self.name)

	peti = Person()
	"""))

	# show app
	window.show()
	sys.exit(app.exec())
