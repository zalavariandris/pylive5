
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced
from QtScriptEditorAdvanced.components.python_keywords_completer import PythonKeywordsCompleter
from QtScriptEditorAdvanced.components.jedi_completer import JediCompleter
from QtScriptEditorAdvanced.components.async_jedi_completer import AsyncJediCompleter


if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication
    from textwrap import dedent

    app = QApplication([])
    editor = ScriptEditAdvanced(completer=AsyncJediCompleter)
    editor.setReadOnly(False)
    
    editor.setPlainText(dedent("""\
    def hello_world():
        print("Hello, World!")
        # This is a comment
        x = 42
        return x

    from vfxops.io import 
    """))

    def validate_script(script:str):
        print("Validating script...")
        import ast
        try:
            editor._linter.clear()
            ast.parse(script)
        except SyntaxError as e:
            print("lint error:", e)
            editor._linter.lintException(e, 'underline')
        except Exception as e:
            print("lint error:", e)
            editor._linter.lintException(e, 'label')

    editor.textChanged.connect(lambda: 
        validate_script(editor.toPlainText()))


    editor.show()
    app.exec()
