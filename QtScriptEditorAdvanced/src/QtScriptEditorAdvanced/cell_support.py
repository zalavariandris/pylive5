from typing import *

import re
from dataclasses import dataclass

@dataclass
class Cell:
	idx:int
	lineno:int # 1 based index
	content:str

	def lineCount(self):
		return len(self.content.split("\n"))

def split_cells(script:str, strip=False)->List[Cell]:
	"""
	returns a dict where the key is the first line,
	and the value si the cell content
	"""
	cell_pattern = r"#\s*%%" # Define a regex pattern to match the cell markers (`# %%`)
	
	cells:List[Cell] = []
	Scope="TEXT"
	for i, line in enumerate(script.split("\n")):

		code = line.split("#")[-1]
		CodeHasDocstring = code.count('"""')%2==1 or code.count("'''")%2==1
		if CodeHasDocstring and Scope !="DOCSTRING":
			# Enter multiline DOCSTRING
			Scope = "DOCSTRING"
		elif CodeHasDocstring and Scope == "DOCSTRING":
			# Exit multiline DOCSTRING
			Scope = "TEXT"

		CodeIsEmpty = False if len(code)>0 else True
		CodeIsComment= line.lstrip() and line.lstrip()[0] == "#"
		CodeIsHeading = re.match(cell_pattern, line.lstrip()) and Scope == "TEXT"


		if CodeIsHeading or i==0:
			cells.append(Cell(len(cells), i+1, line))
		else:
			cells[-1].content+=f"\n{line}"

	if strip:
		for cell in cells:
			cell.content = cell.content.strip()
	return [cell for cell in cells]

def cell_at_line(cells:List[Cell], lineno:int)->Cell|None:
	for cell in cells:
		if lineno>=cell.lineno and lineno<=cell.lineno+cell.lineCount()-1:
			return cell
	return None

if __name__ == "__main__":
	from textwrap import dedent
	from qtpy.QtCore import *
	from qtpy.QtGui import *
	from qtpy.QtWidgets import *
	from pylive.QtScriptEditor.script_edit import ScriptEdit
	app = QApplication()

	window = QWidget()
	layout = QHBoxLayout()
	window.setLayout(layout)

	editor = ScriptEdit()
	layout.addWidget(editor)

	cells_view = QPlainTextEdit()
	cells_view.setReadOnly(True)
	layout.addWidget(cells_view)

	def update_cells():
		script = editor.toPlainText()
		cells = [
			cell for cell in 
			re.split(r"(?=#.*%%.+\n)", script, flags=re.MULTILINE)
		]
		
		text = ""
		
		for i, cell in enumerate(cells):
			text+=dedent(f"""{i}.---------
			{cell}""")
		cells_view.setPlainText(text)

	editor.textChanged.connect(update_cells)

	editor.setPlainText(dedent('''\
#%% setup
from PySide6.QtWidgets import *
from pylive.QtLiveApp import display

#%% update
print(f"Print this {28} to the console!")

display("""\\
Display this *text* or any *QWidget* in the preview area.
""")'''))

	window.show()

	app.exec()