from qtpy.QtCore import QStringListModel, Qt, QEvent, QObject, QTimer
from qtpy.QtGui import QKeyEvent, QTextCursor
from qtpy.QtWidgets import QCompleter, QPlainTextEdit, QLineEdit
from typing import List, cast

import weakref
import re

# from traitlets.utils import text
class TextEditCompleter(QCompleter):
	def __init__(self, textedit:QPlainTextEdit|QLineEdit, words:List[str]=[]):
		super().__init__(words, parent=textedit)
		self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
		self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
		self.text_edit = weakref.ref(textedit)

		self.setWidget(textedit)
		self.activated.connect(self.insertCompletion)

		if isinstance(self.widget(), QLineEdit):
			"""
			the QComleter behaviour will insert text into a QLineEdit, before pressing Enter
			here we are disconnecting that default behavour to replace with our own.
			"""
			self.popup().selectionModel().selectionChanged.disconnect()

		# Install event filter on the text edit
		textedit.installEventFilter(self)
			
		# update built-in Filter when typing, or cursor position has changed
		textedit.textChanged.connect(lambda: (
			self.popup().hide(), 
			self.requestCompletions()
		))

		# Use QTimer to show popup notes: this is both a 'feature' and a workaround.
		# - Feature: Because now we can easily delay the popup visibility, which could be less distracting for some users.
		# - Workaround: Because the initial selection cannot be set immediately after the modelReset signal emits - for some reason. TODO: Figure out why.
		self.timer = QTimer()
		self.timer.setSingleShot(True)
		self.timer.timeout.connect(lambda: self.updatePopupVisibility())

		self.completionModel().modelReset.connect(lambda: (
			self.timer.stop(),
			self.timer.start(0)
		))

	def closeEvent(self):
		print("CloseEvent")

	def requestCompletions(self):
		"""this will be called, when the textedit wants completions
		set the model string or the completion prefix to trigger an update
		"""
		self.setCompletionPrefix(self.getWordUntilCursor())

	def insertCompletion(self, completion:str):
		"""
		Replace "WordUnderCursor" with completion
		"""
		match self.widget():
			case QPlainTextEdit():
				textedit = cast(QPlainTextEdit, self.widget())
				tc = textedit.textCursor()
				tc.select(QTextCursor.SelectionType.WordUnderCursor)
				# extra = len(completion) - len(tc.selectedText())
				# tc.movePosition(QTextCursor.MoveOperation.Left)
				# tc.movePosition(QTextCursor.MoveOperation.EndOfWord)
				tc.insertText(completion)
				textedit.setTextCursor(tc)
			case QLineEdit():
				lineedit = cast(QLineEdit, self.widget())
				word_pattern = r"[^\W_]+(?:'[^\W_]+)?"
				# Use regex to replace the last word
				modified_text = re.sub(rf"{word_pattern}(\s*)$", rf"{completion}\1", lineedit.text())
				lineedit.setText(modified_text)

	def getWordUntilCursor(self):
		"""
		Returns the word under the cursor in the QTextEdit.
		"""
		match self.widget():
			case QPlainTextEdit():
				textedit = cast(QPlainTextEdit, self.widget())
				cursor = textedit.textCursor()
				original_position = cursor.position()
				original_anchor = cursor.anchor()
				cursor.select(QTextCursor.SelectionType.WordUnderCursor)
				cursor.setPosition(cursor.anchor(), QTextCursor.MoveMode.MoveAnchor)
				cursor.setPosition(original_position, QTextCursor.MoveMode.KeepAnchor)
				return cursor.selectedText()
			case QLineEdit():
				lineedit = cast(QLineEdit, self.widget())
				
				# Get the current text and cursor position
				text = lineedit.text()
				cursor_pos = lineedit.cursorPosition()

				# Find all words and their spans (start and end positions)
				word_pattern = r"[^\W_]+(?:'[^\W_]+)?"  # Matches sequences of alphanumeric characters and apostrophes
				matches = [(m.group(), m.start(), m.end()) for m in re.finditer(word_pattern, text)]

				# Determine which word the cursor is in
				for word, start, end in matches:
					if start <= cursor_pos <= end:
						return word
				return ""

	def eventFilter(self, o:QObject, e:QEvent):
		"""
		Filters events for the QTextEdit and the completer popup.
		"""
		# if e.type() == QEvent.Type.KeyRelease:
		# 	print(f"text under cursor: '{self.textUnderCursor()}'")

		#superclass already installed an eventfilter on the popup() ListView
		if e.type() == QEvent.Type.KeyPress:
			e = cast(QKeyEvent, e)
			# print("currentCompletion:", self.currentCompletion())
			if o is self.text_edit or o is self.popup():
				# Handle key events for autocompletion
				
				if e.key() in {Qt.Key.Key_Enter, Qt.Key.Key_Return} and self.popup().isVisible():
					# Get the currently selected completion from the popup
					current_index = self.popup().currentIndex()
					selected_completion = self.completionModel().data(current_index, Qt.ItemDataRole.DisplayRole)
					if selected_completion:
						success = self.insertCompletion(selected_completion)
					self.popup().hide()
					return True
				elif e.key() == Qt.Key.Key_Escape and self.popup().isVisible():
					# print("Escape pressed")
					self.popup().hide()
					return True
				elif e.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down} and self.popup().isVisible():
					# Let the popup handle up/down keys for selection
					return False



		# 	self.popup().hide()
		# 	e = cast(QKeyEvent, e)
		# 	if e.key() in {Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape}:
		# 		return True

		# 	if e.text():
		# 		self.requestCompletions()

		return super().eventFilter(o, e)

	def updatePopupVisibility(self):
		"""
		Updates the completion prefix and shows the popup if necessary.
		"""
		# prefix = self.textUnderCursor()

		def IsLineEmpty():
			match self.widget():
				case QPlainTextEdit():
					textedit = cast(QPlainTextEdit, self.widget())
					cursor = textedit.textCursor()
					return len(cursor.block().text().strip())==0
				case QLineEdit():
					lineedit = cast(QLineEdit, self.widget())
					return lineedit.text().strip()==0


		if not IsLineEmpty() and self.getWordUntilCursor() != self.currentCompletion():
			popup = self.popup()

			popup.setCurrentIndex(self.completionModel().index(0, 0))

			# Calculate the required width for the popup
			def popup_width():
				model = self.completionModel()
				max_width = 0
				for i in range(model.rowCount()):
					text = model.data(model.index(i, 0), Qt.ItemDataRole.DisplayRole)
					width = popup.fontMetrics().horizontalAdvance(text)
					max_width = max(max_width, width)
				
				# Add padding for the scrollbar and item margins
				scrollbar_width = popup.verticalScrollBar().sizeHint().width()
				item_margin = 5  # Adjust this value based on your styling
				return max_width + scrollbar_width + 2 * item_margin

			# Ensure the popup isn't too narrow or too wide
			total_width = popup_width()
			min_width = 5
			max_width = self.widget().width()
			total_width = max(min_width, min(total_width, max_width))
			
			# popup with proper geometry
			match self.widget():
				case QPlainTextEdit():
					textedit = cast(QPlainTextEdit, self.widget())
					rect = textedit.cursorRect()
					rect.setWidth(total_width)
					self.complete(rect)
				case QLineEdit():
					textedit = cast(QLineEdit, self.widget())
					rect = textedit.cursorRect()
					rect.setWidth(total_width)
					self.complete(rect)

		else:
			self.popup().hide()


