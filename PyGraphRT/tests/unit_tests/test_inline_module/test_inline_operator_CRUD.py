"""Decorator contract: references follow names; redefinition replaces values.

These specifications intentionally require behavior beyond the current
implementation, which rejects duplicate operator names.
"""

from pygraphrt.inline_module import InlineModuleRT, MissingOperatorError, OperatorExistsError
import pytest
import pygraphrt as rt

@pytest.fixture
def im() -> InlineModuleRT:
    return InlineModuleRT()

class Test_CreateOp:
    def test_create_operator_from_function(self, im):
        def hello():
            return "hello"
        op = im._create_operator(hello)
        assert op() == "hello"

    def test_create_multiple_operators_from_same_function(self, im):
        def hello():
            return "hello"
        op1 = im._create_operator(hello)
        op2 = im._create_operator(hello)

        assert op1 != op2
        assert op1() == op2()

    def test_create_operator_from_lambda(self, im):
        op = im._create_operator(lambda: "LAMBDA")
        assert op() == "LAMBDA"
        assert op.get_name() == "<lambda>"

    def test_create_multiple_operators_with_lambda(self, im):
        op1 = im._create_operator(lambda: "LAMBDA1")
        op2 = im._create_operator(lambda: "LAMBDA2")
        
        assert op1() == "LAMBDA1"
        assert op2() == "LAMBDA2"


class Test_UpdateOp:
    def test_update_existing_operator(self, im):
        def hello():
            return "hello"
        op = im._create_operator(hello)
        assert op() == "hello"

        def goodbye():
            return "goodbye"
        im._update_operator(op, goodbye)
        assert op() == "goodbye"

    def test_update_not_existing_operator_raises(self, im):
        def hello():
            return "hello"
        
        other_module = InlineModuleRT()
        op_from_other_module = other_module._create_operator(hello)

        with pytest.raises(MissingOperatorError):
            im._update_operator(op_from_other_module, hello)


class Test_DeleteOperator:
    def test_delete_existing_operator(self, im):
        def hello():
            return "hello"
        op = im._create_operator(hello)
        assert op() == "hello"

        im.delete_operator(op)
        with pytest.raises(MissingOperatorError):
            im.get_operator(op)

    def test_delete_not_existing_operator_raises(self, im):
        def hello():
            return "hello"
        other_module = InlineModuleRT()
        op_from_other_module = other_module._create_operator(hello)

        with pytest.raises(MissingOperatorError):
            im.delete_operator(op_from_other_module)

class Test_SetOperator:
    def test_im_does_not_support_setting_operators(self, im):
        """Test that InlineModuleRT does not support setting operators.
        a SET operation creates a new Key if not present.
        OperatorReferences are the Keys. since IM owns its operators, setting them directly is not allowed.
        """
        def hello():
            return "hello"

        op = im._create_operator(hello)
        with pytest.raises(AttributeError):
            im._set_operator(op, hello)




