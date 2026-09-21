from qtpy.QtCore import QStringListModel
from qtpy.QtWidgets import QCompleter, QPlainTextEdit, QLineEdit
from .textedit_completer import TextEditCompleter


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
