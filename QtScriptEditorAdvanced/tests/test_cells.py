import unittest
from typing import *
from pylive.QtScriptEditor.cell_support import Cell, cell_at_line, split_cells
from textwrap import dedent


class TestCellsSplit(unittest.TestCase):
	def setUp(self) -> None:
		self.script = dedent("""\
		# %% setup
		from textwrap import dedent

		script = \"\"\"
		# %% hello
		\"\"\"

		# %% update
		from pylive.QtLiveApp import display

		display(script)
		""")

	def test_cells_linenumber(self):
		cells = split_cells(self.script)
		self.assertEqual(cells[0].lineno, 1)
		self.assertEqual(cells[1].lineno, 8)

	def test_cells_heading_content(self):
		cells = split_cells(self.script)

		for cell in cells:
			cell_first_line = cell.content.split("\n")[0]
			self.assertTrue( cell_first_line.startswith("# %%") )

	def test_cell_split_includes_leading_whitspace(self):
		cells = split_cells(self.script)

		self.assertEqual(cells[1].lineCount(), 5)
		self.assertEqual(cells[1].content.split("\n")[-1], "")

	def test_cell_equality(self):
		cellsA = split_cells(self.script)
		cellsB = split_cells(self.script)

		self.assertEqual(cellsA[0], cellsB[0])
		self.assertNotEqual(cellsA[0], cellsB[1])


class TestStrippedCells(unittest.TestCase):
	def setUp(self) -> None:
		self.script = dedent("""\
		# %% setup
		from textwrap import dedent

		script = \"\"\"
		# %% hello
		\"\"\"

		# %% update
		from pylive.QtLiveApp import display

		display(script)
		""")

	def test_cells_linenumber(self):
		cells = split_cells(self.script, strip=True)
		self.assertEqual(cells[0].lineno, 1)
		self.assertEqual(cells[1].lineno, 8)

	def test_cells_heading_content(self):
		cells = split_cells(self.script)

		for cell in cells:
			cell_first_line = cell.content.split("\n")[0]
			self.assertTrue( cell_first_line.startswith("# %%") )

	def test_cell_split_includes_leading_whitspace(self):
		cells = split_cells(self.script, True)

		self.assertEqual(cells[1].lineCount(), 4)
		self.assertEqual(cells[1].content.split("\n")[-1], self.script.strip().split("\n")[-1])

	def test_line_with_stripped_cell(self):
		cells_full = split_cells(self.script, False)
		cells_stripped = split_cells(self.script, True)

		self.assertEqual(cells_full[1].lineno, 8)

		self.assertEqual(cell_at_line(cells_full, 7), cells_full[0])
		self.assertEqual(cell_at_line(cells_full, 8), cells_full[1])

		self.assertEqual(cell_at_line(cells_stripped, 6), cells_stripped[0])
		self.assertEqual(cell_at_line(cells_stripped, 7), None)
		self.assertEqual(cell_at_line(cells_stripped, 8), cells_stripped[1])


if __name__ == "__main__":
	unittest.main()
	