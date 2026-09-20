from qtpy.QtCore import Qt, QStringListModel
from qtpy.QtGui import QTextCursor
from qtpy.QtWidgets import QPlainTextEdit, QTextEdit, QApplication
from typing import *

from .textedit_completer import TextEditCompleter

import rope.base.project
from rope.base import libutils
import rope.base.project
from rope.contrib import codeassist
import rope

class RopeCompleter(TextEditCompleter):
	def __init__(self, textedit: QTextEdit|QPlainTextEdit, rope_project):
		super().__init__(textedit)
		self.rope_project = rope_project

	@override
	def requestCompletions(self):
		textedit = cast(QPlainTextEdit, self.widget())
		source_code = textedit.toPlainText()
		offset = textedit.textCursor().position()

		try:
			proposals = codeassist.code_assist(
				self.rope_project, 
				source_code=source_code, 
				offset=offset,
				maxfixes=10
			)

			proposals = codeassist.sorted_proposals(proposals) # Sorting proposals; for changing the order see pydoc
			starting_offset = codeassist.starting_offset(source_code, offset)

			# update proposals
			string_list_model = cast(QStringListModel, self.model())
			string_list_model.setStringList([proposal.name for proposal in proposals])
		except (SyntaxError, TabError, IndentationError):
			string_list_model = cast(QStringListModel, self.model())
			string_list_model.setStringList([])
		except (rope.base.exceptions.RopeError):
			string_list_model = cast(QStringListModel, self.model())
			string_list_model.setStringList([])
		except Exception as e:
			print(f"Handle these kind of errors in requestCompletions: {e.__class__}")

	@override
	def insertCompletion(self, completion):
		"""
		Inserts the selected completion into the text at the cursor position.
		"""
		textedit = cast(QPlainTextEdit, self.widget())
		tc = textedit.textCursor()
		tc.select(QTextCursor.SelectionType.WordUnderCursor)
		extra = len(completion) - len(tc.selectedText())
		tc.movePosition(QTextCursor.MoveOperation.Left)
		tc.movePosition(QTextCursor.MoveOperation.EndOfWord)
		tc.insertText(completion[-extra:])
		textedit.setTextCursor(tc)


if __name__ == "__main__":
	#create app
	app = QApplication([])

	# create completing editor
	editor = QTextEdit()
	rope_project = rope.base.project.Project('.')
	completer = RopeCompleter(editor, rope_project)
	editor.setWindowTitle("QTextEdit with a non-blocking Rope Assist Completer")
	editor.resize(600, 400)

	# placeholder
	words = [completer.model().index(row,0).data() for row in range(completer.model().rowCount())]
	editor.setPlaceholderText("Start typing...\n\neg.: " + ", ".join(words))
	
	# show window
	editor.show()

	#run app
	app.exec()