from pypy.objspace.flow.model import Variable, Constant, c_last_exception
from pypy.jit.metainterp.history import AbstractDescr, getkind
from pypy.rpython.lltypesystem import lltype


class SSARepr(object):
    def __init__(self, name):
        self.name = name
        self.insns = []
        self._insns_pos = None     # after being assembled

class Label(object):
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return "Label(%r)" % (self.name, )
    def __eq__(self, other):
        return isinstance(other, Label) and other.name == self.name

class TLabel(object):
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return "TLabel(%r)" % (self.name, )
    def __eq__(self, other):
        return isinstance(other, TLabel) and other.name == self.name

class Register(object):
    def __init__(self, kind, index):
        self.kind = kind          # 'int', 'ref' or 'float'
        self.index = index
    def __repr__(self):
        return "%%%s%d" % (self.kind[0], self.index)

class ListOfKind(object):
    # a list of Regs/Consts, all of the same 'kind'.
    # We cannot use a plain list, because we wouldn't know what 'kind' of
    # Regs/Consts would be expected in case the list is empty.
    def __init__(self, kind, content):
        assert kind in KINDS
        self.kind = kind
        self.content = tuple(content)
    def __repr__(self):
        return '%s%s' % (self.kind[0].upper(), list(self.content))
    def __iter__(self):
        return iter(self.content)
    def __nonzero__(self):
        return bool(self.content)
    def __eq__(self, other):
        return (isinstance(other, ListOfKind) and
                self.kind == other.kind and self.content == other.content)

class IndirectCallTargets(object):
    def __init__(self, lst):
        self.lst = lst       # list of JitCodes
    def __repr__(self):
        return '<IndirectCallTargets>'

KINDS = ['int', 'ref', 'float']

# ____________________________________________________________

def flatten_graph(graph, regallocs, _include_all_exc_links=False):
    """Flatten the graph into an SSARepr, with already-computed register
    allocations.  'regallocs' in a dict {kind: RegAlloc}."""
    flattener = GraphFlattener(graph, regallocs, _include_all_exc_links)
    flattener.enforce_input_args()
    flattener.generate_ssa_form()
    return flattener.ssarepr