class PythonKeywordsCompleter(TextEditCompleter):
	def __init__(self, textedit:QPlainTextEdit|QLineEdit, additional_keywords=[]) -> None:
		keywords_list = [
			"and", "as", "assert", "break", "class", "continue", 
			"def", "del", "elif", "else", "except", "False", 
			"finally", "for", "from", "global", "if", "import", 
			"in", "is", "lambda", "None", "nonlocal", "not", 
			"or", "pass", "raise", "return", "True", "try", 
			"while", "with", "yield"
		]

		builtins_list = [
			"abs", "aiter", "all", "anext", "any", "ascii",
			"bin", "bool", "breakpoint", "bytearray", "bytes",
			"callable", "chr", "classmethod", "compile", "complex",
			"delattr", "dict", "dir", "divmod",
			"enumerate", "eval", "exec",
			"filter", "float", "format", "frozenset",
			"getattr", "globals",
			"hasattr", "hash", "help", "hex",
			"id", "input", "int", "isinstance", "issubclass", "iter",
			"len", "list", "locals",
			"map", "max", "memoryview", "min",
			"next",
			"object", "oct", "open", "ord",
			"pow", "print", "property",
			"range", "repr", "reversed", "round",
			"set", "setattr", "slice", "sorted", "staticmethod", "str", "sum", "super",
			"tuple", "type",
			"vars",
			"zip"
		]
		
		super().__init__(textedit)
		self.setModel(QStringListModel(keywords_list + builtins_list))


if __name__ == "__main__":
	from qtpy import QtWidgets
	from qtpy.QtWidgets import QApplication, QWidget, QHBoxLayout, QPlainTextEdit, QLineEdit
	
	#create app
	app = QApplication([])

	fruits = ["apple", "ananas", "banana", "cherry", "date", "elderberry", "fig", "grape", "honeydew", "kiwi", "lemon"]

	# create main window window
	window = QWidget()
	layout = QHBoxLayout()
	window.setLayout(layout)

	# create completing editor
	editor = QPlainTextEdit()
	editor_completer = PythonKeywordsCompleter(editor, fruits)
	editor.setWindowTitle("QTextEdit with Custom Completer")
	words = [editor_completer.model().index(row,0).data() for row in range(editor_completer.model().rowCount())]
	editor.setPlaceholderText("Start typing...\n\neg.: " + ", ".join(words))
	layout.addWidget(editor)

	# create completin lineedit
	lineedit = QLineEdit()
	lineedit.setPlaceholderText("Start typing fruits...")
	lineedit_completer = TextEditCompleter(lineedit, fruits)
	lineedit.setCompleter(lineedit_completer)
	lineedit_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
	layout.addWidget(lineedit)

	lineedit2 = QLineEdit()
	completer = QCompleter(fruits)
	lineedit2.setCompleter(completer)
	layout.addWidget(lineedit2)

	#run app
	window.show()
	app.exec()
