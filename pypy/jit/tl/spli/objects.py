from pypy.interpreter.baseobjspace import ObjSpace


class DumbObjSpace(ObjSpace):
    """Implement just enough of the ObjSpace API to satisfy PyCode."""

    def wrap(self, x):
        if isinstance(x, int):
            return Int(x)
        if isinstance(x, str):
            return Str(x)


class InvalidOperation(Exception):
    pass


class SPLIObject(object):

    def add(self, other):
        raise InvalidOperation

    def call(self, args):
        raise InvalidOperation


class Int(SPLIObject):

    def __init__(self, value):
        self.value = value

    def add(self, other):
        return Int(self.value + other.value)


class Str(SPLIObject):

    def __init__(self, value):
        self.value = value

    def add(self, other):
        return Str(self.value + other.value)


class Function(SPLIObject):

    def __init__(self, code):
        self.code = code

    def call(self, args):
        from pypy.jit.tl.spli import interpreter
        return interpreter.SPLIFrame(self.code).run()
