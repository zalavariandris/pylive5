
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced



if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication
    from textwrap import dedent

    app = QApplication([])
    editor = ScriptEditAdvanced()
    editor.setReadOnly(False)
    
    editor.setPlainText(dedent("""\
    def hello_world():
        print("Hello, World!")
        # This is a comment
        x = 42
        return x
    """))

    def validate_script(script:str):
        print("Validating script...")
        import ast
        try:
            editor.linter.clear()
            ast.parse(script)
        except SyntaxError as e:
            print("lint error:", e)
            editor.linter.lintException(e, 'underline')
        except Exception as e:
            print("lint error:", e)
            editor.linter.lintException(e, 'label')

    editor.textChanged.connect(lambda: 
        validate_script(editor.toPlainText()))


    editor.show()
    app.exec()
