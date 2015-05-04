import py

from rpython.jit.metainterp.warmspot import ll_meta_interp, get_stats
from rpython.jit.metainterp.test.support import LLJitMixin
from rpython.jit.codewriter.policy import StopAtXPolicy
from rpython.jit.metainterp.resoperation import rop
from rpython.jit.metainterp import history
from rpython.rlib.jit import JitDriver, hint, set_param
from rpython.rlib.objectmodel import compute_hash
from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.rlib.rarithmetic import r_uint, intmask
from rpython.rlib.rawstorage import (alloc_raw_storage, raw_storage_setitem,
                                     free_raw_storage, raw_storage_getitem)

class VectorizeTests:
    enable_opts = 'intbounds:rewrite:virtualize:string:earlyforce:pure:heap:unroll'

    def setup_method(self, method):
        print "RUNNING", method.__name__

    def meta_interp(self, f, args, policy=None):
        return ll_meta_interp(f, args, enable_opts=self.enable_opts,
                              policy=policy,
                              CPUClass=self.CPUClass,
                              type_system=self.type_system,
                              vectorize=1)

    @py.test.mark.parametrize('i',[3,4,5,6,7,8,9,50])
    def test_vectorize_simple_load_arith_store_int_add_index(self,i):
        myjitdriver = JitDriver(greens = [],
                                reds = 'auto',
                                vectorize=True)
        def f(d):
            bc = d*rffi.sizeof(rffi.SIGNED)
            va = alloc_raw_storage(bc, zero=True)
            vb = alloc_raw_storage(bc, zero=True)
            vc = alloc_raw_storage(bc, zero=True)
            x = 1
            for i in range(d):
                j = i*rffi.sizeof(rffi.SIGNED)
                raw_storage_setitem(va, j, rffi.cast(rffi.SIGNED,i))
                raw_storage_setitem(vb, j, rffi.cast(rffi.SIGNED,i))
            i = 0
            while i < bc:
                myjitdriver.jit_merge_point()
                a = raw_storage_getitem(rffi.SIGNED,va,i)
                b = raw_storage_getitem(rffi.SIGNED,vb,i)
                c = a+b
                raw_storage_setitem(vc, i, rffi.cast(rffi.SIGNED,c))
                i += 1*rffi.sizeof(rffi.SIGNED)
            res = 0
            for i in range(d):
                res += raw_storage_getitem(rffi.SIGNED,vc,i*rffi.sizeof(rffi.SIGNED))

            free_raw_storage(va)
            free_raw_storage(vb)
            free_raw_storage(vc)
            return res
        res = self.meta_interp(f, [i])
        assert res == f(i)
        if i > 3:
            self.check_trace_count(1)

    @py.test.mark.parametrize('i',[1,2,3,8,17,128,130,500,501,502,1300])
    def test_vectorize_array_get_set(self,i):
        myjitdriver = JitDriver(greens = [],
                                reds = ['i','d','va','vb','vc'],
                                vectorize=True)
        T = lltype.Array(rffi.INT, hints={'nolength': True})
        def f(d):
            i = 0
            va = lltype.malloc(T, d, flavor='raw', zero=True)
            vb = lltype.malloc(T, d, flavor='raw', zero=True)
            vc = lltype.malloc(T, d, flavor='raw', zero=True)
            for j in range(d):
                va[j] = rffi.r_int(j)
                vb[j] = rffi.r_int(j)
            while i < d:
                myjitdriver.can_enter_jit(i=i, d=d, va=va, vb=vb, vc=vc)
                myjitdriver.jit_merge_point(i=i, d=d, va=va, vb=vb, vc=vc)

                a = va[i]
                b = vb[i]
                ec = intmask(a)+intmask(b)
                vc[i] = rffi.r_int(ec)

                i += 1
            res = 0
            for j in range(d):
                res += intmask(vc[j])
            lltype.free(va, flavor='raw')
            lltype.free(vb, flavor='raw')
            lltype.free(vc, flavor='raw')
            return res
        res = self.meta_interp(f, [i])
        assert res == f(i)
        #if 4 < i:
        #    self.check_trace_count(1)

    @py.test.mark.parametrize('i',[1,2,3,4,9])
    def test_vector_register_too_small_vector(self, i):
        myjitdriver = JitDriver(greens = [],
                                reds = 'auto',
                                vectorize=True)
        T = lltype.Array(rffi.SHORT, hints={'nolength': True})

        def g(d, va, vb):
            i = 0
            while i < d:
                myjitdriver.jit_merge_point()
                a = va[i]
                b = vb[i]
                ec = intmask(a) + intmask(b)
                va[i] = rffi.r_short(ec)
                i += 1

        def f(d):
            i = 0
            va = lltype.malloc(T, d+100, flavor='raw', zero=True)
            vb = lltype.malloc(T, d+100, flavor='raw', zero=True)
            for j in range(d+100):
                va[j] = rffi.r_short(1)
                vb[j] = rffi.r_short(2)

            g(d+100, va, vb)
            g(d, va, vb) # this iteration might not fit into the vector register

            res = intmask(va[d])
            lltype.free(va, flavor='raw')
            lltype.free(vb, flavor='raw')
            return res
        res = self.meta_interp(f, [i])
        assert res == f(i) == 3

class VectorizeLLtypeTests(VectorizeTests):
    pass

class TestLLtype(VectorizeLLtypeTests, LLJitMixin):
    pass
