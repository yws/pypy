from rpython.rlib import rgc
from rpython.rlib import rposix_scandir
from rpython.rtyper.lltypesystem import lltype

from pypy.interpreter.gateway import unwrap_spec, WrappedDefault, interp2app
from pypy.interpreter.error import OperationError, oefmt, wrap_oserror2
from pypy.interpreter.typedef import TypeDef, GetSetProperty
from pypy.interpreter.baseobjspace import W_Root

from pypy.module.posix.interp_posix import unwrap_fd


@unwrap_spec(w_path=WrappedDefault(u"."))
def scandir(space, w_path):
    "scandir(path='.') -> iterator of DirEntry objects for given path"

    if space.isinstance_w(w_path, space.w_bytes):
        path_bytes = space.str0_w(w_path)
        result_is_bytes = True
    else:
        try:
            path_bytes = space.fsencode_w(w_path)
        except OperationError as operr:
            if operr.async(space):
                raise
            fd = unwrap_fd(space, w_path, "string, bytes or integer")
            XXXX
        result_is_bytes = False

    try:
        dirp = rposix_scandir.opendir(path_bytes)
    except OSError as e:
        raise wrap_oserror2(space, e, w_path)
    path_prefix = path_bytes
    if len(path_prefix) > 0 and path_prefix[-1] != '/':
        path_prefix += '/'
    w_path_prefix = space.newbytes(path_prefix)
    if not result_is_bytes:
        w_path_prefix = space.fsdecode(w_path_prefix)
    return W_ScandirIterator(space, dirp, w_path_prefix, result_is_bytes)


class W_ScandirIterator(W_Root):
    def __init__(self, space, dirp, w_path_prefix, result_is_bytes):
        self.space = space
        self.dirp = dirp
        self.w_path_prefix = w_path_prefix
        self.result_is_bytes = result_is_bytes

    @rgc.must_be_light_finalizer
    def __del__(self):
        if self.dirp:
            rposix_scandir.closedir(self.dirp)

    def iter_w(self):
        return self.space.wrap(self)

    def fail(self, err=None):
        dirp = self.dirp
        if dirp:
            self.dirp = lltype.nullptr(lltype.typeOf(dirp).TO)
            rposix_scandir.closedir(dirp)
        if err is None:
            raise OperationError(self.space.w_StopIteration, self.space.w_None)
        else:
            raise err

    def next_w(self):
        # XXX not safe against being called on several threads for
        # the same object, but I think that CPython has the same problem
        if not self.dirp:
            self.fail()
        #
        space = self.space
        while True:
            try:
                entry = rposix_scandir.nextentry(self.dirp)
            except StopIteration:
                self.fail()
            except OSError as e:
                self.fail(wrap_oserror(space, e))
            assert rposix_scandir.has_name_bytes(entry)
            name = rposix_scandir.get_name_bytes(entry)
            if name != '.' and name != '..':
                break
        #
        w_name = space.newbytes(name)
        result_is_bytes = self.result_is_bytes
        if not result_is_bytes:
            w_name = space.fsdecode(w_name)
        direntry = W_DirEntry(w_name, self.w_path_prefix, result_is_bytes)
        return space.wrap(direntry)


W_ScandirIterator.typedef = TypeDef(
    'posix.ScandirIterator',
    __iter__ = interp2app(W_ScandirIterator.iter_w),
    __next__ = interp2app(W_ScandirIterator.next_w),
)
W_ScandirIterator.typedef.acceptable_as_base_class = False


class W_DirEntry(W_Root):
    w_path = None

    def __init__(self, w_name, w_path_prefix, result_is_bytes):
        self.w_name = w_name
        self.w_path_prefix = w_path_prefix
        self.result_is_bytes = result_is_bytes

    def fget_name(self, space):
        return self.w_name

    def fget_path(self, space):
        w_path = self.w_path
        if w_path is None:
            w_path = space.add(self.w_path_prefix, self.w_name)
            self.w_path = w_path
        return w_path

W_DirEntry.typedef = TypeDef(
    'posix.DirEntry',
    name = GetSetProperty(W_DirEntry.fget_name,
                          doc="the entry's base filename, relative to "
                              'scandir() "path" argument'),
    path = GetSetProperty(W_DirEntry.fget_path,
                          doc="the entry's full path name; equivalent to "
                              "os.path.join(scandir_path, entry.name)"),
)
W_DirEntry.typedef.acceptable_as_base_class = False