class GraphFlattener(object):

    def __init__(self, graph, regallocs, _include_all_exc_links=False):
        self.graph = graph
        self.regallocs = regallocs
        self._include_all_exc_links = _include_all_exc_links
        self.registers = {}
        if graph:
            name = graph.name
        else:
            name = '?'
        self.ssarepr = SSARepr(name)

    def enforce_input_args(self):
        inputargs = self.graph.startblock.inputargs
        numkinds = {}
        for v in inputargs:
            kind = getkind(v.concretetype)
            if kind == 'void':
                continue
            curcol = self.regallocs[kind].getcolor(v)
            realcol = numkinds.get(kind, 0)
            numkinds[kind] = realcol + 1
            if curcol != realcol:
                assert curcol > realcol
                self.regallocs[kind].swapcolors(realcol, curcol)

    def generate_ssa_form(self):
        self.seen_blocks = {}
        self.make_bytecode_block(self.graph.startblock)

    def make_bytecode_block(self, block):
        if block.exits == ():
            self.make_return(block.inputargs)
            return
        if block in self.seen_blocks:
            self.emitline("goto", TLabel(block))
            self.emitline("---")
            return
        # inserting a goto not necessary, falling through
        self.seen_blocks[block] = True
        self.emitline(Label(block))
        #
        operations = block.operations
        for i, op in enumerate(operations):
            self.serialize_op(op)
        #
        self.insert_exits(block)

    def make_return(self, args):
        if len(args) == 1:
            # return from function
            [v] = args
            kind = getkind(v.concretetype)
            if kind == 'void':
                self.emitline("void_return")
            else:
                self.emitline("%s_return" % kind, self.getcolor(args[0]))
        elif len(args) == 2:
            # exception block, raising an exception from a function
            if isinstance(args[1], Variable):
                self.emitline("-live-")     # xxx hack
            self.emitline("raise", self.getcolor(args[1]))
        else:
            raise Exception("?")
        self.emitline("---")

    def make_link(self, link):
        if link.target.exits == ():
            self.make_return(link.args)
            return
        self.insert_renamings(link)
        self.make_bytecode_block(link.target)

    def make_exception_link(self, link):
        # Like make_link(), but also introduces the 'last_exception' and
        # 'last_exc_value' as variables if needed.  Also check if the link
        # is jumping directly to the re-raising exception block.
        assert link.last_exception is not None
        assert link.last_exc_value is not None
        if link.target.operations == () and link.args == [link.last_exception,
                                                          link.last_exc_value]:
            self.emitline("reraise")
            self.emitline("---")
            return   # done
        if link.last_exception in link.args:
            self.emitline("last_exception",
                          "->", self.getcolor(link.last_exception))
        if link.last_exc_value in link.args:
            self.emitline("last_exc_value",
                          "->", self.getcolor(link.last_exc_value))
        self.make_link(link)

    def insert_exits(self, block):
        if len(block.exits) == 1:
            # A single link, fall-through
            link = block.exits[0]
            assert link.exitcase is None
            self.make_link(link)
        #
        elif block.exitswitch is c_last_exception:
            # An exception block. See test_exc_exitswitch in test_flatten.py
            # for an example of what kind of code this makes.
            index = -1
            while True:
                lastopname = block.operations[index].opname
                if lastopname != '-live-':
                    break
                index -= 1
            assert block.exits[0].exitcase is None # is this always True?
            #
            if not self._include_all_exc_links:
                if index == -1:
                    # cannot raise: the last instruction is not
                    # actually a '-live-'
                    self.make_link(block.exits[0])
                    return
            # 
            self.emitline('catch_exception', TLabel(block.exits[0]))
            self.make_link(block.exits[0])
            self.emitline(Label(block.exits[0]))
            for link in block.exits[1:]:
                if (link.exitcase is Exception or
                    (link.exitcase is OverflowError and
                     lastopname.startswith('int_') and
                     lastopname.endswith('_ovf'))):
                    # this link captures all exceptions
                    self.make_exception_link(link)
                    break
                self.emitline('goto_if_exception_mismatch',
                              Constant(link.llexitcase,
                                       lltype.typeOf(link.llexitcase)),
                              TLabel(link))
                self.make_exception_link(link)
                self.emitline(Label(link))
            else:
                # no link captures all exceptions, so we have to put a reraise
                # for the other exceptions
                self.emitline("reraise")
                self.emitline("---")
        #
        elif len(block.exits) == 2 and (
                isinstance(block.exitswitch, tuple) or
                block.exitswitch.concretetype == lltype.Bool):
            # Two exit links with a boolean condition
            linkfalse, linktrue = block.exits
            if linkfalse.llexitcase == True:
                linkfalse, linktrue = linktrue, linkfalse
            opname = 'goto_if_not'
            livebefore = False
            if isinstance(block.exitswitch, tuple):
                # special case produced by jtransform.optimize_goto_if_not()
                opname = 'goto_if_not_' + block.exitswitch[0]
                opargs = block.exitswitch[1:]
                if opargs[-1] == '-live-before':
                    livebefore = True
                    opargs = opargs[:-1]
            else:
                assert block.exitswitch.concretetype == lltype.Bool
                opargs = [block.exitswitch]
            #
            lst = self.flatten_list(opargs) + [TLabel(linkfalse)]
            if livebefore:
                self.emitline('-live-')
            self.emitline(opname, *lst)
            if not livebefore:
                self.emitline('-live-', TLabel(linkfalse))
            # true path:
            self.make_link(linktrue)
            # false path:
            self.emitline(Label(linkfalse))
            self.make_link(linkfalse)
        #
        else:
            # A switch.
            #
            def emitdefaultpath():
                if block.exits[-1].exitcase == 'default':
                    self.make_link(block.exits[-1])
                else:
                    self.emitline("---")
            #
            self.emitline('-live-')
            switches = [link for link in block.exits
                        if link.exitcase != 'default']
            switches.sort(key=lambda link: link.llexitcase)
            kind = getkind(block.exitswitch.concretetype)
            if len(switches) >= 5 and kind == 'int':
                # A large switch on an integer, implementable efficiently
                # with the help of a SwitchDictDescr
                from pypy.jit.codewriter.jitcode import SwitchDictDescr
                switchdict = SwitchDictDescr()
                switchdict._labels = []
                self.emitline('switch', self.getcolor(block.exitswitch),
                                        switchdict)
                emitdefaultpath()
                #
                for switch in switches:
                    key = lltype.cast_primitive(lltype.Signed,
                                                switch.llexitcase)
                    switchdict._labels.append((key, TLabel(switch)))
                    # emit code for that path
                    self.emitline(Label(switch))
                    self.make_link(switch)
            #
            else:
                # A switch with several possible answers, though not too
                # many of them -- a chain of int_eq comparisons is fine
                assert kind == 'int'    # XXX
                color = self.getcolor(block.exitswitch)
                self.emitline('int_guard_value', color)
                for switch in switches:
                    # make the case described by 'switch'
                    self.emitline('goto_if_not_int_eq',
                                  color,
                                  Constant(switch.llexitcase,
                                           block.exitswitch.concretetype),
                                  TLabel(switch))
                    # emit code for the "taken" path
                    self.make_link(switch)
                    # finally, emit the label for the "non-taken" path
                    self.emitline(Label(switch))
                #
                emitdefaultpath()

    def insert_renamings(self, link):
        renamings = {}
        lst = [(self.getcolor(v), self.getcolor(link.target.inputargs[i]))
               for i, v in enumerate(link.args)
               if v.concretetype is not lltype.Void]
        lst.sort(key=lambda(v, w): w.index)
        for v, w in lst:
            if v == w:
                continue
            frm, to = renamings.setdefault(w.kind, ([], []))
            frm.append(v)
            to.append(w)
        for kind in KINDS:
            if kind in renamings:
                frm, to = renamings[kind]
                # Produce a series of %s_copy.  If there is a cycle, it
                # is handled with a %s_push to save the first value of
                # the cycle, some number of %s_copy, and finally a
                # %s_pop to load the last value.
                result = reorder_renaming_list(frm, to)
                for v, w in result:
                    if w is None:
                        self.emitline('%s_push' % kind, v)
                    elif v is None:
                        self.emitline('%s_pop' % kind, "->", w)
                    else:
                        self.emitline('%s_copy' % kind, v, "->", w)

    def emitline(self, *line):
        self.ssarepr.insns.append(line)

    def flatten_list(self, arglist):
        args = []
        for v in arglist:
            if isinstance(v, Variable):
                v = self.getcolor(v)
            elif isinstance(v, Constant):
                pass
            elif isinstance(v, ListOfKind):
                lst = [self.getcolor(x) for x in v]
                v = ListOfKind(v.kind, lst)
            elif isinstance(v, (AbstractDescr,
                                IndirectCallTargets)):
                pass
            else:
                raise NotImplementedError(type(v))
            args.append(v)
        return args

    def serialize_op(self, op):
        args = self.flatten_list(op.args)
        if op.result is not None:
            kind = getkind(op.result.concretetype)
            if kind != 'void':
                args.append("->")
                args.append(self.getcolor(op.result))
        self.emitline(op.opname, *args)

    def getcolor(self, v):
        if isinstance(v, Constant):
            return v
        kind = getkind(v.concretetype)
        col = self.regallocs[kind].getcolor(v)    # if kind=='void', fix caller
        try:
            r = self.registers[kind, col]
        except KeyError:
            r = self.registers[kind, col] = Register(kind, col)
        return r

# ____________________________________________________________

def reorder_renaming_list(frm, to):
    result = []
    pending_indices = range(len(to))
    while pending_indices:
        not_read = dict.fromkeys([frm[i] for i in pending_indices])
        still_pending_indices = []
        for i in pending_indices:
            if to[i] not in not_read:
                result.append((frm[i], to[i]))
            else:
                still_pending_indices.append(i)
        if len(pending_indices) == len(still_pending_indices):
            # no progress -- there is a cycle
            assert None not in not_read
            result.append((frm[pending_indices[0]], None))
            frm[pending_indices[0]] = None
            continue
        pending_indices = still_pending_indices
    return result
