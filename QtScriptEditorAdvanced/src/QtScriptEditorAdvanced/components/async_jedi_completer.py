from textwrap import dedent
from qtpy.QtCore import QObject, QRunnable, QThread, QThreadPool, QCoreApplication, Signal, QStringListModel
from qtpy.QtGui import QTextCursor
from qtpy.QtWidgets import QTextEdit, QPlainTextEdit, QLineEdit, QApplication, QWidget, QHBoxLayout
from typing import *
import jedi
# from traitlets.utils import text  # Import the Jedi library


from .jedi_completer import JediCompleter

import time
import logging
logger = logging.getLogger(__name__)


class JediWorkerTask(QObject, QRunnable):
	"""Encapsulates the rope task for the QThreadPool."""
	finished = Signal(list)
	exceptionThrown = Signal(Exception)

	def __init__(self, source_code: str, line: int, column:int):
		QObject.__init__(self)
		QRunnable.__init__(self)
		self.source_code = source_code
		self.line = line
		self.column = column
		logger.info("start jedi task")

	def run(self):
		"""Perform the jedi code assist task and invoke the callback."""
		# Check and print the thread details
		# make sure the current 
		app = QCoreApplication.instance()
		IsSeperateThread = app and QThread.currentThread() != app.thread()
		if not IsSeperateThread:
			logger.warning("warning: RopeTask does not run in a seperate thread")

		try:
			script = jedi.Script(code=self.source_code, path="<string>")
			completions = script.complete(line=self.line, column=self.column)
			self.finished.emit(completions)

		except Exception as e:
			self.exceptionThrown.emit(e)

class AsyncJediCompleter(JediCompleter):
	def __init__(self, textedit: QTextEdit | QPlainTextEdit):
		super().__init__(textedit)
		self._thread_pool = QThreadPool.globalInstance()
		self._active_tasks:List[JediWorkerTask] = []
		self.destroyed.connect(lambda: self.cancellAllTasks())

		# self.model().modelReset.connect(lambda: self.updateCompletionWidgets())

	def requestCompletions(self):
		logger.info('requestCompletions...')
		# cancel previous tasks
		self.cancellAllTasks()
		
		# get cursor info
		def get_cursor_info()->Tuple[str, str, int, int]:
			match self.widget():
				case QPlainTextEdit():
					textedit = cast(QPlainTextEdit, self.widget())
					source_code = textedit.toPlainText()
					cursor = QTextCursor(textedit.textCursor())
					lineno = cursor.blockNumber() + 1  # PySide6 line numbers are 0-based
					columnno = cursor.columnNumber()  # Current position within the line
					cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
					line_text = cursor.selectedText()

					return source_code, line_text, lineno, columnno
				case QLineEdit():
					lineedit = cast(QLineEdit, self.widget())
					lineno = 1
					columnno = lineedit.cursorPosition()
					source_code = lineedit.text()
					line_text = lineedit.text()
					return source_code, line_text, lineno, columnno
				case _:
					raise ValueError(f"widget shoudl be either a QPlainTextEdit or a QLineEdit, got: {self.widget()}")

		source_code, line_text, lineno, columnno = get_cursor_info()
		# get completions from jedi
		if line_text.split(" ")[-1].isidentifier() or line_text.endswith("."):
			jedi_task = JediWorkerTask(source_code, lineno, columnno)
			jedi_task.finished.connect(lambda completions:
				self._update_completion_model([completion.name for completion in completions]))
			self._active_tasks.append(jedi_task)
			self._thread_pool.start(jedi_task)

	def _update_completion_model(self, completions:List[str]):
		try:
			# Update proposals in the model
			string_list_model = cast(QStringListModel, self.model())
			string_list_model.setStringList([completion for completion in completions])

		except Exception as e:
			logger.warning(f"Error in requestCompletions: {e}")
			string_list_model = cast(QStringListModel, self.model())
			string_list_model.setStringList([])
			self.hint_label.hide()

	def cancellAllTasks(self):
		"""Cancel all running tasks by tracking task status."""
		self._active_tasks.clear()  # Clear the list of active tasks


if __name__ == "__main__":
	def hello(x:int):
		pass

	# Create app
	app = QApplication([])

	window = QWidget()
	mainLayout = QHBoxLayout()
	window.setLayout(mainLayout)

	# Create completing editor
	editor = QTextEdit()
	editor.setTabStopDistance(editor.fontMetrics().horizontalAdvance(' ')*4)
	mainLayout.addWidget(editor)
	completer = AsyncJediCompleter(editor)
	editor.setWindowTitle("QTextEdit with a non-blocking Jedi Assist Completer")
	editor.resize(800, 800)

	editor.setPlainText(dedent("""\
	class Dog:
		def __init__(self, name, height=1):
			self.name = name
			self.height = height

	mydog = Dog("buksi")
	"""))

	# COMPLETER INFO
	label = QTextEdit()
	label.setReadOnly(True)
	label.setText("jedi info at x,y")
	mainLayout.addWidget(label)

	def update_completion_info():
		source_code = editor.toPlainText()
		cursor = editor.textCursor()
		line = cursor.blockNumber() + 1  # PySide6 line numbers are 0-based
		column = cursor.columnNumber()  # Current position within the line
		script = jedi.Script(code=source_code, path="<string>")
		# completions = script.complete(line=line, column=column)
		context = script.get_context(line=line, column=column)
		signatures = script.get_signatures(line=line, column=column)
		the_help = script.help(line=line, column=column)
		infer = script.infer(line=line, column=column)


		label.setText(dedent(f"""\
		Jedi info at {line} {column}
		
		help: {the_help}
		context: {context}
		signatures: {signatures}
		infer: {infer}
		"""))


	editor.cursorPositionChanged.connect(lambda: update_completion_info())

	# Placeholder
	words = [completer.model().index(row, 0).data() for row in range(completer.model().rowCount())]
	editor.setPlaceholderText("Start typing...\n\neg.: " + ", ".join(words))

	# Show window
	window.show()

	# Run app
	app.exec()
